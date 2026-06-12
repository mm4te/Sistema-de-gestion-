# routes/compras.py
from datetime import date

from flask import (Blueprint, flash, g, redirect, render_template,
                   request, send_file, url_for)

from models import get_conn
from routes import login_required, require_permiso
from services.compras_service import (
    CONDICIONES_IVA, ESTADOS_COMPRA, METODOS_PAGO,
    actualizar_compra, actualizar_proveedor_nacional,
    agregar_item, calcular_totales, cerrar_compra,
    crear_compra, crear_proveedor_nacional,
    eliminar_item, eliminar_proveedor_nacional,
    generar_pdf_compra,
    get_compra, get_compra_items, get_compra_pagos,
    get_proveedor, listar_compras, listar_proveedores_nacionales,
    registrar_pago, registrar_recepcion,
)

compras_bp = Blueprint('compras', __name__)


# ── Listado ───────────────────────────────────────────────────────────────────

@compras_bp.route('/compras')
@login_required
@require_permiso('compras', 'ver')
def lista():
    page         = request.args.get('page', 1, type=int)
    estado       = request.args.get('estado', '').strip() or None
    proveedor_id = request.args.get('proveedor_id', type=int)
    fecha_desde  = request.args.get('fecha_desde', '').strip() or None
    fecha_hasta  = request.args.get('fecha_hasta', '').strip() or None

    filas, total = listar_compras(
        estado=estado, proveedor_id=proveedor_id,
        fecha_desde=fecha_desde, fecha_hasta=fecha_hasta,
        page=page, per_page=20
    )
    total_pages  = (total + 19) // 20
    proveedores  = listar_proveedores_nacionales()

    return render_template('compras/lista.html',
                           filas=filas, total=total,
                           page=page, total_pages=total_pages,
                           proveedores=proveedores,
                           estados=ESTADOS_COMPRA,
                           estado_filtro=estado or '',
                           proveedor_id_filtro=proveedor_id or '',
                           fecha_desde=fecha_desde or '',
                           fecha_hasta=fecha_hasta or '')


# ── Nueva ─────────────────────────────────────────────────────────────────────

@compras_bp.route('/compras/nueva', methods=['GET', 'POST'])
@login_required
@require_permiso('compras', 'crear')
def nueva():
    proveedores = listar_proveedores_nacionales()

    if request.method == 'POST':
        proveedor_id             = request.form.get('proveedor_id', type=int)
        fecha                    = request.form.get('fecha', '').strip()
        numero_factura_proveedor = request.form.get('numero_factura_proveedor', '').strip() or None
        observaciones            = request.form.get('observaciones', '').strip() or None

        if not proveedor_id:
            flash("Debe seleccionar un proveedor", "error")
            return _render_form(None, proveedores)
        if not fecha:
            flash("La fecha es requerida", "error")
            return _render_form(None, proveedores)

        ok, result = crear_compra(proveedor_id, fecha, numero_factura_proveedor, observaciones)
        if ok:
            flash("Compra creada. Ahora agregá los productos.", "success")
            return redirect(url_for('compras.detalle', compra_id=result))
        flash(f"Error: {result}", "error")

    return _render_form(None, proveedores)


def _render_form(compra, proveedores):
    return render_template('compras/form.html',
                           compra=compra, proveedores=proveedores,
                           hoy=date.today().strftime('%Y-%m-%d'),
                           titulo="Nueva Compra" if not compra else "Editar Compra")


# ── Editar ────────────────────────────────────────────────────────────────────

@compras_bp.route('/compras/<int:compra_id>/editar', methods=['GET', 'POST'])
@login_required
@require_permiso('compras', 'editar')
def editar(compra_id):
    compra = get_compra(compra_id)
    if not compra:
        flash("Compra no encontrada", "error")
        return redirect(url_for('compras.lista'))
    if compra['estado'] == 'cerrado':
        flash("No se puede editar una compra cerrada", "error")
        return redirect(url_for('compras.detalle', compra_id=compra_id))

    proveedores = listar_proveedores_nacionales()

    if request.method == 'POST':
        proveedor_id             = request.form.get('proveedor_id', type=int)
        fecha                    = request.form.get('fecha', '').strip()
        numero_factura_proveedor = request.form.get('numero_factura_proveedor', '').strip() or None
        observaciones            = request.form.get('observaciones', '').strip() or None

        ok, err = actualizar_compra(compra_id, proveedor_id, fecha,
                                    numero_factura_proveedor, observaciones)
        if ok:
            flash("Compra actualizada", "success")
            return redirect(url_for('compras.detalle', compra_id=compra_id))
        flash(f"Error: {err}", "error")

    return render_template('compras/form.html',
                           compra=compra, proveedores=proveedores,
                           hoy=date.today().strftime('%Y-%m-%d'),
                           titulo="Editar Compra")


# ── Detalle ───────────────────────────────────────────────────────────────────

@compras_bp.route('/compras/<int:compra_id>')
@login_required
@require_permiso('compras', 'ver')
def detalle(compra_id):
    compra = get_compra(compra_id)
    if not compra:
        flash("Compra no encontrada", "error")
        return redirect(url_for('compras.lista'))

    items   = get_compra_items(compra_id)
    pagos   = get_compra_pagos(compra_id)
    totales = calcular_totales(compra_id)

    conn = get_conn()
    productos = conn.execute(
        "SELECT id, sku, descripcion FROM productos WHERE activo=1 ORDER BY descripcion ASC"
    ).fetchall()
    conn.close()

    return render_template('compras/detalle.html',
                           compra=compra, items=items, pagos=pagos,
                           totales=totales, productos=productos,
                           metodos_pago=METODOS_PAGO,
                           estados=ESTADOS_COMPRA,
                           hoy=date.today().strftime('%Y-%m-%d'))


# ── Agregar ítem ──────────────────────────────────────────────────────────────

@compras_bp.route('/compras/<int:compra_id>/items/agregar', methods=['POST'])
@login_required
@require_permiso('compras', 'editar')
def agregar_item_route(compra_id):
    compra = get_compra(compra_id)
    if not compra or compra['estado'] == 'cerrado':
        flash("No se puede modificar esta compra", "error")
        return redirect(url_for('compras.detalle', compra_id=compra_id))

    producto_id = request.form.get('producto_id', type=int)
    descripcion = request.form.get('descripcion', '').strip()
    cant_str    = request.form.get('cantidad', '0').replace(',', '.').strip()
    costo_str   = request.form.get('costo_unitario', '0').replace(',', '.').strip()

    if not descripcion and not producto_id:
        flash("Ingresá una descripción o seleccioná un producto existente", "error")
        return redirect(url_for('compras.detalle', compra_id=compra_id))

    try:
        cantidad = float(cant_str)
        costo    = float(costo_str)
    except ValueError:
        flash("Cantidad o costo inválido", "error")
        return redirect(url_for('compras.detalle', compra_id=compra_id))

    ok, err = agregar_item(compra_id, producto_id, descripcion, cantidad, costo)
    if ok:
        flash("Producto agregado a la compra", "success")
    else:
        flash(f"Error: {err}", "error")
    return redirect(url_for('compras.detalle', compra_id=compra_id))


# ── Eliminar ítem ─────────────────────────────────────────────────────────────

@compras_bp.route('/compras/<int:compra_id>/items/<int:item_id>/eliminar', methods=['POST'])
@login_required
@require_permiso('compras', 'editar')
def eliminar_item_route(compra_id, item_id):
    compra = get_compra(compra_id)
    if not compra or compra['estado'] == 'cerrado':
        flash("No se puede modificar esta compra", "error")
        return redirect(url_for('compras.detalle', compra_id=compra_id))
    eliminar_item(item_id)
    flash("Producto eliminado de la compra", "success")
    return redirect(url_for('compras.detalle', compra_id=compra_id))


# ── Registrar pago ────────────────────────────────────────────────────────────

@compras_bp.route('/compras/<int:compra_id>/pagos/registrar', methods=['POST'])
@login_required
@require_permiso('compras', 'editar')
def registrar_pago_route(compra_id):
    monto_str   = request.form.get('monto', '').replace(',', '.').strip()
    fecha_pago  = request.form.get('fecha_pago', '').strip() or None
    metodo_pago = request.form.get('metodo_pago', '').strip() or None
    comprobante = request.form.get('comprobante', '').strip() or None

    try:
        monto = float(monto_str)
    except ValueError:
        flash("Monto inválido", "error")
        return redirect(url_for('compras.detalle', compra_id=compra_id))

    ok, err = registrar_pago(compra_id, monto, metodo_pago, fecha_pago,
                             comprobante, usuario_id=g.user_id)
    if ok:
        flash("Pago registrado y debitado de caja", "success")
    else:
        flash(f"Error: {err}", "error")
    return redirect(url_for('compras.detalle', compra_id=compra_id))


# ── Registrar recepción ───────────────────────────────────────────────────────

@compras_bp.route('/compras/<int:compra_id>/recepcion', methods=['POST'])
@login_required
@require_permiso('compras', 'editar')
def registrar_recepcion_route(compra_id):
    recepciones = {}
    for key, val in request.form.items():
        if key.startswith('recv_'):
            item_id = key[5:]
            try:
                cant = float(val.replace(',', '.').strip())
                if cant > 0:
                    recepciones[item_id] = cant
            except (ValueError, AttributeError):
                pass

    ok, err = registrar_recepcion(compra_id, recepciones, usuario_id=g.user_id)
    if ok:
        flash("Recepción registrada", "success")
    else:
        flash(f"Error: {err}", "error")
    return redirect(url_for('compras.detalle', compra_id=compra_id))


# ── Cerrar compra ─────────────────────────────────────────────────────────────

@compras_bp.route('/compras/<int:compra_id>/cerrar', methods=['POST'])
@login_required
@require_permiso('compras', 'cerrar')
def cerrar(compra_id):
    ok, err = cerrar_compra(compra_id, usuario_id=g.user_id)
    if ok:
        flash("Compra cerrada. Costos aplicados al inventario.", "success")
    else:
        flash(f"Error: {err}", "error")
    return redirect(url_for('compras.detalle', compra_id=compra_id))


# ── PDF ───────────────────────────────────────────────────────────────────────

@compras_bp.route('/compras/<int:compra_id>/pdf')
@login_required
@require_permiso('compras', 'ver')
def generar_pdf_route(compra_id):
    compra = get_compra(compra_id)
    if not compra:
        flash("Compra no encontrada", "error")
        return redirect(url_for('compras.lista'))
    buf = generar_pdf_compra(compra_id)
    if not buf:
        flash("Error al generar el PDF", "error")
        return redirect(url_for('compras.detalle', compra_id=compra_id))
    return send_file(buf,
                     as_attachment=True,
                     download_name=f"compra_{compra['numero']}.pdf",
                     mimetype='application/pdf')


# ── CRUD Proveedores nacionales ───────────────────────────────────────────────

@compras_bp.route('/compras/proveedores')
@login_required
@require_permiso('compras', 'ver')
def proveedores():
    lista_prov = listar_proveedores_nacionales()
    return render_template('compras/proveedores.html',
                           proveedores=lista_prov,
                           condiciones_iva=CONDICIONES_IVA)


@compras_bp.route('/compras/proveedores/nuevo', methods=['POST'])
@login_required
@require_permiso('compras', 'crear')
def nuevo_proveedor():
    nombre        = request.form.get('nombre', '').strip()
    cuit          = request.form.get('cuit', '').strip() or None
    condicion_iva = request.form.get('condicion_iva', '').strip() or None
    contacto      = request.form.get('contacto', '').strip() or None
    telefono      = request.form.get('telefono', '').strip() or None
    email         = request.form.get('email', '').strip() or None
    direccion     = request.form.get('direccion', '').strip() or None
    notas         = request.form.get('notas', '').strip() or None

    ok, result = crear_proveedor_nacional(nombre, cuit, condicion_iva,
                                          contacto, telefono, email, direccion, notas)
    if ok:
        flash(f"Proveedor '{nombre}' creado", "success")
    else:
        flash(f"Error: {result}", "error")
    return redirect(url_for('compras.proveedores'))


@compras_bp.route('/compras/proveedores/<int:prov_id>/editar', methods=['POST'])
@login_required
@require_permiso('compras', 'editar')
def editar_proveedor(prov_id):
    nombre        = request.form.get('nombre', '').strip()
    cuit          = request.form.get('cuit', '').strip() or None
    condicion_iva = request.form.get('condicion_iva', '').strip() or None
    contacto      = request.form.get('contacto', '').strip() or None
    telefono      = request.form.get('telefono', '').strip() or None
    email         = request.form.get('email', '').strip() or None
    direccion     = request.form.get('direccion', '').strip() or None
    notas         = request.form.get('notas', '').strip() or None

    ok, err = actualizar_proveedor_nacional(prov_id, nombre, cuit, condicion_iva,
                                            contacto, telefono, email, direccion, notas)
    if ok:
        flash("Proveedor actualizado", "success")
    else:
        flash(f"Error: {err}", "error")
    return redirect(url_for('compras.proveedores'))


@compras_bp.route('/compras/proveedores/<int:prov_id>/eliminar', methods=['POST'])
@login_required
@require_permiso('compras', 'eliminar')
def eliminar_proveedor_route(prov_id):
    ok, err = eliminar_proveedor_nacional(prov_id)
    if ok:
        flash("Proveedor eliminado", "success")
    else:
        flash(f"Error: {err}", "error")
    return redirect(url_for('compras.proveedores'))
