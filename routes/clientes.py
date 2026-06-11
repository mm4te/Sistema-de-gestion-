# routes/clientes.py
import sqlite3
import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from models import get_clientes, add_cliente, get_cliente_by_id, get_conn
from routes import login_required

clientes_bp = Blueprint('clientes', __name__)
logger = logging.getLogger(__name__)

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

@clientes_bp.route('/clientes/consultar-cuit')
@login_required
def consultar_cuit():
    cuit = request.args.get('cuit', '').replace('-', '').replace(' ', '').strip()
    if len(cuit) != 11 or not cuit.isdigit():
        return jsonify({'ok': False, 'error': 'CUIT inválido (debe tener 11 dígitos)'}), 400
    try:
        from services.afip_service import consultar_cuit_padron
        datos = consultar_cuit_padron(cuit)
        return jsonify({'ok': True, **datos})
    except Exception as e:
        logger.warning("Error consultando CUIT %s: %s", cuit, str(e))
        return jsonify({'ok': False, 'error': str(e)})


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
        razon_social        = request.form.get('razon_social', '').strip()        or None
        condicion_iva       = request.form.get('condicion_iva', '').strip()       or None
        domicilio_fiscal    = request.form.get('domicilio_fiscal', '').strip()    or None
        localidad           = request.form.get('localidad', '').strip()           or None
        provincia           = request.form.get('provincia', '').strip()           or None
        codigo_postal       = request.form.get('codigo_postal', '').strip()       or None
        actividad_principal = request.form.get('actividad_principal', '').strip() or None
        estado_afip         = request.form.get('estado_afip', '').strip()         or None
        if not nombre:
            flash("❌ El nombre es obligatorio", "error")
        else:
            success, msg = add_cliente(
                nombre, cuit, telefono, dni, email, tipo,
                razon_social=razon_social, condicion_iva=condicion_iva,
                domicilio_fiscal=domicilio_fiscal, localidad=localidad,
                provincia=provincia, codigo_postal=codigo_postal,
                actividad_principal=actividad_principal, estado_afip=estado_afip,
            )
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
        # Campos fiscales: usa el valor del form si se envía, sino preserva el existente en DB
        def _fld(key, existing):
            v = request.form.get(key, '').strip()
            return v if v else (existing or None)
        razon_social        = _fld('razon_social',        cliente['razon_social'])
        condicion_iva       = _fld('condicion_iva',       cliente['condicion_iva']) or 'consumidor_final'
        domicilio_fiscal    = _fld('domicilio_fiscal',    cliente['domicilio_fiscal'])
        localidad           = _fld('localidad',           cliente['localidad'])
        provincia           = _fld('provincia',           cliente['provincia'])
        codigo_postal       = _fld('codigo_postal',       cliente['codigo_postal'])
        actividad_principal = _fld('actividad_principal', cliente['actividad_principal'])
        estado_afip         = _fld('estado_afip',         cliente['estado_afip'])
        if not nombre:
            flash("❌ El nombre es obligatorio", "error")
        else:
            conn = get_conn()
            try:
                conn.execute(
                    "UPDATE clientes"
                    " SET nombre=?, cuit=?, telefono=?, dni=?, email=?, tipo=?,"
                    "     razon_social=?, condicion_iva=?, domicilio_fiscal=?,"
                    "     localidad=?, provincia=?, codigo_postal=?,"
                    "     actividad_principal=?, estado_afip=?"
                    " WHERE id=?",
                    (nombre, cuit, telefono, dni, email, tipo,
                     razon_social, condicion_iva, domicilio_fiscal,
                     localidad, provincia, codigo_postal,
                     actividad_principal, estado_afip,
                     cliente_id)
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
