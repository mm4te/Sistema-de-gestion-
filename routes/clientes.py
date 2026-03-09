# routes/clientes.py
import sqlite3
from flask import Blueprint, render_template, request, redirect, url_for, flash
from models import get_clientes, add_cliente, get_cliente_by_id
from routes import login_required

clientes_bp = Blueprint('clientes', __name__)

@clientes_bp.route('/clientes')
@login_required
def clientes():
    page = request.args.get('page', 1, type=int)
    lista, total = get_clientes(page)
    total_pages = (total + 19) // 20
    return render_template('clientes.html', clientes=lista, page=page,
                           total_pages=total_pages, total=total)

@clientes_bp.route('/nuevo_cliente', methods=['GET', 'POST'])
@login_required
def nuevo_cliente():
    if request.method == 'POST':
        nombre   = request.form.get('nombre', '').strip()
        cuit     = request.form.get('cuit', '').strip()
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

@clientes_bp.route('/eliminar_cliente/<int:cliente_id>', methods=['POST'])
@login_required
def eliminar_cliente(cliente_id):
    conn = sqlite3.connect('negocio.db')
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM clientes WHERE id = ?", (cliente_id,))
        if cursor.rowcount == 0:
            flash("❌ Cliente no encontrado", "error")
        else:
            flash("✅ Cliente eliminado correctamente", "success")
        conn.commit()
    except Exception as e:
        flash(f"❌ Error al eliminar: {str(e)}", "error")
    finally:
        conn.close()
    return redirect(url_for('clientes.clientes'))

@clientes_bp.route('/editar_cliente/<int:cliente_id>', methods=['GET', 'POST'])
@login_required
def editar_cliente(cliente_id):
    cliente = get_cliente_by_id(cliente_id)
    if not cliente:
        flash("Cliente no encontrado", "error")
        return redirect(url_for('clientes.clientes'))
    if request.method == 'POST':
        nombre   = request.form.get('nombre', '').strip()
        cuit     = request.form.get('cuit', '').strip()
        telefono = request.form.get('telefono', '').strip()
        if not nombre:
            flash("❌ El nombre es obligatorio", "error")
        else:
            conn = sqlite3.connect('negocio.db')
            try:
                conn.execute(
                    "UPDATE clientes SET nombre = ?, cuit = ?, telefono = ? WHERE id = ?",
                    (nombre, cuit, telefono, cliente_id)
                )
                conn.commit()
                flash("✅ Cliente actualizado correctamente", "success")
                return redirect(url_for('clientes.clientes'))
            except Exception as e:
                flash(f"❌ Error al actualizar: {str(e)}", "error")
            finally:
                conn.close()
    return render_template('editar_cliente.html', cliente=cliente)
