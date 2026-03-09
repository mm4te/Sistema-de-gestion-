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
        promotional_price TEXT,

        stock INTEGER,

        barcode TEXT,

        variant_id TEXT UNIQUE,
        product_id TEXT,

        activo INTEGER NOT NULL DEFAULT 1,
        fecha_creacion DATETIME DEFAULT CURRENT_TIMESTAMP,
        
        imagen_url TEXT
    );
""")

conn.commit()
conn.close()

print("Tabla productos recreada correctamente")
