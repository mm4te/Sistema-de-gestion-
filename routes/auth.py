# routes/auth.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from models import init_db
from werkzeug.security import check_password_hash
import sqlite3

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = sqlite3.connect('negocio.db')
        user = conn.execute("SELECT id, password_hash FROM usuarios WHERE username = ?", (username,)).fetchone()
        conn.close()
        if user and check_password_hash(user[1], password):
            session['user_id'] = user[0]
            flash("✅ Sesión iniciada", "success")
            return redirect(url_for('main.index'))
        else:
            flash("❌ Usuario o contraseña incorrectos", "error")
    return render_template('login.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash("👋 Sesión cerrada", "success")
    return redirect(url_for('auth.login'))