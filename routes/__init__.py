# routes/__init__.py
from functools import wraps
from flask import session, redirect, url_for

def login_required(f):
    """Decorador centralizado. Importar desde acá en todos los blueprints."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function
