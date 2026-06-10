# services/usuarios_service.py
import logging
from datetime import datetime

from werkzeug.security import generate_password_hash

from models import get_conn

logger = logging.getLogger(__name__)


# ── Roles ─────────────────────────────────────────────────────────────────────

def listar_roles():
    conn = get_conn()
    roles = conn.execute("SELECT * FROM roles ORDER BY nivel").fetchall()
    conn.close()
    return roles


# ── Permisos ──────────────────────────────────────────────────────────────────

def cargar_permisos(rol_id):
    """Devuelve un set de tuplas (modulo, accion) para el rol dado."""
    conn = get_conn()
    filas = conn.execute(
        "SELECT modulo, accion FROM rol_permisos WHERE rol_id = ?", (rol_id,)
    ).fetchall()
    conn.close()
    return {(r['modulo'], r['accion']) for r in filas}


# ── CRUD usuarios ─────────────────────────────────────────────────────────────

def listar_usuarios():
    conn = get_conn()
    usuarios = conn.execute("""
        SELECT u.id, u.username, u.rol_id,
               COALESCE(r.nombre, 'SuperAdmin') AS rol_nombre,
               COALESCE(r.nivel, 1) AS rol_nivel
        FROM usuarios u
        LEFT JOIN roles r ON u.rol_id = r.id
        ORDER BY r.nivel, u.username
    """).fetchall()
    conn.close()
    return usuarios


def get_usuario(user_id):
    conn = get_conn()
    u = conn.execute("""
        SELECT u.id, u.username, u.rol_id,
               COALESCE(r.nombre, 'SuperAdmin') AS rol_nombre,
               COALESCE(r.nivel, 1) AS rol_nivel
        FROM usuarios u
        LEFT JOIN roles r ON u.rol_id = r.id
        WHERE u.id = ?
    """, (user_id,)).fetchone()
    conn.close()
    return u


def crear_usuario(username, password, rol_id):
    if not username or not password:
        return False, "Usuario y contraseña son obligatorios"
    conn = get_conn()
    try:
        existente = conn.execute(
            "SELECT id FROM usuarios WHERE username = ?", (username,)
        ).fetchone()
        if existente:
            return False, f"El usuario '{username}' ya existe"
        conn.execute(
            "INSERT INTO usuarios (username, password_hash, rol_id) VALUES (?, ?, ?)",
            (username, generate_password_hash(password), rol_id)
        )
        conn.commit()
        new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        return True, new_id
    except Exception as e:
        conn.rollback()
        logger.error("crear_usuario error: %s", e)
        return False, str(e)
    finally:
        conn.close()


def actualizar_usuario(user_id, username, rol_id, nueva_password=None):
    if not username:
        return False, "El nombre de usuario es obligatorio"
    conn = get_conn()
    try:
        dup = conn.execute(
            "SELECT id FROM usuarios WHERE username = ? AND id != ?", (username, user_id)
        ).fetchone()
        if dup:
            return False, f"El nombre '{username}' ya lo usa otro usuario"

        if nueva_password:
            conn.execute(
                "UPDATE usuarios SET username = ?, rol_id = ?, password_hash = ? WHERE id = ?",
                (username, rol_id, generate_password_hash(nueva_password), user_id)
            )
        else:
            conn.execute(
                "UPDATE usuarios SET username = ?, rol_id = ? WHERE id = ?",
                (username, rol_id, user_id)
            )
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        logger.error("actualizar_usuario error: %s", e)
        return False, str(e)
    finally:
        conn.close()


def eliminar_usuario(user_id, solicitante_id):
    if user_id == solicitante_id:
        return False, "No podés eliminar tu propia cuenta"
    conn = get_conn()
    try:
        # Verificar que no sea el único SuperAdmin
        target = conn.execute(
            "SELECT u.rol_id, r.nivel FROM usuarios u LEFT JOIN roles r ON u.rol_id=r.id WHERE u.id=?",
            (user_id,)
        ).fetchone()
        if target and (target['nivel'] == 1 or target['nivel'] is None):
            count_sa = conn.execute(
                "SELECT COUNT(*) FROM usuarios u LEFT JOIN roles r ON u.rol_id=r.id WHERE r.nivel=1 OR r.nivel IS NULL"
            ).fetchone()[0]
            if count_sa <= 1:
                return False, "No se puede eliminar el único SuperAdmin"

        conn.execute("DELETE FROM usuarios WHERE id = ?", (user_id,))
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        logger.error("eliminar_usuario error: %s", e)
        return False, str(e)
    finally:
        conn.close()


# ── Audit log ─────────────────────────────────────────────────────────────────

def registrar_auditoria(usuario_id, username, accion, modulo, detalle='', ip=''):
    try:
        conn = get_conn()
        conn.execute(
            "INSERT INTO audit_log (usuario_id, username, accion, modulo, detalle, ip, fecha) VALUES (?,?,?,?,?,?,?)",
            (usuario_id, username, accion, modulo, detalle or '', ip or '',
             datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error("registrar_auditoria error: %s", e)


def listar_audit_log(page=1, per_page=50, modulo=None, usuario_id=None):
    conn = get_conn()
    condiciones = []
    params = []
    if modulo:
        condiciones.append("modulo = ?")
        params.append(modulo)
    if usuario_id:
        condiciones.append("usuario_id = ?")
        params.append(usuario_id)

    where = ("WHERE " + " AND ".join(condiciones)) if condiciones else ""
    total = conn.execute(f"SELECT COUNT(*) FROM audit_log {where}", params).fetchone()[0]
    offset = (page - 1) * per_page
    filas = conn.execute(
        f"SELECT * FROM audit_log {where} ORDER BY fecha DESC LIMIT ? OFFSET ?",
        (*params, per_page, offset)
    ).fetchall()
    conn.close()
    return filas, total
