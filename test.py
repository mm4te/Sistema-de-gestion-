import sqlite3

# 1. Conectar a la base de datos
conn = sqlite3.connect('negocio.db')
cursor = conn.cursor()

try:
    # 2. Ejecutar la sentencia ALTER TABLE
    cursor.execute("ALTER TABLE productos ADD COLUMN variant_id TEXT;")
    conn.commit()
    print("Columna 'variant_id' añadida exitosamente.")
except sqlite3.OperationalError as e:
    # Maneja error si la columna ya existe
    print(f"Error: {e}")
finally:
    # 3. Cerrar la conexión
    conn.close()