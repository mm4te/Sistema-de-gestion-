# routes/clientes.py
import sqlite3
from flask import Blueprint, render_template, request, redirect, url_for, flash
from models import get_clientes, add_cliente, get_cliente_by_id, get_conn
from routes import login_required

clientes_bp = Blueprint('clientes', __name__)

@clientes_bp.route('/clientes')
@login_required
def clientes():
    page        = request.args.get('page', 1, type=int)
    tipo_filtro = request.args.get('tipo', '')  # '' | '0' | '1'
    conn        = get_conn()

    condicion = ""
    params    = []
    if tipo_filtro in ('0', '1'):
        condicion = "WHERE tipo = ?"
        params.append(int(tipo_filtro))

    total = conn.execute(f"SELECT COUNT(*) FROM clientes {condicion}", params).fetchone()[0]
    offset = (page - 1) * 20
    lista = conn.execute(
        f"SELECT * FROM clientes {condicion} ORDER BY nombre LIMIT 20 OFFSET ?",
        (*params, offset)
    ).fetchall()
    conn.close()

    total_pages = (total + 19) // 20
    return render_template('clientes.html', clientes=lista, page=page,
                           total_pages=total_pages, total=total,
                           tipo_filtro=tipo_filtro)

@clientes_bp.route('/nuevo_cliente', methods=['GET', 'POST'])
@login_required
def nuevo_cliente():
    if request.method == 'POST':
        nombre   = request.form.get('nombre', '').strip()
        cuit     = request.form.get('cuit', '').strip()
        telefono = request.form.get('telefono', '').strip()
        dni      = request.form.get('dni', '').strip()
        email    = request.form.get('email', '').strip()
        tipo     = int(request.form.get('tipo', 0))
        if not nombre:
            flash("❌ El nombre es obligatorio", "error")
        else:
            success, msg = add_cliente(nombre, cuit, telefono, dni, email, tipo)
            if success:
                flash("✅ Cliente creado correctamente", "success")
                return redirect(url_for('clientes.clientes'))
            else:
                flash(f"❌ {msg}", "error")
    return render_template('nuevo_cliente.html')

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
        dni      = request.form.get('dni', '').strip()
        email    = request.form.get('email', '').strip()
        tipo     = int(request.form.get('tipo', 0))
        if not nombre:
            flash("❌ El nombre es obligatorio", "error")
        else:
            conn = get_conn()
            try:
                conn.execute(
                    "UPDATE clientes SET nombre=?, cuit=?, telefono=?, dni=?, email=?, tipo=? WHERE id=?",
                    (nombre, cuit, telefono, dni, email, tipo, cliente_id)
                )
                conn.commit()
                flash("✅ Cliente actualizado correctamente", "success")
                return redirect(url_for('clientes.clientes'))
            except Exception as e:
                flash(f"❌ Error al actualizar: {str(e)}", "error")
            finally:
                conn.close()
    return render_template('editar_cliente.html', cliente=cliente)

@clientes_bp.route('/eliminar_cliente/<int:cliente_id>', methods=['POST'])
@login_required
def eliminar_cliente(cliente_id):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM clientes WHERE id = ?", (cliente_id,))
        flash("✅ Cliente eliminado correctamente", "success")
        conn.commit()
    except Exception as e:
        flash(f"❌ Error al eliminar: {str(e)}", "error")
    finally:
        conn.close()
    return redirect(url_for('clientes.clientes'))
