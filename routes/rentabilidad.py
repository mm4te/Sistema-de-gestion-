# routes/rentabilidad.py
from datetime import date

from flask import Blueprint, redirect, render_template, request, send_file, url_for

from routes import require_permiso
from services import rentabilidad_service as svc

rentabilidad_bp = Blueprint('rentabilidad', __name__)


def _defaults():
    hoy  = date.today()
    ini  = hoy.replace(day=1).isoformat()
    fin  = hoy.isoformat()
    return ini, fin


@rentabilidad_bp.route('/reportes/rentabilidad')
@require_permiso('resumen', 'ver')
def index():
    hoy = date.today()
    ini_default, fin_default = _defaults()

    fecha_desde = request.args.get('fecha_desde', ini_default).strip()
    fecha_hasta = request.args.get('fecha_hasta', fin_default).strip()
    origen      = request.args.get('origen', '').strip()

    try:
        data = svc.get_rentabilidad(fecha_desde, fecha_hasta, origen or None)
        evol = svc.get_evolucion_margen_12meses(hoy.year, hoy.month, origen or None)
    except Exception as e:
        data = None
        evol = []
        error_msg = str(e)
    else:
        error_msg = None

    return render_template(
        'rentabilidad/index.html',
        data=data,
        evol=evol,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        origen=origen,
        error_msg=error_msg,
    )


@rentabilidad_bp.route('/reportes/rentabilidad/excel')
@require_permiso('resumen', 'ver')
def excel():
    ini, fin = _defaults()
    fecha_desde = request.args.get('fecha_desde', ini).strip()
    fecha_hasta = request.args.get('fecha_hasta', fin).strip()
    origen      = request.args.get('origen', '').strip()

    buf      = svc.exportar_excel(fecha_desde, fecha_hasta, origen or None)
    filename = f"rentabilidad_{fecha_desde}_{fecha_hasta}.xlsx"
    return send_file(buf, as_attachment=True, download_name=filename,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@rentabilidad_bp.route('/reportes/rentabilidad/pdf')
@require_permiso('resumen', 'ver')
def pdf():
    ini, fin = _defaults()
    fecha_desde = request.args.get('fecha_desde', ini).strip()
    fecha_hasta = request.args.get('fecha_hasta', fin).strip()
    origen      = request.args.get('origen', '').strip()

    buf      = svc.exportar_pdf(fecha_desde, fecha_hasta, origen or None)
    filename = f"rentabilidad_{fecha_desde}_{fecha_hasta}.pdf"
    return send_file(buf, as_attachment=True, download_name=filename,
                     mimetype='application/pdf')
