# crear_usuario.py
import sqlite3
from werkzeug.security import generate_password_hash

def crear_usuario(username, password):
    conn = sqlite3.connect('negocio.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL)''')
    
    hashed = generate_password_hash(password)
    try:
        c.execute("INSERT INTO usuarios (username, password_hash) VALUES (?, ?)", (username, hashed))
        print(f" Usuario '{username}' creado con éxito.")
    except sqlite3.IntegrityError:
        print(f" El usuario '{username}' ya existe.")
    conn.commit()
    conn.close()

if __name__ == '__main__':
    # Cambia estos valores por los tuyos
    crear_usuario("admin", "tu_contraseña_segura")