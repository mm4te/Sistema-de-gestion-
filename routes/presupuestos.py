# routes/presupuestos.py
import json
from datetime import date, timedelta

from flask import (Blueprint, flash, redirect, render_template,
                   request, send_file, session, url_for)

from models import get_conn
from routes import login_required
from services.presupuesto_service import (
    TRANSICIONES_VALIDAS,
    actualizar_presupuesto,
    cambiar_estado,
    convertir_a_venta,
    crear_presupuesto,
    eliminar_presupuesto,
    generar_pdf,
    get_presupuesto,
    listar_presupuestos,
    marcar_vencidos,
)

presupuestos_bp = Blueprint('presupuestos', __name__)

ESTADOS = ['borrador', 'enviado', 'aprobado', 'rechazado', 'vencido']


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_items(form):
    """Extrae y valida los ítems enviados como arrays paralelos en el formulario."""
    items = []
    descripciones     = form.getlist('item_descripcion')
    cantidades        = form.getlist('item_cantidad')
    precios           = form.getlist('item_precio_unitario')
    producto_ids      = form.getlist('item_producto_id')

    for i, desc in enumerate(descripciones):
        desc = desc.strip()
        if not desc:
            continue
        try:
            cantidad = float(cantidades[i])
            precio   = float(precios[i])
            if cantidad <= 0 or precio < 0:
                continue
            pid_raw = producto_ids[i] if i < len(producto_ids) else ''
            items.append({
                'descripcion':     desc,
                'cantidad':        cantidad,
                'precio_unitario': precio,
                'producto_id':     int(pid_raw) if pid_raw and pid_raw.isdigit() else None,
            })
        except (ValueError, IndexError):
            continue
    return items


def _productos_json(productos):
    return json.dumps([{
        'id':          p['id'],
        'sku':         p['sku'],
        'descripcion': p['descripcion'],
        'precio':      float(p['precio']),
    } for p in productos])


def _get_form_data():
    """Carga clientes y productos activos para los formularios."""
    conn = get_conn()
    clientes  = conn.execute("SELECT id, nombre FROM clientes ORDER BY nombre").fetchall()
    productos = conn.execute(
        "SELECT id, sku, descripcion, precio FROM productos WHERE activo = 1 ORDER BY descripcion"
    ).fetchall()
    conn.close()
    return clientes, productos


# ── Listado ──────────────────────────────────────────────────────────────────

@presupuestos_bp.route('/presupuestos')
@login_required
def lista():
    marcar_vencidos()
    page   = request.args.get('page', 1, type=int)
    estado = request.args.get('estado', '')

    presupuestos, total = listar_presupuestos(
        estado=estado or None, page=page, per_page=20
    )
    total_pages = (total + 19) // 20
    return render_template('presupuestos/lista.html',
                           presupuestos=presupuestos, total=total,
                           page=page, total_pages=total_pages,
                           estado_filtro=estado, estados=ESTADOS)


# ── Nuevo ────────────────────────────────────────────────────────────────────

@presupuestos_bp.route('/presupuestos/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo():
    clientes, productos = _get_form_data()

    if request.method == 'POST':
        cliente_id   = request.form.get('cliente_id', type=int)
        fecha_validez= request.form.get('fecha_validez', '').strip()
        observaciones= request.form.get('observaciones', '').strip()
        items        = _parse_items(request.form)

        if not cliente_id:
            flash("❌ Seleccioná un cliente", "error")
        elif not fecha_validez:
            flash("❌ La fecha de validez es obligatoria", "error")
        elif not items:
            flash("❌ Agregá al menos un ítem al presupuesto", "error")
        else:
            ok, result = crear_presupuesto(
                cliente_id, fecha_validez, items,
                observaciones, session.get('user_id')
            )
            if ok:
                flash("✅ Presupuesto creado correctamente", "success")
                return redirect(url_for('presupuestos.detalle', presupuesto_id=result))
            flash(f"❌ {result}", "error")

    fecha_validez_default = (date.today() + timedelta(days=30)).isoformat()
    return render_template('presupuestos/form.html',
                           clientes=clientes,
                           productos=productos,
                           productos_json=_productos_json(productos),
                           presupuesto=None,
                           items_existentes='[]',
                           fecha_validez_default=fecha_validez_default,
                           titulo="Nuevo Presupuesto")


# ── Detalle ──────────────────────────────────────────────────────────────────

@presupuestos_bp.route('/presupuestos/<int:presupuesto_id>')
@login_required
def detalle(presupuesto_id):
    p, items, historial = get_presupuesto(presupuesto_id)
    if not p:
        flash("❌ Presupuesto no encontrado", "error")
        return redirect(url_for('presupuestos.lista'))

    transiciones = TRANSICIONES_VALIDAS.get(p['estado'], ())
    return render_template('presupuestos/detalle.html',
                           p=p, items=items, historial=historial,
                           transiciones=transiciones, estados=ESTADOS)


# ── Editar ───────────────────────────────────────────────────────────────────

@presupuestos_bp.route('/presupuestos/<int:presupuesto_id>/editar', methods=['GET', 'POST'])
@login_required
def editar(presupuesto_id):
    p, items, _ = get_presupuesto(presupuesto_id)
    if not p:
        flash("❌ Presupuesto no encontrado", "error")
        return redirect(url_for('presupuestos.lista'))
    if p['estado'] != 'borrador':
        flash("⚠️ Solo se pueden editar presupuestos en borrador", "error")
        return redirect(url_for('presupuestos.detalle', presupuesto_id=presupuesto_id))

    clientes, productos = _get_form_data()

    if request.method == 'POST':
        cliente_id    = request.form.get('cliente_id', type=int)
        fecha_validez = request.form.get('fecha_validez', '').strip()
        observaciones = request.form.get('observaciones', '').strip()
        items_form    = _parse_items(request.form)

        if not cliente_id:
            flash("❌ Seleccioná un cliente", "error")
        elif not fecha_validez:
            flash("❌ La fecha de validez es obligatoria", "error")
        elif not items_form:
            flash("❌ Agregá al menos un ítem al presupuesto", "error")
        else:
            ok, result = actualizar_presupuesto(
                presupuesto_id, cliente_id, fecha_validez, items_form, observaciones
            )
            if ok:
                flash("✅ Presupuesto actualizado", "success")
                return redirect(url_for('presupuestos.detalle', presupuesto_id=presupuesto_id))
            flash(f"❌ {result}", "error")

    items_json = json.dumps([{
        'producto_id':     item['producto_id'],
        'descripcion':     item['descripcion'],
        'cantidad':        float(item['cantidad']),
        'precio_unitario': float(item['precio_unitario']),
    } for item in items])

    return render_template('presupuestos/form.html',
                           clientes=clientes,
                           productos=productos,
                           productos_json=_productos_json(productos),
                           presupuesto=p,
                           items_existentes=items_json,
                           fecha_validez_default=p['fecha_validez'],
                           titulo="Editar Presupuesto")


# ── Cambiar estado ───────────────────────────────────────────────────────────

@presupuestos_bp.route('/presupuestos/<int:presupuesto_id>/cambiar_estado', methods=['POST'])
@login_required
def cambiar_estado_route(presupuesto_id):
    nuevo_estado = request.form.get('estado', '').strip()
    nota         = request.form.get('nota', '').strip() or None
    ok, result   = cambiar_estado(presupuesto_id, nuevo_estado,
                                  session.get('user_id'), nota)
    if ok:
        flash(f"✅ Estado actualizado a '{nuevo_estado}'", "success")
    else:
        flash(f"❌ {result}", "error")
    return redirect(url_for('presupuestos.detalle', presupuesto_id=presupuesto_id))


# ── Eliminar ─────────────────────────────────────────────────────────────────

@presupuestos_bp.route('/presupuestos/<int:presupuesto_id>/eliminar', methods=['POST'])
@login_required
def eliminar(presupuesto_id):
    ok, msg = eliminar_presupuesto(presupuesto_id)
    if ok:
        flash("✅ Presupuesto eliminado", "success")
        return redirect(url_for('presupuestos.lista'))
    flash(f"❌ {msg}", "error")
    return redirect(url_for('presupuestos.detalle', presupuesto_id=presupuesto_id))


# ── PDF ──────────────────────────────────────────────────────────────────────

@presupuestos_bp.route('/presupuestos/<int:presupuesto_id>/pdf')
@login_required
def pdf(presupuesto_id):
    buf = generar_pdf(presupuesto_id)
    if not buf:
        flash("❌ No se pudo generar el PDF", "error")
        return redirect(url_for('presupuestos.detalle', presupuesto_id=presupuesto_id))
    p, _, _ = get_presupuesto(presupuesto_id)
    return send_file(buf, as_attachment=True,
                     download_name=f"presupuesto_{p['numero']}.pdf",
                     mimetype='application/pdf')


# ── Convertir a venta ────────────────────────────────────────────────────────

@presupuestos_bp.route('/presupuestos/<int:presupuesto_id>/convertir_venta', methods=['POST'])
@login_required
def convertir_venta(presupuesto_id):
    metodo_pago = request.form.get('metodo_pago')
    cuotas      = request.form.get('cuotas', type=int)

    if metodo_pago not in ('efectivo', 'transferencia', 'tarjeta'):
        flash("❌ Método de pago inválido", "error")
        return redirect(url_for('presupuestos.detalle', presupuesto_id=presupuesto_id))
    if metodo_pago == 'tarjeta' and cuotas not in (2, 3, 6):
        flash("❌ Cuotas inválidas", "error")
        return redirect(url_for('presupuestos.detalle', presupuesto_id=presupuesto_id))
    if metodo_pago != 'tarjeta':
        cuotas = None

    ok, result = convertir_a_venta(presupuesto_id, metodo_pago, cuotas)
    if ok:
        flash(f"✅ Venta #{result} creada exitosamente", "success")
        return redirect(url_for('ventas_historial.detalle_venta', venta_id=result))
    flash(f"❌ {result}", "error")
    return redirect(url_for('presupuestos.detalle', presupuesto_id=presupuesto_id))
