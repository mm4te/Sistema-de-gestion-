# routes/caja.py
from datetime import date

from flask import (Blueprint, flash, g, redirect, render_template,
                   request, send_file, url_for)

from routes import login_required, require_permiso
from services.caja_service import (
    METODOS_CAJA, ORIGENES_CAJA, TIPOS_CAJA,
    exportar_excel_caja, get_saldos,
    listar_movimientos, registrar_movimiento_manual,
)
from services.usuarios_service import registrar_auditoria

caja_bp = Blueprint('caja', __name__)


@caja_bp.route('/caja')
@login_required
@require_permiso('caja', 'ver')
def index():
    page        = request.args.get('page', 1, type=int)
    tipo        = request.args.get('tipo',        '').strip() or None
    origen      = request.args.get('origen',      '').strip() or None
    metodo_pago = request.args.get('metodo_pago', '').strip() or None
    fecha_desde = request.args.get('fecha_desde', '').strip() or None
    fecha_hasta = request.args.get('fecha_hasta', '').strip() or None
    per_page    = 30

    saldos = get_saldos(fecha_desde, fecha_hasta)
    movimientos, total = listar_movimientos(
        tipo, origen, metodo_pago, fecha_desde, fecha_hasta, page, per_page
    )
    total_pages = (total + per_page - 1) // per_page

    return render_template(
        'caja/index.html',
        saldos=saldos,
        movimientos=movimientos,
        total=total,
        page=page,
        total_pages=total_pages,
        tipo=tipo or '',
        origen=origen or '',
        metodo_pago=metodo_pago or '',
        fecha_desde=fecha_desde or '',
        fecha_hasta=fecha_hasta or '',
        metodos=METODOS_CAJA,
        origenes=ORIGENES_CAJA,
        tipos=TIPOS_CAJA,
        hoy=date.today().strftime('%Y-%m-%d'),
    )


@caja_bp.route('/caja/movimiento', methods=['POST'])
@login_required
@require_permiso('caja', 'crear')
def nuevo_movimiento():
    tipo        = request.form.get('tipo', '').strip()
    descripcion = request.form.get('descripcion', '').strip()
    monto_str   = request.form.get('monto', '0').replace(',', '.').strip()
    metodo_pago = request.form.get('metodo_pago', '').strip()
    fecha       = request.form.get('fecha', '').strip() or None

    if tipo not in ('ingreso', 'egreso'):
        flash("❌ Tipo inválido", "error")
        return redirect(url_for('caja.index'))
    if not descripcion:
        flash("❌ La descripción es obligatoria", "error")
        return redirect(url_for('caja.index'))
    try:
        monto = float(monto_str)
        if monto <= 0:
            raise ValueError
    except ValueError:
        flash("❌ Monto inválido (debe ser mayor a cero)", "error")
        return redirect(url_for('caja.index'))

    ok, result = registrar_movimiento_manual(
        tipo=tipo,
        descripcion=descripcion,
        monto=monto,
        metodo_pago=metodo_pago,
        creado_por=g.user_id,
        fecha=fecha,
    )
    if ok:
        registrar_auditoria(
            g.user_id, g.username,
            'movimiento_manual_caja', 'caja',
            detalle=f"{tipo.capitalize()} manual: {descripcion} — ${monto:.2f} ({metodo_pago or 'sin método'})",
            ip=request.remote_addr
        )
        flash("✅ Movimiento registrado correctamente", "success")
    else:
        flash(f"❌ Error: {result}", "error")
    return redirect(url_for('caja.index'))


@caja_bp.route('/caja/export')
@login_required
@require_permiso('caja', 'ver')
def export_excel():
    tipo        = request.args.get('tipo',        '').strip() or None
    origen      = request.args.get('origen',      '').strip() or None
    metodo_pago = request.args.get('metodo_pago', '').strip() or None
    fecha_desde = request.args.get('fecha_desde', '').strip() or None
    fecha_hasta = request.args.get('fecha_hasta', '').strip() or None

    buf = exportar_excel_caja(tipo, origen, metodo_pago, fecha_desde, fecha_hasta)
    return send_file(
        buf,
        as_attachment=True,
        download_name='movimientos_caja.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
