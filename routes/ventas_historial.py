# routes/ventas_historial.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from functools import wraps
import sqlite3

# Crear blueprint
ventas_historial_bp = Blueprint('ventas_historial', __name__)

# Decorador de login requerido (copia local si no lo compartes globalmente)
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

@ventas_historial_bp.route('/ventas_historial')
@login_required
def ventas_historial():
    page = request.args.get('page', 1, type=int)
    search_id = request.args.get('id', '').strip()
    per_page = 20

    conn = sqlite3.connect('negocio.db')
    
    if search_id:
        try:
            venta_id = int(search_id)
            ventas = conn.execute("""
                SELECT v.id, v.fecha, c.nombre, v.total
                FROM ventas v
                JOIN clientes c ON v.cliente_id = c.id
                WHERE v.id = ?
                ORDER BY v.fecha DESC
            """, (venta_id,)).fetchall()
            total = len(ventas)
            total_pages = 1
            page = 1
        except ValueError:
            flash("❌ El ID debe ser un número entero.", "error")
            ventas = []
            total = 0
            total_pages = 0
    else:
        total = conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0]
        offset = (page - 1) * per_page
        ventas = conn.execute("""
            SELECT v.id, v.fecha, c.nombre, v.total
            FROM ventas v
            JOIN clientes c ON v.cliente_id = c.id
            ORDER BY v.fecha DESC
            LIMIT ? OFFSET ?
        """, (per_page, offset)).fetchall()
        total_pages = (total + per_page - 1) // per_page

    conn.close()

    return render_template(
        'ventas_historial.html',
        ventas=ventas,
        page=page,
        total_pages=total_pages,
        total=total,
        search_id=search_id
    )


@ventas_historial_bp.route('/venta/<int:venta_id>')
@login_required
def detalle_venta(venta_id):
    conn = sqlite3.connect('negocio.db')
    
    # Obtener datos de la venta
    venta = conn.execute("""
        SELECT v.id, v.fecha, c.nombre, v.total, v.metodo_pago, v.cuotas
        FROM ventas v
        JOIN clientes c ON v.cliente_id = c.id
        WHERE v.id = ?
    """, (venta_id,)).fetchone()
    
    if not venta:
        conn.close()
        flash("❌ Venta no encontrada.", "error")
        return redirect(url_for('ventas_historial.ventas_historial'))
    
    # Obtener productos de la venta
    productos = conn.execute("""
        SELECT p.descripcion, dv.cantidad, dv.precio_unitario
        FROM detalle_venta dv
        JOIN productos p ON dv.producto_id = p.id
        WHERE dv.venta_id = ?
    """, (venta_id,)).fetchall()
    
    conn.close()
    
    return render_template('detalle_venta.html', venta=venta, productos=productos)