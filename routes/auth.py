# routes/auth.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from models import get_conn
from werkzeug.security import check_password_hash

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_conn()
        user = conn.execute("""
            SELECT u.id, u.username, u.password_hash, u.rol_id,
                   COALESCE(r.nivel,  1)            AS rol_nivel,
                   COALESCE(r.nombre, 'SuperAdmin') AS rol_nombre
            FROM usuarios u
            LEFT JOIN roles r ON u.rol_id = r.id
            WHERE u.username = ?
        """, (username,)).fetchone()
        conn.close()

        if user and check_password_hash(user['password_hash'], password):
            session['user_id']   = user['id']
            session['username']  = user['username']
            session['rol_id']    = user['rol_id']
            session['rol_nivel'] = user['rol_nivel']
            session['rol_nombre']= user['rol_nombre']

            # SuperAdmin: no necesita lista de permisos (se chequea por nivel)
            if user['rol_nivel'] == 1:
                session['permisos'] = []
            else:
                from services.usuarios_service import cargar_permisos
                perms = cargar_permisos(user['rol_id'])
                session['permisos'] = [list(p) for p in perms]

            # Registro de auditoría
            try:
                from services.usuarios_service import registrar_auditoria
                registrar_auditoria(user['id'], user['username'], 'login', 'auth',
                                    ip=request.remote_addr)
            except Exception:
                pass

            flash("✅ Sesión iniciada", "success")
            return redirect(url_for('main.index'))
        else:
            flash("❌ Usuario o contraseña incorrectos", "error")

    return render_template('login.html')


@auth_bp.route('/logout')
def logout():
    if 'user_id' in session:
        try:
            from services.usuarios_service import registrar_auditoria
            registrar_auditoria(session['user_id'], session.get('username', ''),
                                'logout', 'auth', ip=request.remote_addr)
        except Exception:
            pass
    session.clear()
    flash("👋 Sesión cerrada", "success")
    return redirect(url_for('auth.login'))
