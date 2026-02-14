import os
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
import pandas as pd
import csv

app = Flask(__name__)
app.secret_key = 'clave_secreta_negocio_2025_segura'
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# === DECORADOR DE LOGIN ===
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# === INICIALIZAR BASE DE DATOS ===
def init_db():
    conn = sqlite3.connect('negocio.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS productos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo TEXT UNIQUE NOT NULL,
        descripcion TEXT NOT NULL,
        precio REAL NOT NULL,
        stock INTEGER NOT NULL
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS clientes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        cuit TEXT,
        telefono TEXT
    )''')
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
        precio_unitario REAL NOT NULL
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL
    )''')
    # Insertar cliente por defecto si no existe
    c.execute("SELECT COUNT(*) FROM clientes")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO clientes (nombre, telefono) VALUES ('Consumidor Final', '')")
    conn.commit()
    conn.close()

# === FILTRO JINJA ===
@app.template_filter('pesos')
def formato_pesos(valor):
    try:
        return f"{float(valor):,.0f}".replace(',', '.')
    except:
        return valor

# === RUTAS DE AUTENTICACIÓN ===
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
    session.clear()
    flash("👋 Sesión cerrada", "success")
    return redirect(url_for('login'))

# === PÁGINA PRINCIPAL ===
@app.route('/')
@login_required
def index():
    conn = sqlite3.connect('negocio.db')
    c = conn.cursor()
    total_productos = c.execute("SELECT COUNT(*) FROM productos").fetchone()[0]
    total_clientes = c.execute("SELECT COUNT(*) FROM clientes").fetchone()[0]
    hoy = datetime.now().strftime('%Y-%m-%d')
    ventas_hoy = c.execute("SELECT COUNT(*), COALESCE(SUM(total), 0) FROM ventas WHERE fecha LIKE ?", (hoy + '%',)).fetchone()
    mes_actual = datetime.now().strftime('%Y-%m')
    ventas_mes = c.execute("SELECT COUNT(*), COALESCE(SUM(total), 0) FROM ventas WHERE strftime('%Y-%m', fecha) = ?", (mes_actual,)).fetchone()
    ultimas_ventas = c.execute("""
        SELECT v.id, v.fecha, c.nombre, v.total
        FROM ventas v
        JOIN clientes c ON v.cliente_id = c.id
        ORDER BY v.fecha DESC LIMIT 5
    """).fetchall()
    conn.close()
    return render_template(
        'index.html',
        total_productos=total_productos,
        total_clientes=total_clientes,
        cantidad_ventas_hoy=ventas_hoy[0],
        total_ventas_hoy=ventas_hoy[1],
        cantidad_ventas_mes=ventas_mes[0],
        total_ventas_mes=ventas_mes[1],
        ultimas_ventas=ultimas_ventas
    )

# === INVENTARIO ===
@app.route('/inventario')
@login_required
def inventario():
    page = request.args.get('page', 1, type=int)
    search_query = request.args.get('q', '').strip()
    filtro_stock = request.args.get('stock', '')
    orden = request.args.get('orden', '')
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
    
    order_clause = "ORDER BY id DESC"
    if orden == 'mayor': order_clause = "ORDER BY precio DESC"
    elif orden == 'menor': order_clause = "ORDER BY precio ASC"
    elif orden == 'nuevo': order_clause = "ORDER BY id DESC"
    elif orden == 'viejo': order_clause = "ORDER BY id ASC"

    total = conn.execute(f"SELECT COUNT(*) FROM productos {where_clause}", params).fetchone()[0]
    offset = (page - 1) * per_page
    productos = conn.execute(f"SELECT * FROM productos {where_clause} {order_clause} LIMIT ? OFFSET ?", (*params, per_page, offset)).fetchall()
    conn.close()

    total_pages = (total + per_page - 1) // per_page
    return render_template('inventario.html', productos=productos, page=page, total_pages=total_pages, total=total,
                           search_query=search_query, filtro_stock=filtro_stock, orden=orden)

# === PRODUCTOS: CRUD ===
@app.route('/nuevo_producto', methods=['GET', 'POST'])
@login_required
def nuevo_producto():
    if request.method == 'POST':
        codigo = request.form.get('codigo', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        precio = request.form.get('precio', '').strip()
        stock = request.form.get('stock', '').strip()
        if not all([codigo, descripcion, precio, stock]):
            flash("❌ Todos los campos son obligatorios", "error")
            return render_template('nuevo_producto.html')
        try:
            precio = float(precio)
            stock = int(stock)
            if precio <= 0 or stock < 0:
                raise ValueError
            conn = sqlite3.connect('negocio.db')
            conn.execute("INSERT INTO productos (codigo, descripcion, precio, stock) VALUES (?, ?, ?, ?)",
                         (codigo, descripcion, precio, stock))
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
    producto = conn.execute("SELECT * FROM productos WHERE id = ?", (producto_id,)).fetchone()
    if not producto:
        flash("Producto no encontrado", "error")
        return redirect(url_for('inventario'))
    if request.method == 'POST':
        codigo = request.form.get('codigo', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        precio = request.form.get('precio', '').strip()
        stock = request.form.get('stock', '').strip()
        if not all([codigo, descripcion, precio, stock]):
            flash("❌ Todos los campos son obligatorios", "error")
        else:
            try:
                precio = float(precio)
                stock = int(stock)
                if precio <= 0 or stock < 0:
                    raise ValueError
                conn.execute("UPDATE productos SET codigo = ?, descripcion = ?, precio = ?, stock = ? WHERE id = ?",
                             (codigo, descripcion, precio, stock, producto_id))
                conn.commit()
                flash("✅ Producto actualizado correctamente", "success")
                return redirect(url_for('inventario'))
            except sqlite3.IntegrityError:
                flash("❌ El código ya existe. Usa uno único.", "error")
            except Exception as e:
                flash(f"❌ Error: {str(e)}", "error")
    conn.close()
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

# === CARGA MASIVA ===
@app.route('/cargar_tiendanube', methods=['POST'])
@login_required
def cargar_tiendanube():
    file = request.files.get('file')
    if not file or not file.filename.endswith('.csv'):
        flash("❌ Archivo inválido. Debe ser .csv", "error")
        return redirect(url_for('inventario'))
    
    try:
        raw_data = file.stream.read()
        for encoding in ['utf-8', 'latin-1', 'cp1252']:
            try:
                decoded = raw_data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError("Codificación no soportada")
        
        reader = csv.reader(decoded.splitlines(), delimiter=';')
        next(reader)  # encabezado
        
        conn = sqlite3.connect('negocio.db')
        cursor = conn.cursor()
        count = 0
        for row in reader:
            if len(row) < 17:
                continue
            nombre = row[1].strip()
            precio_str = row[9].replace('.', '').replace(',', '.') if row[9] else '0'
            stock_str = row[15] if row[15] else '0'
            sku = row[16].strip() or None
            if not sku and not nombre:
                continue
            try:
                precio = float(precio_str)
                stock = int(float(stock_str))
            except ValueError:
                continue
            codigo = sku or nombre[:20].replace(' ', '_')
            cursor.execute("""
                INSERT INTO productos (codigo, descripcion, precio, stock)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(codigo) DO UPDATE SET
                    descripcion = excluded.descripcion,
                    precio = excluded.precio,
                    stock = excluded.stock
            """, (codigo, nombre, precio, stock))
            count += 1
        conn.commit()
        conn.close()
        flash(f"✅ {count} productos cargados/actualizados desde Tienda Nube", "success")
    except Exception as e:
        flash(f"❌ Error al procesar el archivo: {str(e)}", "error")
    return redirect(url_for('inventario'))

# === CLIENTES ===
@app.route('/clientes')
@login_required
def clientes():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    conn = sqlite3.connect('negocio.db')
    total = conn.execute("SELECT COUNT(*) FROM clientes").fetchone()[0]
    offset = (page - 1) * per_page
    lista = conn.execute("SELECT * FROM clientes LIMIT ? OFFSET ?", (per_page, offset)).fetchall()
    conn.close()
    total_pages = (total + per_page - 1) // per_page
    return render_template('clientes.html', clientes=lista, page=page, total_pages=total_pages, total=total)

@app.route('/nuevo_cliente', methods=['GET', 'POST'])
@login_required
def nuevo_cliente():
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        cuit = request.form.get('cuit', '').strip()
        telefono = request.form.get('telefono', '').strip()
        if not nombre:
            flash("❌ El nombre es obligatorio", "error")
        else:
            try:
                conn = sqlite3.connect('negocio.db')
                if cuit:
                    existente = conn.execute("SELECT id FROM clientes WHERE cuit = ?", (cuit,)).fetchone()
                    if existente:
                        flash("❌ El CUIT ya está registrado para otro cliente", "error")
                        return render_template('nuevo_cliente.html')
                conn.execute("INSERT INTO clientes (nombre, cuit, telefono) VALUES (?, ?, ?)", (nombre, cuit, telefono))
                conn.commit()
                flash("✅ Cliente creado correctamente", "success")
                return redirect(url_for('clientes'))
            except Exception as e:
                flash(f"❌ Error: {str(e)}", "error")
            finally:
                conn.close()
    return render_template('nuevo_cliente.html')

# === VENTAS Y CARRITO ===
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
    cliente_id = session.get('cliente_id_seleccionado')
    conn = sqlite3.connect('negocio.db')
    clientes = conn.execute("SELECT id, nombre FROM clientes").fetchall()
    productos = conn.execute("SELECT id, codigo, descripcion, precio, stock FROM productos WHERE stock > 0").fetchall()
    conn.close()
    carrito = session.get('carrito', [])
    total = sum(item['precio'] * item['cantidad'] for item in carrito)
    return render_template('ventas.html', clientes=clientes, productos=productos, carrito=carrito, total=total,
                           cliente_id_seleccionado=cliente_id)

@app.route('/agregar_al_carrito', methods=['POST'])
@login_required
def agregar_al_carrito():
    producto_id = request.form.get('producto_id')
    cantidad = int(request.form.get('cantidad', 1))
    if not producto_id or cantidad <= 0:
        flash("❌ Cantidad o producto inválido", "error")
        return redirect(url_for('ventas'))
    conn = sqlite3.connect('negocio.db')
    p = conn.execute("SELECT id, codigo, descripcion, precio, stock FROM productos WHERE id = ?", (producto_id,)).fetchone()
    conn.close()
    if not p:
        flash("❌ Producto no encontrado", "error")
        return redirect(url_for('ventas'))
    if cantidad > p[4]:
        flash(f"❌ Stock insuficiente. Disponible: {p[4]}", "error")
        return redirect(url_for('ventas'))
    carrito = session.get('carrito', [])
    for item in carrito:
        if item['id'] == p[0]:
            nueva_cant = item['cantidad'] + cantidad
            if nueva_cant <= p[4]:
                item['cantidad'] = nueva_cant
            else:
                flash(f"❌ No hay suficiente stock para {p[2]}", "error")
            session['carrito'] = carrito
            flash(f"✅ {p[2]} cantidad actualizada", "success")
            return redirect(url_for('ventas'))
    carrito.append({
        'id': p[0],
        'codigo': p[1],
        'descripcion': p[2],
        'precio_original': float(p[3]),
        'precio': float(p[3]),
        'cantidad': cantidad
    })
    session['carrito'] = carrito
    flash(f"✅ {p[2]} agregado al carrito", "success")
    return redirect(url_for('ventas'))

@app.route('/actualizar_precio_carrito', methods=['POST'])
@login_required
def actualizar_precio_carrito():
    index = int(request.form.get('index'))
    nuevo_precio = float(request.form.get('nuevo_precio'))
    carrito = session.get('carrito', [])
    if 0 <= index < len(carrito) and nuevo_precio > 0:
        carrito[index]['precio'] = nuevo_precio
        session['carrito'] = carrito
        flash("✅ Precio actualizado", "success")
    else:
        flash("❌ Error al actualizar el precio", "error")
    return redirect(url_for('ventas'))

@app.route('/actualizar_carrito', methods=['POST'])
@login_required
def actualizar_carrito():
    index = int(request.form.get('index'))
    nueva_cantidad = int(request.form.get('cantidad'))
    carrito = session.get('carrito', [])
    if not (0 <= index < len(carrito)) or nueva_cantidad <= 0:
        flash("❌ Datos inválidos", "error")
        return redirect(url_for('ventas'))
    item = carrito[index]
    conn = sqlite3.connect('negocio.db')
    stock_actual = conn.execute("SELECT stock FROM productos WHERE id = ?", (item['id'],)).fetchone()
    conn.close()
    if not stock_actual or nueva_cantidad > stock_actual[0]:
        flash(f"❌ Stock insuficiente. Disponible: {stock_actual[0] if stock_actual else 0}", "error")
        return redirect(url_for('ventas'))
    item['cantidad'] = nueva_cantidad
    session['carrito'] = carrito
    flash("✅ Cantidad actualizada", "success")
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
        session['metodo_pago'] = metodo
        session['cuotas_pago'] = cuotas if metodo == 'tarjeta' else None
        return redirect(url_for('confirmar_venta'))
    total = sum(item['precio'] * item['cantidad'] for item in carrito)
    return render_template('seleccionar_pago.html', total=total)

@app.route('/confirmar_venta', methods=['POST'])
@login_required
def confirmar_venta():
    metodo_pago = request.form.get('metodo_pago')
    cuotas = request.form.get('cuotas', type=int)
    carrito = session.get('carrito', [])
    cliente_id = session.get('cliente_id_seleccionado')
    if not carrito or not cliente_id or not metodo_pago:
        flash("❌ Datos incompletos", "error")
        return redirect(url_for('ventas'))
    if metodo_pago not in ['efectivo', 'transferencia', 'tarjeta']:
        flash("❌ Método de pago inválido", "error")
        return redirect(url_for('ventas'))
    if metodo_pago == 'tarjeta' and cuotas not in [2, 3, 6]:
        flash("❌ Cuotas inválidas", "error")
        return redirect(url_for('seleccionar_pago'))
    if metodo_pago != 'tarjeta':
        cuotas = None

    conn = sqlite3.connect('negocio.db')
    try:
        # Verificar stock
        for item in carrito:
            stock_actual = conn.execute("SELECT stock FROM productos WHERE id = ?", (item['id'],)).fetchone()
            if not stock_actual or stock_actual[0] < item['cantidad']:
                flash(f"❌ Stock insuficiente para {item['descripcion']}", "error")
                conn.rollback()
                return redirect(url_for('ventas'))
        # Registrar venta
        fecha = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        total_venta = sum(item['precio'] * item['cantidad'] for item in carrito)
        conn.execute("INSERT INTO ventas (fecha, cliente_id, total, metodo_pago, cuotas) VALUES (?, ?, ?, ?, ?)",
                     (fecha, cliente_id, total_venta, metodo_pago, cuotas))
        venta_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        # Registrar detalles y actualizar stock
        for item in carrito:
            conn.execute("INSERT INTO detalle_venta (venta_id, producto_id, cantidad, precio_unitario) VALUES (?, ?, ?, ?)",
                         (venta_id, item['id'], item['cantidad'], item['precio']))
            conn.execute("UPDATE productos SET stock = stock - ? WHERE id = ?", (item['cantidad'], item['id']))
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

# === HISTORIAL DE VENTAS ===
@app.route('/ventas_historial')
@login_required
def ventas_historial():
    page = request.args.get('page', 1, type=int)
    search_id = request.args.get('id', '').strip()
    per_page = 20
    conn = sqlite3.connect('negocio.db')
    if search_id:
        try:
            venta_id = int(search_id)
            ventas = conn.execute("""
                SELECT v.id, v.fecha, c.nombre, v.total
                FROM ventas v
                JOIN clientes c ON v.cliente_id = c.id
                WHERE v.id = ?
                ORDER BY v.fecha DESC
            """, (venta_id,)).fetchall()
            total = len(ventas)
            total_pages = 1
            page = 1
        except ValueError:
            flash("❌ El ID debe ser un número", "error")
            ventas, total, total_pages = [], 0, 0
    else:
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
    productos = conn.execute("""
        SELECT p.descripcion, dv.cantidad, dv.precio_unitario
        FROM detalle_venta dv
        JOIN productos p ON dv.producto_id = p.id
        WHERE dv.venta_id = ?
    """, (venta_id,)).fetchall()
    conn.close()
    return render_template('detalle_venta.html', venta=venta, productos=productos)

# === REPORTES ===
@app.route('/reporte/excel')
@login_required
def reporte_excel():
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
    hoy = datetime.now().strftime('%d-%m-%Y')
    output_path = f'reporte_ventas_{hoy}.xlsx'
    df.to_excel(output_path, index=False)
    conn.close()
    return send_file(output_path, as_attachment=True)

# === INICIAR APLICACIÓN ===
if __name__ == '__main__':
    init_db()
    print("Sistema iniciado. Abre http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)