# models.py
import sqlite3
import os
from datetime import datetime
from werkzeug.security import generate_password_hash
from services.tiendanube_service import actualizar_stock_tn_service

# Path absoluto a la DB, resuelto desde la ubicación de este archivo
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'negocio.db')

def get_conn():
    """Abre una conexión con row_factory para acceder a columnas por nombre."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS productos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sku TEXT UNIQUE NOT NULL,
        descripcion TEXT NOT NULL,
        precio REAL NOT NULL,
        stock INTEGER DEFAULT 0,
        variant_id TEXT UNIQUE,
        product_id TEXT,
        promotional_price REAL,
        barcode TEXT,
        imagen_url TEXT,
        activo INTEGER DEFAULT 1
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS clientes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        cuit TEXT,
        telefono TEXT,
        dni TEXT,
        email TEXT,
        tipo INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS ventas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha TEXT NOT NULL,
        cliente_id INTEGER NOT NULL,
        total REAL NOT NULL,
        metodo_pago TEXT,
        cuotas INTEGER,
        order_id TEXT
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

    # Migraciones seguras: agregar columnas nuevas si no existen
    columnas_productos = [r[1] for r in c.execute("PRAGMA table_info(productos)").fetchall()]
    for col, definition in [
        ("promotional_price", "REAL"),
        ("barcode", "TEXT"),
        ("imagen_url", "TEXT"),
    ]:
        if col not in columnas_productos:
            c.execute(f"ALTER TABLE productos ADD COLUMN {col} {definition}")

    columnas_ventas = [r[1] for r in c.execute("PRAGMA table_info(ventas)").fetchall()]
    if "order_id" not in columnas_ventas:
        c.execute("ALTER TABLE ventas ADD COLUMN order_id TEXT")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_ventas_order_id ON ventas(order_id)")
    columnas_clientes = [r[1] for r in c.execute("PRAGMA table_info(clientes)").fetchall()]
    for col, definition in [
        ("dni",   "TEXT"),
        ("email", "TEXT"),
        ("tipo",  "INTEGER DEFAULT 0"),
    ]:
        if col not in columnas_clientes:
            c.execute(f"ALTER TABLE clientes ADD COLUMN {col} {definition}")
    # Cliente por defecto
    c.execute("SELECT COUNT(*) FROM clientes")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO clientes (nombre, telefono, cuit) VALUES ('Consumidor Final', '', '')")

    conn.commit()
    conn.close()


# === Productos ===

def get_productos(search=None, stock_filter=None, orden=None, page=1, per_page=20):
    conn = get_conn()
    condiciones = []
    params = []

    if search:
        condiciones.append("(sku LIKE ? OR descripcion LIKE ?)")
        params.extend([f'%{search}%', f'%{search}%'])
    if stock_filter == 'sin_stock':
        condiciones.append("stock = 0")

    where_clause = "WHERE " + " AND ".join(condiciones) if condiciones else ""

    order_clause = "ORDER BY id DESC"
    if orden == 'mayor':   order_clause = "ORDER BY precio DESC"
    elif orden == 'menor': order_clause = "ORDER BY precio ASC"
    elif orden == 'nuevo': order_clause = "ORDER BY id DESC"
    elif orden == 'viejo': order_clause = "ORDER BY id ASC"

    total = conn.execute(f"SELECT COUNT(*) FROM productos {where_clause}", params).fetchone()[0]
    offset = (page - 1) * per_page
    productos = conn.execute(
        f"SELECT * FROM productos {where_clause} {order_clause} LIMIT ? OFFSET ?",
        (*params, per_page, offset)
    ).fetchall()
    conn.close()
    return productos, total

def add_producto(sku, descripcion, precio, stock):
    conn = get_conn()
    conn.execute(
        "INSERT INTO productos (sku, descripcion, precio, stock) VALUES (?, ?, ?, ?)",
        (sku, descripcion, precio, stock)
    )
    conn.commit()
    conn.close()

def update_producto(producto_id, sku, descripcion, precio, stock):
    conn = get_conn()
    conn.execute(
        "UPDATE productos SET sku = ?, descripcion = ?, precio = ?, stock = ? WHERE id = ?",
        (sku, descripcion, precio, stock, producto_id)
    )
    conn.commit()

    # Sincronizar con TiendaNube si el producto está vinculado
    row = conn.execute(
        "SELECT variant_id, product_id FROM productos WHERE id = ?", (producto_id,)
    ).fetchone()
    conn.close()

    if row and row["variant_id"]:
        from services.tiendanube_service import actualizar_stock_tn_service, actualizar_precio_tn_service
        actualizar_stock_tn_service(row["variant_id"], stock)
        actualizar_precio_tn_service(row["variant_id"], row["product_id"], precio)

def delete_producto(producto_id):
    conn = get_conn()
    tiene_ventas = conn.execute(
        "SELECT COUNT(*) FROM detalle_venta WHERE producto_id = ?", (producto_id,)
    ).fetchone()[0]
    if tiene_ventas > 0:
        conn.close()
        return False
    conn.execute("DELETE FROM productos WHERE id = ?", (producto_id,))
    conn.commit()
    conn.close()
    return True

def get_producto_by_id(producto_id):
    conn = get_conn()
    p = conn.execute("SELECT * FROM productos WHERE id = ?", (producto_id,)).fetchone()
    conn.close()
    return p


# === Clientes ===

def get_clientes(page=1, per_page=20):
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) FROM clientes").fetchone()[0]
    offset = (page - 1) * per_page
    clientes = conn.execute("SELECT * FROM clientes LIMIT ? OFFSET ?", (per_page, offset)).fetchall()
    conn.close()
    return clientes, total

def add_cliente(nombre, cuit=None, telefono=None, dni=None, email=None, tipo=0):
    conn = get_conn()
    if cuit:
        existente = conn.execute("SELECT id FROM clientes WHERE cuit = ?", (cuit,)).fetchone()
        if existente:
            conn.close()
            return False, "CUIT ya registrado"
    conn.execute(
        "INSERT INTO clientes (nombre, cuit, telefono, dni, email, tipo) VALUES (?, ?, ?, ?, ?, ?)",
        (nombre, cuit, telefono, dni, email, tipo)
    )
    conn.commit()
    conn.close()
    return True, ""

def get_cliente_by_id(cliente_id):
    conn = get_conn()
    c = conn.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
    conn.close()
    return c


# === Ventas ===

def registrar_venta(cliente_id, carrito, metodo_pago, cuotas=None):
    conn = get_conn()
    try:
        # Verificar stock
        for item in carrito:
            row = conn.execute(
                "SELECT stock FROM productos WHERE id = ?", (item['id'],)
            ).fetchone()
            if not row or (row['stock'] is not None and row['stock'] < item['cantidad']):
                return False, f"Stock insuficiente para {item['descripcion']}"

        # Registrar venta
        fecha = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        total_venta = sum(item['precio'] * item['cantidad'] for item in carrito)

        conn.execute(
            "INSERT INTO ventas (fecha, cliente_id, total, metodo_pago, cuotas) VALUES (?, ?, ?, ?, ?)",
            (fecha, cliente_id, total_venta, metodo_pago, cuotas)
        )
        venta_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Registrar detalle y descontar stock
        for item in carrito:
            conn.execute(
                "INSERT INTO detalle_venta (venta_id, producto_id, cantidad, precio_unitario) VALUES (?, ?, ?, ?)",
                (venta_id, item['id'], item['cantidad'], item['precio'])
            )
            conn.execute(
                "UPDATE productos SET stock = stock - ? WHERE id = ?",
                (item['cantidad'], item['id'])
            )

        conn.commit()

        # Sincronizar stock con Tiendanube (solo productos vinculados)
        for item in carrito:
            variant_row = conn.execute(
                "SELECT variant_id, stock FROM productos WHERE id = ?", (item['id'],)
            ).fetchone()
            if variant_row and variant_row['variant_id']:
                actualizar_stock_tn_service(variant_row['variant_id'], variant_row['stock'])

        return True, venta_id

    except Exception as e:
        conn.rollback()
        return False, str(e)

    finally:
        conn.close()


def get_ventas_historial(page=1, per_page=20, search_id=None):
    conn = get_conn()
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
    conn = get_conn()
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
    conn = get_conn()
    total_productos = conn.execute("SELECT COUNT(*) FROM productos").fetchone()[0]
    total_clientes  = conn.execute("SELECT COUNT(*) FROM clientes").fetchone()[0]
    hoy = datetime.now().strftime('%Y-%m-%d')
    ventas_hoy = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(total), 0) FROM ventas WHERE fecha LIKE ?", (hoy + '%',)
    ).fetchone()
    mes_actual = datetime.now().strftime('%Y-%m')
    ventas_mes = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(total), 0) FROM ventas WHERE strftime('%Y-%m', fecha) = ?", (mes_actual,)
    ).fetchone()
    ultimas_ventas = conn.execute("""
        SELECT v.id, v.fecha, c.nombre, v.total
        FROM ventas v
        JOIN clientes c ON v.cliente_id = c.id
        ORDER BY v.fecha DESC LIMIT 5
    """).fetchall()
    conn.close()
    return {
        'total_productos':     total_productos,
        'total_clientes':      total_clientes,
        'cantidad_ventas_hoy': ventas_hoy[0],
        'total_ventas_hoy':    ventas_hoy[1],
        'cantidad_ventas_mes': ventas_mes[0],
        'total_ventas_mes':    ventas_mes[1],
        'ultimas_ventas':      ultimas_ventas,
    }
