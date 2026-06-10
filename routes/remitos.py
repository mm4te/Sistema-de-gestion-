# routes/remitos.py
import json

from flask import (Blueprint, flash, redirect, render_template,
                   request, send_file, session, url_for)

from models import get_conn
from routes import login_required
from services.remito_service import (
    TRANSICIONES_VALIDAS,
    actualizar_remito,
    cambiar_estado,
    crear_remito,
    datos_desde_presupuesto,
    datos_desde_venta,
    eliminar_remito,
    generar_pdf,
    get_remito,
    listar_remitos,
)

remitos_bp = Blueprint('remitos', __name__)

ESTADOS = ['pendiente', 'en_transito', 'entregado', 'devuelto']


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_items(form):
    items = []
    descripciones = form.getlist('item_descripcion')
    cantidades    = form.getlist('item_cantidad')
    producto_ids  = form.getlist('item_producto_id')

    for i, desc in enumerate(descripciones):
        desc = desc.strip()
        if not desc:
            continue
        try:
            cantidad = float(cantidades[i])
            if cantidad <= 0:
                continue
            pid_raw = producto_ids[i] if i < len(producto_ids) else ''
            items.append({
                'descripcion': desc,
                'cantidad':    cantidad,
                'producto_id': int(pid_raw) if pid_raw and pid_raw.isdigit() else None,
            })
        except (ValueError, IndexError):
            continue
    return items


def _get_form_data():
    conn = get_conn()
    clientes  = conn.execute("SELECT id, nombre FROM clientes ORDER BY nombre").fetchall()
    productos = conn.execute(
        "SELECT id, sku, descripcion FROM productos WHERE activo = 1 ORDER BY descripcion"
    ).fetchall()
    conn.close()
    return clientes, productos


def _productos_json(productos):
    return json.dumps([{
        'id': p['id'], 'sku': p['sku'], 'descripcion': p['descripcion'],
    } for p in productos])


# ── Listado ──────────────────────────────────────────────────────────────────

@remitos_bp.route('/remitos')
@login_required
def lista():
    page   = request.args.get('page', 1, type=int)
    estado = request.args.get('estado', '')
    rows, total = listar_remitos(estado=estado or None, page=page, per_page=20)
    total_pages = (total + 19) // 20
    return render_template('remitos/lista.html',
                           remitos=rows, total=total,
                           page=page, total_pages=total_pages,
                           estado_filtro=estado, estados=ESTADOS)


# ── Nuevo ────────────────────────────────────────────────────────────────────

@remitos_bp.route('/remitos/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo():
    clientes, productos = _get_form_data()

    # Pre-compleción desde presupuesto o venta
    prefill = {}
    desde_presupuesto = request.args.get('desde_presupuesto', type=int)
    desde_venta       = request.args.get('desde_venta', type=int)
    if desde_presupuesto:
        prefill = datos_desde_presupuesto(desde_presupuesto) or {}
    elif desde_venta:
        prefill = datos_desde_venta(desde_venta) or {}

    if request.method == 'POST':
        cliente_id             = request.form.get('cliente_id', type=int)
        destinatario           = request.form.get('destinatario', '').strip()
        direccion              = request.form.get('direccion', '').strip()
        bultos                 = request.form.get('bultos', 1, type=int)
        peso                   = request.form.get('peso', type=float)
        fecha_entrega_estimada = request.form.get('fecha_entrega_estimada', '').strip() or None
        observaciones          = request.form.get('observaciones', '').strip() or None
        presupuesto_id         = request.form.get('presupuesto_id', type=int)
        venta_id               = request.form.get('venta_id', type=int)
        stock_descontado       = request.form.get('stock_descontado', 0, type=int)
        items                  = _parse_items(request.form)

        if not destinatario:
            flash("❌ El destinatario es obligatorio", "error")
        elif not direccion:
            flash("❌ La dirección de entrega es obligatoria", "error")
        elif not items:
            flash("❌ Agregá al menos un ítem", "error")
        else:
            ok, result = crear_remito(
                cliente_id=cliente_id,
                destinatario=destinatario,
                direccion=direccion,
                items=items,
                bultos=bultos,
                peso=peso,
                fecha_entrega_estimada=fecha_entrega_estimada,
                observaciones=observaciones,
                presupuesto_id=presupuesto_id,
                venta_id=venta_id,
                stock_descontado=stock_descontado,
                usuario_id=session.get('user_id'),
            )
            if ok:
                flash("✅ Remito creado correctamente", "success")
                return redirect(url_for('remitos.detalle', remito_id=result))
            flash(f"❌ {result}", "error")

    items_json = json.dumps(prefill.get('items', []))
    return render_template('remitos/form.html',
                           clientes=clientes,
                           productos=productos,
                           productos_json=_productos_json(productos),
                           remito=None,
                           prefill=prefill,
                           items_existentes=items_json,
                           titulo="Nuevo Remito")


# ── Detalle ──────────────────────────────────────────────────────────────────

@remitos_bp.route('/remitos/<int:remito_id>')
@login_required
def detalle(remito_id):
    r, items = get_remito(remito_id)
    if not r:
        flash("❌ Remito no encontrado", "error")
        return redirect(url_for('remitos.lista'))
    transiciones = TRANSICIONES_VALIDAS.get(r['estado'], ())
    return render_template('remitos/detalle.html',
                           r=r, items=items,
                           transiciones=transiciones)


# ── Editar ───────────────────────────────────────────────────────────────────

@remitos_bp.route('/remitos/<int:remito_id>/editar', methods=['GET', 'POST'])
@login_required
def editar(remito_id):
    r, items = get_remito(remito_id)
    if not r:
        flash("❌ Remito no encontrado", "error")
        return redirect(url_for('remitos.lista'))
    if r['estado'] != 'pendiente':
        flash("⚠️ Solo se pueden editar remitos en estado pendiente", "error")
        return redirect(url_for('remitos.detalle', remito_id=remito_id))

    clientes, productos = _get_form_data()

    if request.method == 'POST':
        cliente_id             = request.form.get('cliente_id', type=int)
        destinatario           = request.form.get('destinatario', '').strip()
        direccion              = request.form.get('direccion', '').strip()
        bultos                 = request.form.get('bultos', 1, type=int)
        peso                   = request.form.get('peso', type=float)
        fecha_entrega_estimada = request.form.get('fecha_entrega_estimada', '').strip() or None
        observaciones          = request.form.get('observaciones', '').strip() or None
        items_form             = _parse_items(request.form)

        if not destinatario:
            flash("❌ El destinatario es obligatorio", "error")
        elif not direccion:
            flash("❌ La dirección es obligatoria", "error")
        elif not items_form:
            flash("❌ Agregá al menos un ítem", "error")
        else:
            ok, result = actualizar_remito(
                remito_id, cliente_id, destinatario, direccion, items_form,
                bultos, peso, fecha_entrega_estimada, observaciones
            )
            if ok:
                flash("✅ Remito actualizado", "success")
                return redirect(url_for('remitos.detalle', remito_id=remito_id))
            flash(f"❌ {result}", "error")

    items_json = json.dumps([{
        'producto_id': it['producto_id'],
        'descripcion': it['descripcion'],
        'cantidad':    float(it['cantidad']),
    } for it in items])

    return render_template('remitos/form.html',
                           clientes=clientes,
                           productos=productos,
                           productos_json=_productos_json(productos),
                           remito=r,
                           prefill={},
                           items_existentes=items_json,
                           titulo="Editar Remito")


# ── Cambiar estado ───────────────────────────────────────────────────────────

@remitos_bp.route('/remitos/<int:remito_id>/cambiar_estado', methods=['POST'])
@login_required
def cambiar_estado_route(remito_id):
    nuevo_estado = request.form.get('estado', '').strip()
    recibido_por = request.form.get('recibido_por', '').strip() or None
    ok, result   = cambiar_estado(remito_id, nuevo_estado, recibido_por)
    if ok:
        flash(f"✅ Estado actualizado a '{nuevo_estado}'", "success")
    else:
        flash(f"❌ {result}", "error")
    return redirect(url_for('remitos.detalle', remito_id=remito_id))


# ── Eliminar ─────────────────────────────────────────────────────────────────

@remitos_bp.route('/remitos/<int:remito_id>/eliminar', methods=['POST'])
@login_required
def eliminar(remito_id):
    ok, msg = eliminar_remito(remito_id)
    if ok:
        flash("✅ Remito eliminado", "success")
        return redirect(url_for('remitos.lista'))
    flash(f"❌ {msg}", "error")
    return redirect(url_for('remitos.detalle', remito_id=remito_id))


# ── PDF ──────────────────────────────────────────────────────────────────────

@remitos_bp.route('/remitos/<int:remito_id>/pdf')
@login_required
def pdf(remito_id):
    buf = generar_pdf(remito_id)
    if not buf:
        flash("❌ No se pudo generar el PDF", "error")
        return redirect(url_for('remitos.detalle', remito_id=remito_id))
    r, _ = get_remito(remito_id)
    return send_file(buf, as_attachment=True,
                     download_name=f"remito_{r['numero']}.pdf",
                     mimetype='application/pdf')
