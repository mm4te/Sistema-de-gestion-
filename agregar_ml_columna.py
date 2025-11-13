# agregar_ml_columna.py
import sqlite3

conn = sqlite3.connect('negocio.db')
conn.execute("ALTER TABLE productos ADD COLUMN ml_item_id TEXT;")
conn.commit()
print(" Columna 'ml_item_id' agregada exitosamente.")
conn.close()