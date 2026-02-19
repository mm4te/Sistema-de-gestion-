# routes/main.py
from flask import Blueprint, render_template, session, redirect, url_for
from functools import wraps
from models import get_dashboard_data

main_bp = Blueprint('main', __name__)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

@main_bp.route('/')
@login_required
def index():
    data = get_dashboard_data()
    return render_template('index.html', **data)