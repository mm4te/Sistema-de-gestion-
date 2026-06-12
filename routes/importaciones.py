# routes/importaciones.py
import os
import uuid

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, send_file, session, url_for)
from werkzeug.utils import secure_filename

from models import get_conn
from routes import login_required, require_permiso
from services.importaciones_service import (
    ESTADOS_IMPORTACION, METODOS_PAGO, MONEDAS, TIPOS_GASTO_IMP,
    actualizar_importacion, actualizar_proveedor,
    agregar_gasto_importacion, agregar_item,
    calcular_costos, cambiar_estado, cerrar_importacion,
    crear_importacion, crear_proveedor,
    eliminar_gasto_importacion, eliminar_item, eliminar_proveedor,
    get_importacion, get_importacion_gastos, get_importacion_items,
    get_proveedor, listar_importaciones, listar_proveedores,
    registrar_pago,
)

importaciones_bp = Blueprint('importaciones', __name__)

EXTENSIONES_PERMITIDAS = {'pdf', 'jpg', 'jpeg', 'png', 'webp'}


def _allowed(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in EXTENSIONES_PERMITIDAS


def _guardar_comprobante(file):
    if not file or not file.filename:
        return None, None
    if not _allowed(file.filename):
        return None, None
    ext  = secure_filename(file.filename).rsplit('.', 1)[-1].lower()
    nombre_guardado = f"{uuid.uuid4().hex}.{ext}"
    carpeta = current_app.config.get('UPLOAD_FOLDER_IMPORTACIONES', '')
    ruta    = os.path.join(carpeta, nombre_guardado)
    file.save(ruta)
    return secure_filename(file.filename), ruta


# ── Lista ─────────────────────────────────────────────────────────────────────

@importaciones_bp.route('/importaciones')
@login_required
@require_permiso('importaciones', 'ver')
def lista():
    page         = request.args.get('page', 1, type=int)
    estado       = request.args.get('estado', '').strip() or None
    proveedor_id = request.args.get('proveedor_id', type=int)

    filas, total = listar_importaciones(estado=estado, proveedor_id=proveedor_id,
                                         page=page, per_page=20)
    total_pages  = (total + 19) // 20
    proveedores  = listar_proveedores()

    return render_template('importaciones/lista.html',
                           filas=filas, total=total,
                           page=page, total_pages=total_pages,
                           proveedores=proveedores,
                           estados=ESTADOS_IMPORTACION,
                           estado_filtro=estado or '',
                           proveedor_id_filtro=proveedor_id or '')


# ── Nueva ─────────────────────────────────────────────────────────────────────

@importaciones_bp.route('/importaciones/nueva', methods=['GET', 'POST'])
@login_required
@require_permiso('importaciones', 'crear')
def nueva():
    proveedores = listar_proveedores()

    if request.method == 'POST':
        proveedor_id  = request.form.get('proveedor_id', type=int)
        fecha_pedido  = request.form.get('fecha_pedido', '').strip()
        moneda_origen = request.form.get('moneda_origen', 'USD').strip()
        tc_str        = request.form.get('tipo_cambio', '1').replace(',', '.').strip()
        observaciones = request.form.get('observaciones', '').strip() or None

        if not proveedor_id:
            flash("Debe seleccionar un proveedor", "error")
            return _render_form(None, proveedores)
        if not fecha_pedido:
            flash("La fecha del pedido es requerida", "error")
            return _render_form(None, proveedores)
        try:
            tipo_cambio = float(tc_str)
        except ValueError:
            flash("Tipo de cambio inválido", "error")
            return _render_form(None, proveedores)

        ok, result = crear_importacion(proveedor_id, fecha_pedido,
                                        moneda_origen, tipo_cambio, observaciones)
        if ok:
            flash("Importación creada. Ahora agregá los productos.", "success")
            return redirect(url_for('importaciones.detalle', imp_id=result))
        flash(f"Error: {result}", "error")

    from datetime import date
    return _render_form(None, proveedores, hoy=date.today().strftime('%Y-%m-%d'))


def _render_form(imp, proveedores, hoy=None):
    from datetime import date
    return render_template('importaciones/form.html',
                           imp=imp, proveedores=proveedores, monedas=MONEDAS,
                           hoy=hoy or date.today().strftime('%Y-%m-%d'),
                           titulo="Nueva Importación" if not imp else "Editar Importación")


# ── Editar ────────────────────────────────────────────────────────────────────

@importaciones_bp.route('/importaciones/<int:imp_id>/editar', methods=['GET', 'POST'])
@login_required
@require_permiso('importaciones', 'editar')
def editar(imp_id):
    imp = get_importacion(imp_id)
    if not imp:
        flash("Importación no encontrada", "error")
        return redirect(url_for('importaciones.lista'))
    if imp['estado'] == 'cerrado':
        flash("No se puede editar una importación cerrada", "error")
        return redirect(url_for('importaciones.detalle', imp_id=imp_id))

    proveedores = listar_proveedores()

    if request.method == 'POST':
        proveedor_id  = request.form.get('proveedor_id', type=int)
        fecha_pedido  = request.form.get('fecha_pedido', '').strip()
        moneda_origen = request.form.get('moneda_origen', 'USD').strip()
        tc_str        = request.form.get('tipo_cambio', '1').replace(',', '.').strip()
        observaciones = request.form.get('observaciones', '').strip() or None

        try:
            tipo_cambio = float(tc_str)
        except ValueError:
            flash("Tipo de cambio inválido", "error")
            return render_template('importaciones/form.html', imp=imp,
                                   proveedores=proveedores, monedas=MONEDAS,
                                   titulo="Editar Importación")

        ok, err = actualizar_importacion(imp_id, proveedor_id, fecha_pedido,
                                          moneda_origen, tipo_cambio, observaciones)
        if ok:
            flash("Importación actualizada", "success")
            return redirect(url_for('importaciones.detalle', imp_id=imp_id))
        flash(f"Error: {err}", "error")

    return render_template('importaciones/form.html', imp=imp,
                           proveedores=proveedores, monedas=MONEDAS,
                           titulo="Editar Importación")


# ── Detalle ───────────────────────────────────────────────────────────────────

@importaciones_bp.route('/importaciones/<int:imp_id>')
@login_required
@require_permiso('importaciones', 'ver')
def detalle(imp_id):
    imp = get_importacion(imp_id)
    if not imp:
        flash("Importación no encontrada", "error")
        return redirect(url_for('importaciones.lista'))

    items  = get_importacion_items(imp_id)
    gastos = get_importacion_gastos(imp_id)

    total_fob     = sum(float(it['cantidad']) * float(it['precio_unitario_fob']) for it in items)
    total_fob_ars = total_fob * float(imp['tipo_cambio'])
    total_gastos  = sum(float(g['monto']) for g in gastos)
    total_final   = total_fob_ars + total_gastos
    unidades      = sum(float(it['cantidad']) for it in items)
    costo_prom    = total_final / unidades if unidades > 0 else 0

    costos_preview = calcular_costos(imp_id) if items else []

    conn = get_conn()
    productos = conn.execute(
        "SELECT id, sku, descripcion FROM productos WHERE activo=1 ORDER BY descripcion ASC"
    ).fetchall()
    conn.close()

    return render_template('importaciones/detalle.html',
                           imp=imp, items=items, gastos=gastos,
                           total_fob=total_fob, total_fob_ars=total_fob_ars,
                           total_gastos=total_gastos, total_final=total_final,
                           costo_prom=costo_prom, unidades=unidades,
                           costos_preview=costos_preview,
                           productos=productos,
                           tipos_gasto=TIPOS_GASTO_IMP,
                           metodos_pago=METODOS_PAGO,
                           estados=ESTADOS_IMPORTACION)


# ── Agregar item ──────────────────────────────────────────────────────────────

@importaciones_bp.route('/importaciones/<int:imp_id>/items/agregar', methods=['POST'])
@login_required
@require_permiso('importaciones', 'editar')
def agregar_item_route(imp_id):
    imp = get_importacion(imp_id)
    if not imp or imp['estado'] == 'cerrado':
        flash("No se puede modificar esta importación", "error")
        return redirect(url_for('importaciones.detalle', imp_id=imp_id))

    producto_id = request.form.get('producto_id', type=int)
    descripcion = request.form.get('descripcion', '').strip()
    cant_str    = request.form.get('cantidad', '0').replace(',', '.').strip()
    fob_str     = request.form.get('precio_unitario_fob', '0').replace(',', '.').strip()

    if not descripcion and not producto_id:
        flash("Ingresá una descripción o seleccioná un producto existente", "error")
        return redirect(url_for('importaciones.detalle', imp_id=imp_id))

    try:
        cantidad = float(cant_str)
        precio   = float(fob_str)
    except ValueError:
        flash("Cantidad o precio inválido", "error")
        return redirect(url_for('importaciones.detalle', imp_id=imp_id))

    ok, err = agregar_item(imp_id, producto_id, descripcion, cantidad, precio)
    if ok:
        flash("Producto agregado al pedido", "success")
    else:
        flash(f"Error: {err}", "error")
    return redirect(url_for('importaciones.detalle', imp_id=imp_id))


# ── Eliminar item ─────────────────────────────────────────────────────────────

@importaciones_bp.route('/importaciones/<int:imp_id>/items/<int:item_id>/eliminar',
                         methods=['POST'])
@login_required
@require_permiso('importaciones', 'editar')
def eliminar_item_route(imp_id, item_id):
    imp = get_importacion(imp_id)
    if not imp or imp['estado'] == 'cerrado':
        flash("No se puede modificar esta importación", "error")
        return redirect(url_for('importaciones.detalle', imp_id=imp_id))
    eliminar_item(item_id)
    flash("Producto eliminado del pedido", "success")
    return redirect(url_for('importaciones.detalle', imp_id=imp_id))


# ── Agregar gasto ─────────────────────────────────────────────────────────────

@importaciones_bp.route('/importaciones/<int:imp_id>/gastos/agregar', methods=['POST'])
@login_required
@require_permiso('importaciones', 'editar')
def agregar_gasto_route(imp_id):
    imp = get_importacion(imp_id)
    if not imp or imp['estado'] == 'cerrado':
        flash("No se puede modificar esta importación", "error")
        return redirect(url_for('importaciones.detalle', imp_id=imp_id))

    tipo        = request.form.get('tipo', '').strip()
    descripcion = request.form.get('descripcion', '').strip() or None
    monto_str   = request.form.get('monto', '0').replace(',', '.').strip()
    metodo_pago = request.form.get('metodo_pago', '').strip() or None

    try:
        monto = float(monto_str)
    except ValueError:
        flash("Monto inválido", "error")
        return redirect(url_for('importaciones.detalle', imp_id=imp_id))

    if monto <= 0:
        flash("El monto debe ser mayor a cero", "error")
        return redirect(url_for('importaciones.detalle', imp_id=imp_id))

    comprobante_nombre, comprobante_ruta = None, None
    file = request.files.get('comprobante')
    if file and file.filename:
        if not _allowed(file.filename):
            flash("Tipo de archivo no permitido (pdf, jpg, png, webp)", "error")
            return redirect(url_for('importaciones.detalle', imp_id=imp_id))
        comprobante_nombre, comprobante_ruta = _guardar_comprobante(file)

    ok, err = agregar_gasto_importacion(
        imp_id, tipo, descripcion, monto, metodo_pago,
        comprobante_nombre, comprobante_ruta,
        usuario_id=session.get('user_id')
    )
    if ok:
        flash("Gasto registrado y debitado de caja", "success")
    else:
        flash(f"Error: {err}", "error")
    return redirect(url_for('importaciones.detalle', imp_id=imp_id))


# ── Eliminar gasto ────────────────────────────────────────────────────────────

@importaciones_bp.route('/importaciones/<int:imp_id>/gastos/<int:gasto_id>/eliminar',
                         methods=['POST'])
@login_required
@require_permiso('importaciones', 'editar')
def eliminar_gasto_route(imp_id, gasto_id):
    imp = get_importacion(imp_id)
    if not imp or imp['estado'] == 'cerrado':
        flash("No se puede modificar esta importación", "error")
        return redirect(url_for('importaciones.detalle', imp_id=imp_id))
    eliminar_gasto_importacion(gasto_id)
    flash("Gasto eliminado", "success")
    return redirect(url_for('importaciones.detalle', imp_id=imp_id))


# ── Registrar pago al proveedor ───────────────────────────────────────────────

@importaciones_bp.route('/importaciones/<int:imp_id>/registrar-pago', methods=['POST'])
@login_required
@require_permiso('importaciones', 'editar')
def registrar_pago_route(imp_id):
    tc_str      = request.form.get('tipo_cambio', '').replace(',', '.').strip()
    fecha_pago  = request.form.get('fecha_pago', '').strip() or None
    metodo_pago = request.form.get('metodo_pago', '').strip() or None

    try:
        tipo_cambio = float(tc_str)
    except ValueError:
        flash("Tipo de cambio inválido", "error")
        return redirect(url_for('importaciones.detalle', imp_id=imp_id))

    ok, err = registrar_pago(imp_id, tipo_cambio, fecha_pago, metodo_pago,
                              usuario_id=session.get('user_id'))
    if ok:
        flash("Pago registrado y debitado de caja", "success")
    else:
        flash(f"Error: {err}", "error")
    return redirect(url_for('importaciones.detalle', imp_id=imp_id))


# ── Cambiar estado ────────────────────────────────────────────────────────────

@importaciones_bp.route('/importaciones/<int:imp_id>/cambiar-estado', methods=['POST'])
@login_required
@require_permiso('importaciones', 'editar')
def cambiar_estado_route(imp_id):
    nuevo_estado  = request.form.get('nuevo_estado', '').strip()
    fecha_llegada = request.form.get('fecha_llegada', '').strip() or None

    ok, err = cambiar_estado(imp_id, nuevo_estado, fecha_llegada)
    if ok:
        flash("Estado actualizado", "success")
    else:
        flash(f"Error: {err}", "error")
    return redirect(url_for('importaciones.detalle', imp_id=imp_id))


# ── Cerrar importación ────────────────────────────────────────────────────────

@importaciones_bp.route('/importaciones/<int:imp_id>/cerrar', methods=['POST'])
@login_required
@require_permiso('importaciones', 'cerrar')
def cerrar(imp_id):
    ok, err = cerrar_importacion(imp_id, usuario_id=session.get('user_id'))
    if ok:
        flash("Importación cerrada. Costos aplicados al inventario.", "success")
    else:
        flash(f"Error: {err}", "error")
    return redirect(url_for('importaciones.detalle', imp_id=imp_id))


# ── Descargar comprobante ─────────────────────────────────────────────────────

@importaciones_bp.route('/importaciones/gastos/<int:gasto_id>/comprobante')
@login_required
@require_permiso('importaciones', 'ver')
def descargar_comprobante(gasto_id):
    conn = get_conn()
    g = conn.execute(
        "SELECT * FROM importacion_gastos WHERE id = ?", (gasto_id,)
    ).fetchone()
    conn.close()
    if not g or not g['comprobante_ruta'] or not os.path.isfile(g['comprobante_ruta']):
        abort(404)
    return send_file(g['comprobante_ruta'], as_attachment=True,
                     download_name=g['comprobante_nombre'])


# ── CRUD Proveedores ──────────────────────────────────────────────────────────

@importaciones_bp.route('/importaciones/proveedores')
@login_required
@require_permiso('importaciones', 'ver')
def proveedores():
    lista_prov = listar_proveedores()
    return render_template('importaciones/proveedores.html', proveedores=lista_prov)


@importaciones_bp.route('/importaciones/proveedores/nuevo', methods=['POST'])
@login_required
@require_permiso('importaciones', 'crear')
def nuevo_proveedor():
    nombre   = request.form.get('nombre', '').strip()
    pais     = request.form.get('pais', '').strip() or None
    contacto = request.form.get('contacto', '').strip() or None
    telefono = request.form.get('telefono', '').strip() or None
    email    = request.form.get('email', '').strip() or None
    notas    = request.form.get('notas', '').strip() or None

    ok, result = crear_proveedor(nombre, pais, contacto, telefono, email, notas)
    if ok:
        flash(f"Proveedor '{nombre}' creado", "success")
    else:
        flash(f"Error: {result}", "error")
    return redirect(url_for('importaciones.proveedores'))


@importaciones_bp.route('/importaciones/proveedores/<int:prov_id>/editar', methods=['POST'])
@login_required
@require_permiso('importaciones', 'editar')
def editar_proveedor(prov_id):
    nombre   = request.form.get('nombre', '').strip()
    pais     = request.form.get('pais', '').strip() or None
    contacto = request.form.get('contacto', '').strip() or None
    telefono = request.form.get('telefono', '').strip() or None
    email    = request.form.get('email', '').strip() or None
    notas    = request.form.get('notas', '').strip() or None

    ok, err = actualizar_proveedor(prov_id, nombre, pais, contacto, telefono, email, notas)
    if ok:
        flash("Proveedor actualizado", "success")
    else:
        flash(f"Error: {err}", "error")
    return redirect(url_for('importaciones.proveedores'))


@importaciones_bp.route('/importaciones/proveedores/<int:prov_id>/eliminar', methods=['POST'])
@login_required
@require_permiso('importaciones', 'eliminar')
def eliminar_proveedor_route(prov_id):
    ok, err = eliminar_proveedor(prov_id)
    if ok:
        flash("Proveedor eliminado", "success")
    else:
        flash(f"Error: {err}", "error")
    return redirect(url_for('importaciones.proveedores'))
