# routes/__init__.py
from functools import wraps
from flask import session, redirect, url_for, flash, g


def login_required(f):
    """Redirige al login si no hay sesión activa."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


def require_rol(nivel_minimo):
    """Exige que el usuario tenga nivel <= nivel_minimo (1=SuperAdmin, …, 5=Depósito)."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('auth.login'))
            if g.get('rol_nivel', 99) > nivel_minimo:
                flash("⛔ No tenés el nivel de acceso requerido", "error")
                return redirect(url_for('main.index'))
            return f(*args, **kwargs)
        return decorated
    return decorator


def require_permiso(modulo, accion):
    """Exige que el usuario tenga el permiso (modulo, accion) o sea SuperAdmin."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('auth.login'))
            if not g.get('es_superadmin') and (modulo, accion) not in g.get('permisos', set()):
                flash("⛔ No tenés permiso para esta acción", "error")
                return redirect(url_for('main.index'))
            return f(*args, **kwargs)
        return decorated
    return decorator
