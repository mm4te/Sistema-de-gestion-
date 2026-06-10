# routes/usuarios.py
from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from routes import login_required, require_permiso, require_rol
from services.usuarios_service import (
    actualizar_usuario,
    crear_usuario,
    eliminar_usuario,
    get_usuario,
    listar_audit_log,
    listar_roles,
    listar_usuarios,
    registrar_auditoria,
)

usuarios_bp = Blueprint('usuarios', __name__)


# ── Lista de usuarios ────────────────────────────────────────────────────────

@usuarios_bp.route('/usuarios')
@login_required
@require_permiso('usuarios', 'ver')
def lista():
    usuarios = listar_usuarios()
    return render_template('usuarios/lista.html', usuarios=usuarios)


# ── Nuevo usuario ────────────────────────────────────────────────────────────

@usuarios_bp.route('/usuarios/nuevo', methods=['GET', 'POST'])
@login_required
@require_permiso('usuarios', 'crear')
def nuevo():
    roles = listar_roles()
    # Filtra roles según nivel del solicitante (no puede crear alguien de mayor nivel)
    roles = [r for r in roles if r['nivel'] >= g.rol_nivel]

    if request.method == 'POST':
        username  = request.form.get('username', '').strip()
        password  = request.form.get('password', '').strip()
        rol_id    = request.form.get('rol_id', type=int)

        # Verificar que el rol asignado no supere al del solicitante
        rol_elegido = next((r for r in roles if r['id'] == rol_id), None)
        if not rol_elegido:
            flash("❌ Rol inválido", "error")
        elif not password or len(password) < 6:
            flash("❌ La contraseña debe tener al menos 6 caracteres", "error")
        else:
            ok, result = crear_usuario(username, password, rol_id)
            if ok:
                registrar_auditoria(
                    session['user_id'], session.get('username'),
                    'crear_usuario', 'usuarios',
                    detalle=f"Nuevo usuario: {username} (rol: {rol_elegido['nombre']})",
                    ip=request.remote_addr
                )
                flash(f"✅ Usuario '{username}' creado correctamente", "success")
                return redirect(url_for('usuarios.lista'))
            flash(f"❌ {result}", "error")

    return render_template('usuarios/form.html', usuario=None, roles=roles, titulo="Nuevo Usuario")


# ── Editar usuario ───────────────────────────────────────────────────────────

@usuarios_bp.route('/usuarios/<int:user_id>/editar', methods=['GET', 'POST'])
@login_required
@require_permiso('usuarios', 'editar')
def editar(user_id):
    u     = get_usuario(user_id)
    if not u:
        flash("❌ Usuario no encontrado", "error")
        return redirect(url_for('usuarios.lista'))

    roles = listar_roles()
    # No puede asignar un rol de nivel superior al propio
    roles = [r for r in roles if r['nivel'] >= g.rol_nivel]

    # No puede editar usuarios de nivel mayor o igual al suyo (excepto SuperAdmin)
    if g.rol_nivel != 1 and u['rol_nivel'] <= g.rol_nivel and u['id'] != session['user_id']:
        flash("⛔ No podés editar un usuario con igual o mayor jerarquía", "error")
        return redirect(url_for('usuarios.lista'))

    if request.method == 'POST':
        username  = request.form.get('username', '').strip()
        rol_id    = request.form.get('rol_id', type=int)
        password  = request.form.get('password', '').strip() or None

        if password and len(password) < 6:
            flash("❌ La contraseña debe tener al menos 6 caracteres", "error")
        else:
            rol_elegido = next((r for r in roles if r['id'] == rol_id), None)
            if not rol_elegido:
                flash("❌ Rol inválido", "error")
            else:
                ok, err = actualizar_usuario(user_id, username, rol_id, password)
                if ok:
                    registrar_auditoria(
                        session['user_id'], session.get('username'),
                        'editar_usuario', 'usuarios',
                        detalle=f"Editó usuario ID {user_id} ({username})",
                        ip=request.remote_addr
                    )
                    flash("✅ Usuario actualizado", "success")
                    return redirect(url_for('usuarios.lista'))
                flash(f"❌ {err}", "error")

    return render_template('usuarios/form.html', usuario=u, roles=roles, titulo="Editar Usuario")


# ── Eliminar usuario ─────────────────────────────────────────────────────────

@usuarios_bp.route('/usuarios/<int:user_id>/eliminar', methods=['POST'])
@login_required
@require_rol(1)  # Solo SuperAdmin
def eliminar(user_id):
    u = get_usuario(user_id)
    ok, err = eliminar_usuario(user_id, session['user_id'])
    if ok:
        registrar_auditoria(
            session['user_id'], session.get('username'),
            'eliminar_usuario', 'usuarios',
            detalle=f"Eliminó usuario '{u['username'] if u else user_id}'",
            ip=request.remote_addr
        )
        flash("✅ Usuario eliminado", "success")
    else:
        flash(f"❌ {err}", "error")
    return redirect(url_for('usuarios.lista'))


# ── Audit log ────────────────────────────────────────────────────────────────

@usuarios_bp.route('/audit_log')
@login_required
@require_permiso('audit_log', 'ver')
def audit_log():
    page     = request.args.get('page', 1, type=int)
    modulo   = request.args.get('modulo', '').strip() or None
    uid_fil  = request.args.get('usuario_id', type=int)
    filas, total = listar_audit_log(page=page, per_page=50, modulo=modulo, usuario_id=uid_fil)
    total_pages  = (total + 49) // 50

    modulos_disponibles = [
        'auth', 'inventario', 'ventas', 'clientes',
        'presupuestos', 'remitos', 'usuarios', 'gastos',
    ]
    usuarios = listar_usuarios()
    return render_template('usuarios/audit_log.html',
                           filas=filas, total=total,
                           page=page, total_pages=total_pages,
                           modulo_filtro=modulo or '',
                           uid_filtro=uid_fil or '',
                           modulos_disponibles=modulos_disponibles,
                           usuarios=usuarios)
