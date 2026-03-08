import sqlite3


conn = sqlite3.connect("negocio.db")
cursor = conn.cursor()

cursor.execute("DROP TABLE IF EXISTS productos;")

cursor.execute("""
    CREATE TABLE productos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        sku TEXT NOT NULL UNIQUE,
        descripcion TEXT NOT NULL,
        precio REAL NOT NULL,
        stock INTEGER NOT NULL DEFAULT 0,

        variant_id TEXT UNIQUE,
        product_id TEXT,
        ml_item_id TEXT UNIQUE,

        activo INTEGER NOT NULL DEFAULT 1,
        fecha_creacion DATETIME DEFAULT CURRENT_TIMESTAMP
    );
""")

conn.commit()
conn.close()

print("Tabla productos recreada correctamente")