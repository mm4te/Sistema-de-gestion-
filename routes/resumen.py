# routes/resumen.py
import json
from datetime import date

from flask import Blueprint, render_template, request, send_file

from routes import login_required, require_permiso
from services.resumen_service import (
    MESES_ES, exportar_excel, exportar_pdf,
    get_evolucion_12meses, get_resumen_mes,
)

resumen_bp = Blueprint('resumen', __name__)


@resumen_bp.route('/resumen')
@login_required
@require_permiso('resumen', 'ver')
def index():
    hoy   = date.today()
    year  = request.args.get('year',  hoy.year,  type=int)
    month = request.args.get('month', hoy.month, type=int)
    year  = max(2020, min(year, hoy.year + 1))
    month = max(1, min(month, 12))

    data = get_resumen_mes(year, month)
    evol = get_evolucion_12meses(year, month)

    evolucion_json  = json.dumps([
        {'label': e['label'], 'ingresos': e['ingresos'], 'gastos': e['gastos']}
        for e in evol
    ])
    categorias_json = json.dumps([
        {'nombre': c['categoria'], 'total': c['total']}
        for c in data['por_categoria']
    ])

    prev_year, prev_month = (year - 1, 12) if month == 1  else (year, month - 1)
    next_year, next_month = (year + 1,  1) if month == 12 else (year, month + 1)

    # No navegar al futuro
    es_futuro = (next_year, next_month) > (hoy.year, hoy.month)

    years = list(range(hoy.year - 4, hoy.year + 1))

    return render_template(
        'resumen/index.html',
        data=data,
        evolucion_json=evolucion_json,
        categorias_json=categorias_json,
        prev_year=prev_year,   prev_month=prev_month,
        next_year=next_year,   next_month=next_month,
        es_futuro=es_futuro,
        meses=MESES_ES,
        years=years,
        hoy=hoy,
    )


@resumen_bp.route('/resumen/excel')
@login_required
@require_permiso('resumen', 'ver')
def excel():
    hoy   = date.today()
    year  = request.args.get('year',  hoy.year,  type=int)
    month = request.args.get('month', hoy.month, type=int)
    buf   = exportar_excel(year, month)
    return send_file(buf, as_attachment=True,
                     download_name=f"resumen_{year}_{month:02d}.xlsx",
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@resumen_bp.route('/resumen/pdf')
@login_required
@require_permiso('resumen', 'ver')
def pdf():
    hoy   = date.today()
    year  = request.args.get('year',  hoy.year,  type=int)
    month = request.args.get('month', hoy.month, type=int)
    buf   = exportar_pdf(year, month)
    return send_file(buf, as_attachment=True,
                     download_name=f"resumen_{year}_{month:02d}.pdf",
                     mimetype='application/pdf')
