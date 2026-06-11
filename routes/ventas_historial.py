# routes/ventas_historial.py
import os
import sqlite3
import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g
from models import get_conn
from routes import login_required, require_rol
from services.usuarios_service import registrar_auditoria

logger = logging.getLogger(__name__)

ventas_historial_bp = Blueprint('ventas_historial', __name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.path.join(BASE_DIR, 'negocio.db')

@ventas_historial_bp.route('/ventas_historial')
@login_required
def ventas_historial():
    page      = request.args.get('page', 1, type=int)
    search_id = request.args.get('id', '').strip()
    origen    = request.args.get('origen', '').strip()
    per_page  = 20
    conn = get_conn()
    if search_id:
        try:
            venta_id = int(search_id)
            ventas = conn.execute("""
                SELECT v.id, v.fecha, c.nombre, v.total, v.metodo_pago, v.cuotas, v.order_id,
                       v.estado
                FROM ventas v JOIN clientes c ON v.cliente_id = c.id
                WHERE v.id = ? ORDER BY v.fecha DESC
            """, (venta_id,)).fetchall()
            total       = len(ventas)
            total_pages = 1
            page        = 1
        except ValueError:
            flash("❌ El ID debe ser un número entero.", "error")
            ventas, total, total_pages = [], 0, 0
    else:
        if origen == 'tiendanube':
            where_origen = "WHERE v.metodo_pago = 'Tienda Nube'"
        elif origen == 'negocio':
            where_origen = "WHERE v.metodo_pago != 'Tienda Nube'"
        else:
            where_origen = ""
        total  = conn.execute(
            f"SELECT COUNT(*) FROM ventas v {where_origen}"
        ).fetchone()[0]
        offset = (page - 1) * per_page
        ventas = conn.execute(f"""
            SELECT v.id, v.fecha, c.nombre, v.total, v.metodo_pago, v.cuotas, v.order_id,
                   v.estado
            FROM ventas v JOIN clientes c ON v.cliente_id = c.id
            {where_origen}
            ORDER BY v.fecha DESC LIMIT ? OFFSET ?
        """, (per_page, offset)).fetchall()
        total_pages = (total + per_page - 1) // per_page
    conn.close()
    return render_template('ventas_historial.html', ventas=ventas, page=page,
                           total_pages=total_pages, total=total,
                           search_id=search_id, origen=origen)

@ventas_historial_bp.route('/venta/<int:venta_id>')
@login_required
def detalle_venta(venta_id):
    conn  = get_conn()
    venta = conn.execute("""
        SELECT v.id, v.fecha, c.nombre, v.total, v.metodo_pago, v.cuotas, v.order_id,
               v.estado, v.motivo_cancelacion, v.monto_recibido, v.vuelto
        FROM ventas v JOIN clientes c ON v.cliente_id = c.id
        WHERE v.id = ?
    """, (venta_id,)).fetchone()
    if not venta:
        conn.close()
        flash("❌ Venta no encontrada.", "error")
        return redirect(url_for('ventas_historial.ventas_historial'))
    productos = conn.execute("""
        SELECT p.descripcion, dv.cantidad, dv.precio_unitario
        FROM detalle_venta dv JOIN productos p ON dv.producto_id = p.id
        WHERE dv.venta_id = ?
    """, (venta_id,)).fetchall()
    conn.close()
    return render_template('detalle_venta.html', venta=venta, productos=productos)


@ventas_historial_bp.route('/venta/<int:venta_id>/cancelar', methods=['POST'])
@login_required
@require_rol(3)
def cancelar_venta(venta_id):
    motivo = request.form.get('motivo', '').strip()
    conn = get_conn()
    try:
        venta = conn.execute(
            "SELECT id, total, estado, metodo_pago FROM ventas WHERE id = ?", (venta_id,)
        ).fetchone()
        if not venta:
            flash("❌ Venta no encontrada.", "error")
            return redirect(url_for('ventas_historial.ventas_historial'))
        if venta['estado'] == 'cancelada':
            flash("⚠️ La venta ya está cancelada.", "warning")
            return redirect(url_for('ventas_historial.detalle_venta', venta_id=venta_id))

        items = conn.execute(
            "SELECT producto_id, cantidad FROM detalle_venta WHERE venta_id = ?", (venta_id,)
        ).fetchall()

        conn.execute(
            "UPDATE ventas SET estado = 'cancelada', motivo_cancelacion = ? WHERE id = ?",
            (motivo or None, venta_id)
        )
        for item in items:
            conn.execute(
                "UPDATE productos SET stock = stock + ? WHERE id = ?",
                (item['cantidad'], item['producto_id'])
            )

        # Registrar egreso en caja (misma transacción)
        from services.caja_service import registrar_movimiento_en_conn
        registrar_movimiento_en_conn(
            conn, 'egreso', 'cancelacion', venta_id,
            f"Cancelación Venta #{venta_id}",
            venta['total'], venta['metodo_pago'], g.user_id
        )
        conn.commit()

        registrar_auditoria(
            g.user_id, g.username,
            'cancelar_venta', 'ventas',
            detalle=f"Venta #{venta_id} cancelada. Total: ${venta['total']:.2f}."
                    + (f" Motivo: {motivo}" if motivo else ""),
            ip=request.remote_addr
        )
        flash(f"✅ Venta #{venta_id} cancelada y stock revertido.", "success")
    except Exception as e:
        conn.rollback()
        logger.exception("Error al cancelar venta #%s", venta_id)
        flash(f"❌ Error al cancelar la venta: {e}", "error")
    finally:
        conn.close()

    return redirect(url_for('ventas_historial.detalle_venta', venta_id=venta_id))