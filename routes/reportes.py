# routes/reportes.py
from flask import Blueprint, send_file
from models import get_ventas_historial
import pandas as pd
from datetime import datetime
import sqlite3

reportes_bp = Blueprint('reportes', __name__)

@reportes_bp.route('/reporte/excel')
def reporte_excel():
    conn = sqlite3.connect('negocio.db')
    mes_actual = datetime.now().strftime('%Y-%m')
    df = pd.read_sql_query("""
        SELECT v.fecha, c.nombre AS cliente, p.descripcion AS producto,
               dv.cantidad, dv.precio_unitario, (dv.cantidad * dv.precio_unitario) AS subtotal
        FROM ventas v
        JOIN detalle_venta dv ON v.id = dv.venta_id
        JOIN clientes c ON v.cliente_id = c.id
        JOIN productos p ON dv.producto_id = p.id
        WHERE strftime('%Y-%m', v.fecha) = ?
        ORDER BY v.fecha
    """, conn, params=(mes_actual,))
    hoy = datetime.now().strftime('%d-%m-%Y')
    output_path = f'reporte_ventas_{hoy}.xlsx'
    df.to_excel(output_path, index=False)
    conn.close()
    return send_file(output_path, as_attachment=True)