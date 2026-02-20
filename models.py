# models.py
import sqlite3
import os
from datetime import datetime
from werkzeug.security import generate_password_hash

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
    c.execute("SELECT COUNT(*) FROM clientes")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO clientes (nombre, telefono, cuit) VALUES ('Consumidor Final', '', '')")
    conn.commit()
    conn.close()

# === Productos ===
def get_productos(search=None, stock_filter=None, orden=None, page=1, per_page=20):
    conn = sqlite3.connect('negocio.db')
    condiciones = []
    params = []
    
    if search:
        condiciones.append("(codigo LIKE ? OR descripcion LIKE ?)")
        params.extend([f'%{search}%', f'%{search}%'])
    if stock_filter == 'sin_stock':
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
    return productos, total

def add_producto(codigo, descripcion, precio, stock):
    conn = sqlite3.connect('negocio.db')
    conn.execute("INSERT INTO productos (codigo, descripcion, precio, stock) VALUES (?, ?, ?, ?)",
                 (codigo, descripcion, precio, stock))
    conn.commit()
    conn.close()

def update_producto(producto_id, codigo, descripcion, precio, stock):
    conn = sqlite3.connect('negocio.db')
    conn.execute("UPDATE productos SET codigo = ?, descripcion = ?, precio = ?, stock = ? WHERE id = ?",
                 (codigo, descripcion, precio, stock, producto_id))
    conn.commit()
    conn.close()

def delete_producto(producto_id):
    conn = sqlite3.connect('negocio.db')
    tiene_ventas = conn.execute("SELECT COUNT(*) FROM detalle_venta WHERE producto_id = ?", (producto_id,)).fetchone()[0]
    if tiene_ventas > 0:
        conn.close()
        return False
    conn.execute("DELETE FROM productos WHERE id = ?", (producto_id,))
    conn.commit()
    conn.close()
    return True

def get_producto_by_id(producto_id):
    conn = sqlite3.connect('negocio.db')
    p = conn.execute("SELECT * FROM productos WHERE id = ?", (producto_id,)).fetchone()
    conn.close()
    return p

# === Clientes ===
def get_clientes(page=1, per_page=20):
    conn = sqlite3.connect('negocio.db')
    total = conn.execute("SELECT COUNT(*) FROM clientes").fetchone()[0]
    offset = (page - 1) * per_page
    clientes = conn.execute("SELECT * FROM clientes LIMIT ? OFFSET ?", (per_page, offset)).fetchall()
    conn.close()
    return clientes, total

def add_cliente(nombre, cuit=None, telefono=None):
    conn = sqlite3.connect('negocio.db')
    if cuit:
        existente = conn.execute("SELECT id FROM clientes WHERE cuit = ?", (cuit,)).fetchone()
        if existente:
            conn.close()
            return False, "CUIT ya registrado"
    conn.execute("INSERT INTO clientes (nombre, cuit, telefono) VALUES (?, ?, ?)", (nombre, cuit, telefono))
    conn.commit()
    conn.close()
    return True, ""

def get_cliente_by_id(cliente_id):
    conn = sqlite3.connect('negocio.db')
    c = conn.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
    conn.close()
    return c

# === Ventas ===
def registrar_venta(cliente_id, carrito, metodo_pago, cuotas=None):
    conn = sqlite3.connect('negocio.db')
    try:
        # Verificar stock
        for item in carrito:
            stock_actual = conn.execute("SELECT stock FROM productos WHERE id = ?", (item['id'],)).fetchone()
            if not stock_actual or stock_actual[0] < item['cantidad']:
                return False, f"Stock insuficiente para {item['descripcion']}"
        
        # Registrar venta
        fecha = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        total_venta = sum(item['precio'] * item['cantidad'] for item in carrito)
        conn.execute("INSERT INTO ventas (fecha, cliente_id, total, metodo_pago, cuotas) VALUES (?, ?, ?, ?, ?)",
                     (fecha, cliente_id, total_venta, metodo_pago, cuotas))
        venta_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        
        # Detalles y actualizar stock
        for item in carrito:
            conn.execute("INSERT INTO detalle_venta (venta_id, producto_id, cantidad, precio_unitario) VALUES (?, ?, ?, ?)",
                         (venta_id, item['id'], item['cantidad'], item['precio']))
            conn.execute("UPDATE productos SET stock = stock - ? WHERE id = ?", (item['cantidad'], item['id']))
        conn.commit()
        return True, venta_id
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def get_ventas_historial(page=1, per_page=20, search_id=None):
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
        except ValueError:
            ventas, total = [], 0
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
    conn.close()
    return ventas, total

def get_detalle_venta(venta_id):
    conn = sqlite3.connect('negocio.db')
    venta = conn.execute("""
        SELECT v.id, v.fecha, c.nombre, v.total, v.metodo_pago, v.cuotas
        FROM ventas v
        JOIN clientes c ON v.cliente_id = c.id
        WHERE v.id = ?
    """, (venta_id,)).fetchone()
    productos = conn.execute("""
        SELECT p.descripcion, dv.cantidad, dv.precio_unitario
        FROM detalle_venta dv
        JOIN productos p ON dv.producto_id = p.id
        WHERE dv.venta_id = ?
    """, (venta_id,)).fetchall()
    conn.close()
    return venta, productos

# === Dashboard ===
def get_dashboard_data():
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
    return {
        'total_productos': total_productos,
        'total_clientes': total_clientes,
        'cantidad_ventas_hoy': ventas_hoy[0],
        'total_ventas_hoy': ventas_hoy[1],      # ← ahora es un float
        'cantidad_ventas_mes': ventas_mes[0],
        'total_ventas_mes': ventas_mes[1],      # ← ahora es un float
        'ultimas_ventas': ultimas_ventas
    }