import os
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session
import pandas as pd
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash
from functools import wraps

app = Flask(__name__)
app.secret_key = 'clave_secreta_negocio_2025_segura'
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Decorador de login requerido
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Inicializar base de datos
def init_db():
    conn = sqlite3.connect('negocio.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS productos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    codigo TEXT UNIQUE NOT NULL,
                    descripcion TEXT NOT NULL,
                    precio REAL NOT NULL,
                    stock INTEGER NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS clientes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre TEXT NOT NULL,
                    telefono TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS ventas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT NOT NULL,
                cliente_id INTEGER NOT NULL,
                total REAL NOT NULL,
                metodo_pago TEXT,
                cuotas INTEGER
            )''')
    c.execute('''CREATE TABLE IF NOT EXISTS detalle_venta (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    venta_id INTEGER NOT NULL,
                    producto_id INTEGER NOT NULL,
                    cantidad INTEGER NOT NULL,
                    precio_unitario REAL NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL)''')
    
    # Insertar cliente genérico si no existe
    c.execute("SELECT COUNT(*) FROM clientes")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO clientes (nombre, telefono) VALUES ('Cliente General', '')")
    
    conn.commit()
    conn.close()

# === LOGIN / LOGOUT ===
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = sqlite3.connect('negocio.db')
        user = conn.execute("SELECT id, password_hash FROM usuarios WHERE username = ?", (username,)).fetchone()
        conn.close()
        
        if user and check_password_hash(user[1], password):
            session['user_id'] = user[0]
            flash("✅ Sesión iniciada", "success")
            return redirect(url_for('index'))
        else:
            flash("❌ Usuario o contraseña incorrectos", "error")
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()  # Limpia toda la sesión (carrito, cliente, login)
    flash("👋 Sesión cerrada", "success")
    return redirect(url_for('login'))

# === PÁGINA PRINCIPAL ===
@app.route('/')
@login_required
def index():
    conn = sqlite3.connect('negocio.db')
    c = conn.cursor()
    
    # Total de productos
    total_productos = c.execute("SELECT COUNT(*) FROM productos").fetchone()[0]
    
    # Total de clientes
    total_clientes = c.execute("SELECT COUNT(*) FROM clientes").fetchone()[0]
    
    # Ventas hoy
    hoy = datetime.now().strftime('%Y-%m-%d')
    ventas_hoy = c.execute("SELECT COUNT(*), COALESCE(SUM(total), 0) FROM ventas WHERE fecha LIKE ?", (hoy + '%',)).fetchone()
    cantidad_ventas_hoy = ventas_hoy[0]
    total_ventas_hoy = ventas_hoy[1]
    
    # Ventas este mes
    mes_actual = datetime.now().strftime('%Y-%m')
    ventas_mes = c.execute("SELECT COUNT(*), COALESCE(SUM(total), 0) FROM ventas WHERE strftime('%Y-%m', fecha) = ?", (mes_actual,)).fetchone()
    cantidad_ventas_mes = ventas_mes[0]
    total_ventas_mes = ventas_mes[1]
    
    # Últimas 5 ventas
    ultimas_ventas = c.execute("""
        SELECT v.id, v.fecha, c.nombre, v.total
        FROM ventas v
        JOIN clientes c ON v.cliente_id = c.id
        ORDER BY v.fecha DESC
        LIMIT 5
    """).fetchall()
    
    conn.close()
    
    return render_template(
        'index.html',
        total_productos=total_productos,
        total_clientes=total_clientes,
        cantidad_ventas_hoy=cantidad_ventas_hoy,
        total_ventas_hoy=total_ventas_hoy,
        cantidad_ventas_mes=cantidad_ventas_mes,
        total_ventas_mes=total_ventas_mes,
        ultimas_ventas=ultimas_ventas
    )

# === INVENTARIO ===
@app.route('/inventario')
@login_required
def inventario():
    page = request.args.get('page', 1, type=int)
    search_query = request.args.get('q', '').strip()
    filtro_stock = request.args.get('stock', '')
    orden_precio = request.args.get('orden', '')
    per_page = 20

    conn = sqlite3.connect('negocio.db')
    condiciones = []
    params = []
    
    if search_query:
        condiciones.append("(codigo LIKE ? OR descripcion LIKE ?)")
        params.extend([f'%{search_query}%', f'%{search_query}%'])
    
    if filtro_stock == 'sin_stock':
        condiciones.append("stock = 0")
    
    where_clause = "WHERE " + " AND ".join(condiciones) if condiciones else ""
    
    order_clause = ""
    if orden_precio == 'mayor':
        order_clause = "ORDER BY precio DESC"
    elif orden_precio == 'menor':
        order_clause = "ORDER BY precio ASC"
    else:
        order_clause = "ORDER BY id DESC"
    
    count_query = f"SELECT COUNT(*) FROM productos {where_clause}"
    total = conn.execute(count_query, params).fetchone()[0]
    
    offset = (page - 1) * per_page
    select_query = f"SELECT * FROM productos {where_clause} {order_clause} LIMIT ? OFFSET ?"
    productos = conn.execute(select_query, (*params, per_page, offset)).fetchall()
    
    conn.close()
    total_pages = (total + per_page - 1) // per_page

    return render_template(
        'inventario.html',
        productos=productos,
        page=page,
        total_pages=total_pages,
        total=total,
        search_query=search_query,
        filtro_stock=filtro_stock,
        orden_precio=orden_precio
    )
@app.route('/nuevo_producto', methods=['GET', 'POST'])
@login_required
def nuevo_producto():
    if request.method == 'POST':
        codigo = request.form.get('codigo', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        precio = request.form.get('precio', '').strip()
        stock = request.form.get('stock', '').strip()

        if not codigo or not descripcion or not precio or not stock:
            flash("❌ Todos los campos son obligatorios", "error")
            return render_template('nuevo_producto.html')

        try:
            precio = float(precio)
            stock = int(stock)
            if precio <= 0 or stock < 0:
                raise ValueError
        except ValueError:
            flash("❌ Precio debe ser un número positivo y stock un entero no negativo", "error")
            return render_template('nuevo_producto.html')

        try:
            conn = sqlite3.connect('negocio.db')
            conn.execute(
                "INSERT INTO productos (codigo, descripcion, precio, stock) VALUES (?, ?, ?, ?)",
                (codigo, descripcion, precio, stock)
            )
            conn.commit()
            flash("✅ Producto creado correctamente", "success")
            return redirect(url_for('inventario'))
        except sqlite3.IntegrityError:
            flash("❌ El código ya existe. Usa uno único.", "error")
        except Exception as e:
            flash(f"❌ Error al guardar: {str(e)}", "error")
        finally:
            conn.close()

    return render_template('nuevo_producto.html')

@app.route('/editar_producto/<int:producto_id>', methods=['GET', 'POST'])
@login_required
def editar_producto(producto_id):
    conn = sqlite3.connect('negocio.db')
    if request.method == 'POST':
        codigo = request.form.get('codigo', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        precio = request.form.get('precio', '').strip()
        stock = request.form.get('stock', '').strip()

        if not codigo or not descripcion or not precio or not stock:
            flash("❌ Todos los campos son obligatorios", "error")
        else:
            try:
                precio = float(precio)
                stock = int(stock)
                if precio <= 0 or stock < 0:
                    raise ValueError
                conn.execute(
                    "UPDATE productos SET codigo = ?, descripcion = ?, precio = ?, stock = ? WHERE id = ?",
                    (codigo, descripcion, precio, stock, producto_id)
                )
                conn.commit()
                flash("✅ Producto actualizado correctamente", "success")
                return redirect(url_for('inventario'))
            except ValueError:
                flash("❌ Precio debe ser positivo y stock un entero no negativo", "error")
            except sqlite3.IntegrityError:
                flash("❌ El código ya existe. Usa uno único.", "error")
            except Exception as e:
                flash(f"❌ Error: {str(e)}", "error")
    
    producto = conn.execute("SELECT * FROM productos WHERE id = ?", (producto_id,)).fetchone()
    conn.close()
    if not producto:
        flash("Producto no encontrado", "error")
        return redirect(url_for('inventario'))
    return render_template('editar_producto.html', producto=producto)

@app.route('/eliminar_producto/<int:producto_id>', methods=['POST'])
@login_required
def eliminar_producto(producto_id):
    conn = sqlite3.connect('negocio.db')
    tiene_ventas = conn.execute("SELECT COUNT(*) FROM detalle_venta WHERE producto_id = ?", (producto_id,)).fetchone()[0]
    if tiene_ventas > 0:
        flash("⚠️ No se puede eliminar: el producto ya fue vendido.", "error")
    else:
        conn.execute("DELETE FROM productos WHERE id = ?", (producto_id,))
        conn.commit()
        flash("✅ Producto eliminado", "success")
    conn.close()
    return redirect(url_for('inventario'))

@app.route('/cargar_excel', methods=['GET', 'POST'])
@login_required
def cargar_excel():
    if request.method == 'POST':
        file = request.files.get('archivo')
        if not file or not file.filename.endswith('.xlsx'):
            flash("Por favor sube un archivo .xlsx", "error")
            return redirect(request.url)
        
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        try:
            df = pd.read_excel(filepath)
            df.columns = df.columns.str.lower().str.strip()
            required = {'codigo', 'descripcion', 'precio', 'stock'}
            if not required.issubset(df.columns):
                missing = required - set(df.columns)
                flash(f"Faltan columnas: {missing}", "error")
                return redirect(request.url)

            conn = sqlite3.connect('negocio.db')
            for _, row in df.iterrows():
                conn.execute(
                    "INSERT OR REPLACE INTO productos (codigo, descripcion, precio, stock) VALUES (?, ?, ?, ?)",
                    (str(row['codigo']), str(row['descripcion']), float(row['precio']), int(row['stock']))
                )
            conn.commit()
            flash("✅ Productos cargados correctamente", "success")
        except Exception as e:
            flash("❌ Error al procesar el archivo. Asegúrate de que las columnas sean: codigo, descripcion, precio, stock (en minúsculas).", "error")
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)
        return redirect(url_for('inventario'))
    return render_template('cargar_excel.html')

# === CLIENTES ===
@app.route('/clientes')
@login_required
def clientes():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    conn = sqlite3.connect('negocio.db')
    total = conn.execute("SELECT COUNT(*) FROM clientes").fetchone()[0]
    offset = (page - 1) * per_page
    clientes_lista = conn.execute(
        "SELECT * FROM clientes LIMIT ? OFFSET ?", (per_page, offset)
    ).fetchall()
    conn.close()
    total_pages = (total + per_page - 1) // per_page
    return render_template('clientes.html', clientes=clientes_lista, page=page, total_pages=total_pages, total=total)

@app.route('/nuevo_cliente', methods=['GET', 'POST'])
@login_required
def nuevo_cliente():
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        telefono = request.form.get('telefono', '').strip()
        if not nombre:
            flash("❌ El nombre es obligatorio", "error")
        else:
            try:
                conn = sqlite3.connect('negocio.db')
                conn.execute("INSERT INTO clientes (nombre, telefono) VALUES (?, ?)", (nombre, telefono))
                conn.commit()
                flash("✅ Cliente creado correctamente", "success")
                return redirect(url_for('clientes'))
            except Exception as e:
                flash(f"❌ Error: {str(e)}", "error")
            finally:
                conn.close()
    return render_template('nuevo_cliente.html')

@app.route('/cliente/<int:cliente_id>')
@login_required
def historial_cliente(cliente_id):
    conn = sqlite3.connect('negocio.db')
    cliente = conn.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
    if not cliente:
        flash("Cliente no encontrado", "error")
        return redirect(url_for('clientes'))
    
    ventas = conn.execute("""
        SELECT v.id, v.fecha, v.total
        FROM ventas v
        WHERE v.cliente_id = ?
        ORDER BY v.fecha DESC
    """, (cliente_id,)).fetchall()
    
    ventas_detalle = []
    for venta in ventas:
        detalle = conn.execute("""
            SELECT p.descripcion, dv.cantidad, dv.precio_unitario
            FROM detalle_venta dv
            JOIN productos p ON dv.producto_id = p.id
            WHERE dv.venta_id = ?
        """, (venta[0],)).fetchall()
        ventas_detalle.append({
            'id': venta[0],
            'fecha': venta[1],
            'total': venta[2],
            'detalle': detalle
        })
    
    conn.close()
    return render_template('historial_cliente.html', cliente=cliente, ventas=ventas_detalle)

# === CARRITO Y VENTAS ===
@app.route('/guardar_cliente', methods=['POST'])
@login_required
def guardar_cliente():
    cliente_id = request.form.get('cliente_id')
    if cliente_id:
        session['cliente_id_seleccionado'] = int(cliente_id)
    return redirect(url_for('ventas'))

@app.route('/ventas')
@login_required
def ventas():
    cliente_id_sesion = session.get('cliente_id_seleccionado')
    
    conn = sqlite3.connect('negocio.db')
    clientes = conn.execute("SELECT id, nombre FROM clientes").fetchall()
    productos = conn.execute("SELECT id, codigo, descripcion, precio, stock FROM productos WHERE stock > 0").fetchall()
    conn.close()
    
    carrito = session.get('carrito', [])
    total = sum(item['subtotal'] for item in carrito)
    
    return render_template(
        'ventas.html', 
        clientes=clientes, 
        productos=productos, 
        carrito=carrito, 
        total=total,
        cliente_id_seleccionado=cliente_id_sesion
    )

@app.route('/agregar_al_carrito', methods=['POST'])
@login_required
def agregar_al_carrito():
    producto_id = request.form.get('producto_id', type=int)
    cantidad = request.form.get('cantidad', type=int)
    
    if not producto_id or not cantidad or cantidad <= 0:
        flash("❌ Cantidad inválida", "error")
        return redirect(url_for('ventas'))
    
    conn = sqlite3.connect('negocio.db')
    prod = conn.execute("SELECT id, codigo, descripcion, precio, stock FROM productos WHERE id = ?", (producto_id,)).fetchone()
    conn.close()
    
    if not prod:
        flash("❌ Producto no encontrado", "error")
        return redirect(url_for('ventas'))
    
    if prod[4] < cantidad:
        flash(f"❌ Stock insuficiente. Disponible: {prod[4]}", "error")
        return redirect(url_for('ventas'))
    
    # Obtener carrito actual
    carrito = session.get('carrito', [])
    
    # Verificar si el producto ya está en el carrito
    producto_existente = None
    for item in carrito:
        if item['producto_id'] == producto_id:
            producto_existente = item
            break
    
    if producto_existente:
        # Sumar cantidades
        nueva_cantidad = producto_existente['cantidad'] + cantidad
        # Verificar stock total
        if prod[4] < nueva_cantidad:
            flash(f"❌ No hay suficiente stock. Máximo disponible: {prod[4]}", "error")
            return redirect(url_for('ventas'))
        producto_existente['cantidad'] = nueva_cantidad
        producto_existente['subtotal'] = producto_existente['precio'] * nueva_cantidad
    else:
        # Agregar nuevo producto
        subtotal = prod[3] * cantidad
        carrito.append({
            'producto_id': prod[0],
            'codigo': prod[1],
            'descripcion': prod[2],
            'precio': prod[3],
            'cantidad': cantidad,
            'subtotal': subtotal
        })
    
    session['carrito'] = carrito
    flash("✅ Producto agregado al carrito", "success")
    return redirect(url_for('ventas'))
@app.route('/actualizar_carrito', methods=['POST'])
@login_required
def actualizar_carrito():
    index = request.form.get('index', type=int)
    nueva_cantidad = request.form.get('cantidad', type=int)
    
    carrito = session.get('carrito', [])
    if 0 <= index < len(carrito) and nueva_cantidad > 0:
        item = carrito[index]
        conn = sqlite3.connect('negocio.db')
        stock = conn.execute("SELECT stock FROM productos WHERE id = ?", (item['producto_id'],)).fetchone()
        conn.close()
        if stock and stock[0] >= nueva_cantidad:
            item['cantidad'] = nueva_cantidad
            item['subtotal'] = item['precio'] * nueva_cantidad
            session['carrito'] = carrito
        else:
            flash(f"❌ Stock insuficiente para {item['descripcion']}", "error")
    return redirect(url_for('ventas'))

@app.route('/eliminar_del_carrito/<int:index>')
@login_required
def eliminar_del_carrito(index):
    carrito = session.get('carrito', [])
    if 0 <= index < len(carrito):
        carrito.pop(index)
        session['carrito'] = carrito
    return redirect(url_for('ventas'))

@app.route('/vaciar_carrito')
@login_required
def vaciar_carrito():
    session.pop('carrito', None)
    return redirect(url_for('ventas'))
@app.route('/seleccionar_pago', methods=['GET', 'POST'])
@login_required
def seleccionar_pago():
    carrito = session.get('carrito', [])
    cliente_id = session.get('cliente_id_seleccionado')
    
    if not carrito or not cliente_id:
        flash("❌ Carrito vacío o cliente no seleccionado", "error")
        return redirect(url_for('ventas'))
    
    if request.method == 'POST':
        metodo = request.form.get('metodo_pago')
        cuotas = request.form.get('cuotas', type=int)
        
        if metodo not in ['efectivo', 'transferencia', 'tarjeta']:
            flash("❌ Método de pago inválido", "error")
            return redirect(request.url)
        
        if metodo == 'tarjeta' and cuotas not in [2, 3, 6]:
            flash("❌ Cuotas inválidas", "error")
            return redirect(request.url)
        
        # Guardar en sesión temporalmente
        session['metodo_pago'] = metodo
        session['cuotas_pago'] = cuotas if metodo == 'tarjeta' else None
        
        return redirect(url_for('confirmar_venta'))
    
    total = sum(item['subtotal'] for item in carrito)
    return render_template('seleccionar_pago.html', total=total)
@app.route('/confirmar_venta', methods=['POST'])
@login_required
def confirmar_venta():
    # Obtener datos del FORMULARIO (no de la sesión)
    metodo_pago = request.form.get('metodo_pago')
    cuotas = request.form.get('cuotas', type=int)
    
    # Obtener carrito y cliente de la SESIÓN
    carrito = session.get('carrito', [])
    cliente_id = session.get('cliente_id_seleccionado')
    
    # Validar todo
    if not carrito or not cliente_id or not metodo_pago:
        flash("❌ Datos incompletos", "error")
        return redirect(url_for('ventas'))
    
    if metodo_pago not in ['efectivo', 'transferencia', 'tarjeta']:
        flash("❌ Método de pago inválido", "error")
        return redirect(url_for('ventas'))
    
    if metodo_pago == 'tarjeta':
        if cuotas not in [2, 3, 6]:
            flash("❌ Cuotas inválidas", "error")
            return redirect(url_for('seleccionar_pago'))
    else:
        cuotas = None  # Asegurar que sea NULL para otros métodos

    # ... resto del código para registrar la venta ...
    conn = sqlite3.connect('negocio.db')
    try:
        # Verificar stock
        for item in carrito:
            stock_actual = conn.execute("SELECT stock FROM productos WHERE id = ?", (item['producto_id'],)).fetchone()
            if not stock_actual or stock_actual[0] < item['cantidad']:
                flash(f"❌ Stock insuficiente para {item['descripcion']}", "error")
                conn.rollback()
                return redirect(url_for('ventas'))
        
        # Registrar venta
        fecha = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        total_venta = sum(item['subtotal'] for item in carrito)
        conn.execute("""
            INSERT INTO ventas (fecha, cliente_id, total, metodo_pago, cuotas)
            VALUES (?, ?, ?, ?, ?)
        """, (fecha, cliente_id, total_venta, metodo_pago, cuotas))
        
        venta_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        
        # Registrar detalle
        for item in carrito:
            conn.execute("""
                INSERT INTO detalle_venta (venta_id, producto_id, cantidad, precio_unitario)
                VALUES (?, ?, ?, ?)
            """, (venta_id, item['producto_id'], item['cantidad'], item['precio']))
            conn.execute("UPDATE productos SET stock = stock - ? WHERE id = ?", (item['cantidad'], item['producto_id']))
        
        conn.commit()
        
        # Limpiar sesión
        session.pop('carrito', None)
        session.pop('cliente_id_seleccionado', None)
        session.pop('metodo_pago', None)
        session.pop('cuotas_pago', None)
        
        flash("✅ Venta registrada con éxito", "success")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Error al registrar venta: {str(e)}", "error")
    finally:
        conn.close()
    
    return redirect(url_for('ventas'))

# === HISTORIAL DE VENTAS GENERAL ===
@app.route('/ventas_historial')
@login_required
def ventas_historial():
    page = request.args.get('page', 1, type=int)
    search_id = request.args.get('id', '').strip()  # Búsqueda por ID
    per_page = 20

    conn = sqlite3.connect('negocio.db')
    
    if search_id:
        # Buscar venta específica por ID
        try:
            venta_id = int(search_id)
            total = 1
            ventas = conn.execute("""
                SELECT v.id, v.fecha, c.nombre, v.total
                FROM ventas v
                JOIN clientes c ON v.cliente_id = c.id
                WHERE v.id = ?
                ORDER BY v.fecha DESC
            """, (venta_id,)).fetchall()
            total_pages = 1
            page = 1
        except ValueError:
            flash("❌ El ID debe ser un número", "error")
            ventas = []
            total = 0
            total_pages = 0
    else:
        # Mostrar todas las ventas (con paginación)
        total = conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0]
        offset = (page - 1) * per_page
        ventas = conn.execute("""
            SELECT v.id, v.fecha, c.nombre, v.total
            FROM ventas v
            JOIN clientes c ON v.cliente_id = c.id
            ORDER BY v.fecha DESC
            LIMIT ? OFFSET ?
        """, (per_page, offset)).fetchall()
        total_pages = (total + per_page - 1) // per_page
    
    conn.close()
    return render_template('ventas_historial.html', ventas=ventas, page=page, total_pages=total_pages, total=total, search_id=search_id)
@app.route('/venta/<int:venta_id>')
@login_required
def detalle_venta(venta_id):
    conn = sqlite3.connect('negocio.db')
    # Obtener datos de la venta
    venta = conn.execute("""
        SELECT v.id, v.fecha, c.nombre, v.total, v.metodo_pago, v.cuotas
        FROM ventas v
        JOIN clientes c ON v.cliente_id = c.id
        WHERE v.id = ?
    """, (venta_id,)).fetchone()
    
    if not venta:
        conn.close()
        flash("Venta no encontrada", "error")
        return redirect(url_for('ventas_historial'))
    
    # Obtener productos de la venta
    productos = conn.execute("""
        SELECT p.descripcion, dv.cantidad, dv.precio_unitario
        FROM detalle_venta dv
        JOIN productos p ON dv.producto_id = p.id
        WHERE dv.venta_id = ?
    """, (venta_id,)).fetchall()
    
    conn.close()
    
    return render_template('detalle_venta.html', venta=venta, productos=productos)
# === REPORTES ===
@app.route('/reporte/<formato>')
@login_required
def reporte(formato):
    conn = sqlite3.connect('negocio.db')
    mes_actual = datetime.now().strftime('%Y-%m')
    df = pd.read_sql_query("""
        SELECT v.fecha, c.nombre AS cliente, p.descripcion AS producto,
               dv.cantidad, dv.precio_unitario, (dv.cantidad * dv.precio_unitario) AS subtotal
        FROM ventas v
        JOIN detalle_venta dv ON v.id = dv.venta_id
        JOIN clientes c ON v.cliente_id = c.id
        JOIN productos p ON dv.producto_id = p.id
        WHERE strftime('%Y-%m', v.fecha) = ?
        ORDER BY v.fecha
    """, conn, params=(mes_actual,))

    if formato == 'excel':
        output_path = 'reporte_ventas.xlsx'
        df.to_excel(output_path, index=False)
        return send_file(output_path, as_attachment=True)

    elif formato == 'pdf':
        output_path = 'reporte_ventas.csv'
        df.to_csv(output_path, index=False)
        return send_file(output_path, as_attachment=True)

    conn.close()
    return "Formato no soportado"

if __name__ == '__main__':
    init_db()
    print("Sistema iniciado. Abre http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)
