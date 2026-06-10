# routes/reportes.py
import io
from flask import Blueprint, send_file
from datetime import datetime
from routes import login_required
from models import get_conn
import pandas as pd

reportes_bp = Blueprint('reportes', __name__)


@reportes_bp.route('/reporte/excel')
@login_required
def reporte_excel():
    conn = get_conn()
    mes_actual = datetime.now().strftime('%Y-%m')
    df = pd.read_sql_query("""
        SELECT v.fecha, c.nombre AS cliente, p.descripcion AS producto,
               dv.cantidad, dv.precio_unitario,
               (dv.cantidad * dv.precio_unitario) AS subtotal
        FROM ventas v
        JOIN detalle_venta dv ON v.id = dv.venta_id
        JOIN clientes c ON v.cliente_id = c.id
        JOIN productos p ON dv.producto_id = p.id
        WHERE strftime('%Y-%m', v.fecha) = ?
        ORDER BY v.fecha
    """, conn, params=(mes_actual,))
    conn.close()

    output = io.BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    hoy = datetime.now().strftime('%d-%m-%Y')
    return send_file(
        output,
        as_attachment=True,
        download_name=f'reporte_ventas_{hoy}.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
