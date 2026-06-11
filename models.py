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
    if "estado" not in columnas_ventas:
        c.execute("ALTER TABLE ventas ADD COLUMN estado TEXT NOT NULL DEFAULT 'activa'")
    if "motivo_cancelacion" not in columnas_ventas:
        c.execute("ALTER TABLE ventas ADD COLUMN motivo_cancelacion TEXT")
    if "monto_recibido" not in columnas_ventas:
        c.execute("ALTER TABLE ventas ADD COLUMN monto_recibido REAL")
    if "vuelto" not in columnas_ventas:
        c.execute("ALTER TABLE ventas ADD COLUMN vuelto REAL")
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

    # ── Presupuestos ────────────────────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS presupuestos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        numero TEXT UNIQUE NOT NULL,
        cliente_id INTEGER NOT NULL,
        fecha TEXT NOT NULL,
        fecha_validez TEXT NOT NULL,
        estado TEXT NOT NULL DEFAULT 'borrador',
        total REAL NOT NULL DEFAULT 0,
        observaciones TEXT,
        creado_por INTEGER,
        FOREIGN KEY (cliente_id) REFERENCES clientes(id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS presupuesto_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        presupuesto_id INTEGER NOT NULL,
        producto_id INTEGER,
        descripcion TEXT NOT NULL,
        cantidad REAL NOT NULL DEFAULT 1,
        precio_unitario REAL NOT NULL DEFAULT 0,
        subtotal REAL NOT NULL DEFAULT 0,
        FOREIGN KEY (presupuesto_id) REFERENCES presupuestos(id),
        FOREIGN KEY (producto_id) REFERENCES productos(id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS presupuesto_historial (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        presupuesto_id INTEGER NOT NULL,
        estado_anterior TEXT,
        estado_nuevo TEXT NOT NULL,
        fecha TEXT NOT NULL,
        usuario_id INTEGER,
        nota TEXT,
        FOREIGN KEY (presupuesto_id) REFERENCES presupuestos(id)
    )''')

    columnas_presupuestos = [r[1] for r in c.execute("PRAGMA table_info(presupuestos)").fetchall()]
    if 'venta_id' not in columnas_presupuestos:
        c.execute("ALTER TABLE presupuestos ADD COLUMN venta_id INTEGER REFERENCES ventas(id)")

    # ── Remitos ──────────────────────────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS remitos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        numero TEXT UNIQUE NOT NULL,
        cliente_id INTEGER,
        presupuesto_id INTEGER,
        venta_id INTEGER,
        destinatario TEXT NOT NULL,
        direccion TEXT NOT NULL,
        bultos INTEGER DEFAULT 1,
        peso REAL,
        estado TEXT NOT NULL DEFAULT 'pendiente',
        fecha TEXT NOT NULL,
        fecha_entrega_estimada TEXT,
        fecha_entrega_real TEXT,
        recibido_por TEXT,
        observaciones TEXT,
        stock_descontado INTEGER DEFAULT 0,
        creado_por INTEGER,
        FOREIGN KEY (cliente_id) REFERENCES clientes(id),
        FOREIGN KEY (presupuesto_id) REFERENCES presupuestos(id),
        FOREIGN KEY (venta_id) REFERENCES ventas(id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS remito_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        remito_id INTEGER NOT NULL,
        producto_id INTEGER,
        descripcion TEXT NOT NULL,
        cantidad REAL NOT NULL DEFAULT 1,
        FOREIGN KEY (remito_id) REFERENCES remitos(id),
        FOREIGN KEY (producto_id) REFERENCES productos(id)
    )''')

    # ── Caja ─────────────────────────────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS movimientos_caja (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo          TEXT NOT NULL,
        origen        TEXT NOT NULL,
        referencia_id INTEGER,
        descripcion   TEXT NOT NULL,
        monto         REAL NOT NULL,
        metodo_pago   TEXT,
        fecha         TEXT NOT NULL,
        creado_por    INTEGER REFERENCES usuarios(id)
    )''')
    c.execute("CREATE INDEX IF NOT EXISTS idx_caja_fecha  ON movimientos_caja(fecha)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_caja_tipo   ON movimientos_caja(tipo)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_caja_origen ON movimientos_caja(origen)")

    # ── Gastos ───────────────────────────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS categorias_gasto (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre      TEXT UNIQUE NOT NULL,
        descripcion TEXT,
        activo      INTEGER DEFAULT 1
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS gastos (
        id                      INTEGER PRIMARY KEY AUTOINCREMENT,
        categoria_id            INTEGER NOT NULL,
        descripcion             TEXT NOT NULL,
        monto                   REAL NOT NULL,
        fecha                   TEXT NOT NULL,
        metodo_pago             TEXT,
        es_recurrente           INTEGER DEFAULT 0,
        frecuencia              TEXT,
        gasto_padre_id          INTEGER,
        fecha_prox_recurrencia  TEXT,
        archivo_nombre          TEXT,
        archivo_ruta            TEXT,
        observaciones           TEXT,
        creado_por              INTEGER,
        FOREIGN KEY (categoria_id)   REFERENCES categorias_gasto(id),
        FOREIGN KEY (gasto_padre_id) REFERENCES gastos(id),
        FOREIGN KEY (creado_por)     REFERENCES usuarios(id)
    )''')

    # ── Roles y permisos ──────────────────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS roles (
        id          INTEGER PRIMARY KEY,
        nombre      TEXT UNIQUE NOT NULL,
        nivel       INTEGER NOT NULL,
        descripcion TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS rol_permisos (
        rol_id  INTEGER NOT NULL,
        modulo  TEXT NOT NULL,
        accion  TEXT NOT NULL,
        PRIMARY KEY (rol_id, modulo, accion),
        FOREIGN KEY (rol_id) REFERENCES roles(id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS audit_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER,
        username   TEXT,
        accion     TEXT NOT NULL,
        modulo     TEXT NOT NULL,
        detalle    TEXT,
        ip         TEXT,
        fecha      TEXT NOT NULL,
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
    )''')

    # Índices para acelerar búsquedas frecuentes
    c.execute("CREATE INDEX IF NOT EXISTS idx_productos_sku ON productos(sku)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_ventas_fecha ON ventas(fecha)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_detalle_venta_venta_id ON detalle_venta(venta_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_detalle_venta_producto_id ON detalle_venta(producto_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_clientes_email ON clientes(email)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_clientes_dni ON clientes(dni)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_presupuestos_cliente ON presupuestos(cliente_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_presupuestos_estado ON presupuestos(estado)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_presupuesto_items ON presupuesto_items(presupuesto_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_remitos_cliente ON remitos(cliente_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_remitos_estado ON remitos(estado)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_remito_items ON remito_items(remito_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_usuario ON audit_log(usuario_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_fecha   ON audit_log(fecha)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_modulo  ON audit_log(modulo)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_gastos_fecha      ON gastos(fecha)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_gastos_categoria  ON gastos(categoria_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_gastos_recurrente ON gastos(es_recurrente)")

    # ── Migrar usuarios: agregar rol_id ──────────────────────────────────────
    columnas_usuarios = [r[1] for r in c.execute("PRAGMA table_info(usuarios)").fetchall()]
    if 'rol_id' not in columnas_usuarios:
        c.execute("ALTER TABLE usuarios ADD COLUMN rol_id INTEGER REFERENCES roles(id)")

    # ── Seed: roles ──────────────────────────────────────────────────────────
    _ROLES = [
        (1, 'SuperAdmin', 1, 'Acceso total al sistema'),
        (2, 'Admin',      2, 'Gestión completa del negocio'),
        (3, 'Supervisor', 3, 'Supervisión de operaciones'),
        (4, 'Vendedor',   4, 'Ventas y presupuestos'),
        (5, 'Deposito',   5, 'Inventario y logística'),
    ]
    for row in _ROLES:
        c.execute("INSERT OR IGNORE INTO roles (id, nombre, nivel, descripcion) VALUES (?,?,?,?)", row)

    # ── Seed: permisos por rol (SuperAdmin no necesita filas; se chequea por nivel) ──
    _PERMISOS = [
        # Admin (2) — todo excepto que no puede eliminar usuarios
        (2,'inventario','ver'),   (2,'inventario','crear'), (2,'inventario','editar'),
        (2,'inventario','eliminar'), (2,'inventario','importar'),
        (2,'ventas','ver'),       (2,'ventas','crear'),     (2,'ventas','cancelar'),
        (2,'clientes','ver'),     (2,'clientes','crear'),   (2,'clientes','editar'), (2,'clientes','eliminar'),
        (2,'presupuestos','ver'), (2,'presupuestos','crear'),(2,'presupuestos','editar'),
        (2,'presupuestos','eliminar'), (2,'presupuestos','cambiar_estado'),
        (2,'remitos','ver'),      (2,'remitos','crear'),    (2,'remitos','editar'),
        (2,'remitos','eliminar'), (2,'remitos','cambiar_estado'),
        (2,'reportes','ver'),
        (2,'tiendanube','ver'),   (2,'tiendanube','sincronizar'),
        (2,'usuarios','ver'),     (2,'usuarios','crear'),   (2,'usuarios','editar'),
        (2,'audit_log','ver'),
        (2,'gastos','ver'),       (2,'gastos','crear'),     (2,'gastos','editar'), (2,'gastos','eliminar'),
        (2,'caja','ver'),         (2,'caja','crear'),
        (2,'resumen','ver'),
        # Supervisor (3)
        (3,'inventario','ver'),
        (3,'ventas','ver'),       (3,'ventas','crear'),     (3,'ventas','cancelar'),
        (3,'clientes','ver'),     (3,'clientes','crear'),   (3,'clientes','editar'),
        (3,'presupuestos','ver'), (3,'presupuestos','crear'),(3,'presupuestos','editar'),
        (3,'presupuestos','cambiar_estado'),
        (3,'remitos','ver'),      (3,'remitos','crear'),    (3,'remitos','editar'),
        (3,'remitos','cambiar_estado'),
        (3,'reportes','ver'),
        (3,'gastos','ver'),
        (3,'caja','ver'),         (3,'caja','crear'),
        (3,'resumen','ver'),
        # Vendedor (4)
        (4,'inventario','ver'),
        (4,'ventas','ver'),       (4,'ventas','crear'),
        (4,'clientes','ver'),     (4,'clientes','crear'),
        (4,'presupuestos','ver'), (4,'presupuestos','crear'),(4,'presupuestos','editar'),
        (4,'presupuestos','cambiar_estado'),
        (4,'remitos','ver'),
        (4,'reportes','ver'),
        # Depósito (5)
        (5,'inventario','ver'),   (5,'inventario','crear'), (5,'inventario','editar'),
        (5,'inventario','importar'),
        (5,'remitos','ver'),      (5,'remitos','editar'),   (5,'remitos','cambiar_estado'),
        (5,'clientes','ver'),
        (5,'reportes','ver'),
    ]
    for row in _PERMISOS:
        c.execute("INSERT OR IGNORE INTO rol_permisos (rol_id, modulo, accion) VALUES (?,?,?)", row)

    # Usuarios existentes sin rol → SuperAdmin
    c.execute("UPDATE usuarios SET rol_id = 1 WHERE rol_id IS NULL")

    # ── Seed: categorías de gasto ─────────────────────────────────────────────
    _CATEGORIAS = [
        ('Alquiler',     'Alquiler del local u oficina'),
        ('Servicios',    'Luz, gas, agua, internet, teléfono'),
        ('Sueldos',      'Sueldos y cargas sociales del personal'),
        ('Materiales',   'Insumos y materiales de trabajo'),
        ('Transporte',   'Fletes, combustible y movilidad'),
        ('Marketing',    'Publicidad y promociones'),
        ('Impuestos',    'Impuestos, tasas y tributos'),
        ('Mantenimiento','Reparaciones y mantenimiento'),
        ('Bancarios',    'Comisiones y gastos bancarios'),
        ('Otros',        'Gastos varios no categorizados'),
    ]
    for nombre, desc in _CATEGORIAS:
        c.execute("INSERT OR IGNORE INTO categorias_gasto (nombre, descripcion) VALUES (?,?)", (nombre, desc))

    conn.commit()
    conn.close()


# === Productos ===

def get_productos(search=None, stock_filter=None, orden=None, page=1, per_page=20):
    conn = get_conn()
    condiciones = ["activo = 1"]
    params = []

    if search:
        condiciones.append("(sku LIKE ? OR descripcion LIKE ?)")
        params.extend([f'%{search}%', f'%{search}%'])
    if stock_filter == 'sin_stock':
        condiciones.append("stock = 0")

    where_clause = "WHERE " + " AND ".join(condiciones)

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

def registrar_venta(cliente_id, carrito, metodo_pago, cuotas=None,
                    monto_recibido=None, vuelto=None, creado_por=None):
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
            "INSERT INTO ventas (fecha, cliente_id, total, metodo_pago, cuotas, monto_recibido, vuelto)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (fecha, cliente_id, total_venta, metodo_pago, cuotas, monto_recibido, vuelto)
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

        # Registrar ingreso en caja (misma transacción)
        from services.caja_service import registrar_movimiento_en_conn
        registrar_movimiento_en_conn(
            conn, 'ingreso', 'venta', venta_id,
            f"Venta #{venta_id}",
            total_venta, metodo_pago, creado_por, fecha
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
        "SELECT COUNT(*), COALESCE(SUM(total), 0) FROM ventas"
        " WHERE fecha LIKE ? AND (estado IS NULL OR estado != 'cancelada')", (hoy + '%',)
    ).fetchone()
    mes_actual = datetime.now().strftime('%Y-%m')
    ventas_mes = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(total), 0) FROM ventas"
        " WHERE strftime('%Y-%m', fecha) = ? AND (estado IS NULL OR estado != 'cancelada')",
        (mes_actual,)
    ).fetchone()
    ultimas_ventas = conn.execute("""
        SELECT v.id, v.fecha, c.nombre, v.total
        FROM ventas v
        JOIN clientes c ON v.cliente_id = c.id
        WHERE v.estado IS NULL OR v.estado != 'cancelada'
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
