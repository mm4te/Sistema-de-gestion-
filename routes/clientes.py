# routes/clientes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from models import get_clientes, add_cliente, get_cliente_by_id
import sqlite3

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

#eliminar cliente con boton eliminar en clientes.html y una ventana de confirmacion para evitar eliminaciones accidentales, ademas de mostrar un mensaje de exito o error segun corresponda
@clientes_bp.route('/eliminar_cliente/<int:cliente_id>', methods=['POST'])
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

#editar cliente con boton editar en clientes.html que redirige a una nueva ruta /editar_cliente/<int:cliente_id> donde se muestra un formulario con los datos del cliente para editar, y al enviar el formulario se actualizan los datos del cliente en la base de datos, mostrando un mensaje de exito o error segun corresponda

@clientes_bp.route('/editar_cliente/<int:cliente_id>', methods=['GET', 'POST'])
def editar_cliente(cliente_id):
    cliente = get_cliente_by_id(cliente_id)
    if not cliente:
        flash("Cliente no encontrado", "error")
        return redirect(url_for('clientes.clientes'))
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        cuit = request.form.get('cuit', '').strip()
        telefono = request.form.get('telefono', '').strip()
        if not nombre:
            flash("❌ El nombre es obligatorio", "error")
        else:
            conn = sqlite3.connect('negocio.db')
            cursor = conn.cursor()
            try:
                cursor.execute("UPDATE clientes SET nombre = ?, cuit = ?, telefono = ? WHERE id = ?", (nombre, cuit, telefono, cliente_id))
                conn.commit()
                flash("✅ Cliente actualizado correctamente", "success")
                return redirect(url_for('clientes.clientes'))
            except Exception as e:
                flash(f"❌ Error al actualizar: {str(e)}", "error")
            finally:
                conn.close()
    return render_template('editar_cliente.html', cliente=cliente)