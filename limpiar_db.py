import sqlite3

conn = sqlite3.connect('negocio.db')
conn.execute("DELETE FROM productos")
conn.execute("DELETE FROM sqlite_sequence WHERE name='productos'")
conn.commit()
print("Productos eliminados. Base de datos lista para nueva carga.")
conn.close()