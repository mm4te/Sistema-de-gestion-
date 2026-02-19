# routes/clientes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from models import get_clientes, add_cliente, get_cliente_by_id

clientes_bp = Blueprint('clientes', __name__)

@clientes_bp.route('/clientes')
def clientes():
    page = request.args.get('page', 1, type=int)
    lista, total = get_clientes(page)
    total_pages = (total + 19) // 20
    return render_template('clientes.html', clientes=lista, page=page, total_pages=total_pages, total=total)

@clientes_bp.route('/nuevo_cliente', methods=['GET', 'POST'])
def nuevo_cliente():
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        cuit = request.form.get('cuit', '').strip()
        telefono = request.form.get('telefono', '').strip()
        if not nombre:
            flash("❌ El nombre es obligatorio", "error")
        else:
            success, msg = add_cliente(nombre, cuit, telefono)
            if success:
                flash("✅ Cliente creado correctamente", "success")
                return redirect(url_for('clientes.clientes'))
            else:
                flash(f"❌ {msg}", "error")
    return render_template('nuevo_cliente.html')
