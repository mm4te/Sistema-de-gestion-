# routes/ventas_historial.py
import os
import sqlite3
import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g, send_file
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
                       v.estado, v.factura_emitida, v.nota_credito_emitida
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
                   v.estado, v.factura_emitida, v.nota_credito_emitida
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
               v.estado, v.motivo_cancelacion, v.monto_recibido, v.vuelto,
               v.cliente_id,
               v.factura_emitida, v.factura_tipo, v.factura_numero,
               v.factura_cae, v.factura_cae_vto, v.factura_pdf_path, v.factura_fecha,
               v.nota_credito_emitida, v.nota_credito_tipo, v.nota_credito_numero,
               v.nota_credito_cae, v.nota_credito_cae_vto, v.nota_credito_pdf_path,
               v.nota_credito_fecha, v.nota_credito_motivo
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

    # ── Fase 1: leer datos ────────────────────────────────────────────────────
    conn = get_conn()
    try:
        venta = conn.execute("""
            SELECT id, total, estado, metodo_pago, cliente_id,
                   factura_emitida, factura_tipo, factura_numero,
                   nota_credito_emitida
            FROM ventas WHERE id = ?
        """, (venta_id,)).fetchone()
        if not venta:
            flash("❌ Venta no encontrada.", "error")
            return redirect(url_for('ventas_historial.ventas_historial'))
        if venta['estado'] == 'cancelada':
            flash("⚠️ La venta ya está cancelada.", "warning")
            return redirect(url_for('ventas_historial.detalle_venta', venta_id=venta_id))

        items = conn.execute(
            "SELECT producto_id, cantidad FROM detalle_venta WHERE venta_id = ?",
            (venta_id,),
        ).fetchall()
        productos_pdf = conn.execute("""
            SELECT p.descripcion, dv.cantidad, dv.precio_unitario
            FROM detalle_venta dv JOIN productos p ON dv.producto_id = p.id
            WHERE dv.venta_id = ?
        """, (venta_id,)).fetchall()
        cliente = conn.execute(
            "SELECT * FROM clientes WHERE id = ?", (venta['cliente_id'],)
        ).fetchone()
    finally:
        conn.close()

    # ── Fase 2: emitir NC si la venta tiene factura sin NC ────────────────────
    nc_data     = None
    nc_pdf_path = None
    if venta['factura_emitida'] and not venta['nota_credito_emitida']:
        try:
            from services.afip_service import (
                emitir_nota_credito as _emitir_nc,
                generar_pdf_nota_credito,
            )
            nc_data = _emitir_nc(venta, cliente)
        except Exception as e:
            logger.exception("Error al emitir NC para venta #%s", venta_id)
            flash(
                f"❌ No se pudo emitir la Nota de Crédito. "
                f"La venta no puede cancelarse sin anular la factura. Error: {e}",
                "error",
            )
            return redirect(url_for('ventas_historial.detalle_venta', venta_id=venta_id))

        try:
            nc_pdf_path = generar_pdf_nota_credito(
                venta_id, venta, cliente, productos_pdf, nc_data
            )
        except Exception:
            logger.exception("Error generando PDF de NC venta #%s", venta_id)

    # ── Fase 3: transacción DB ────────────────────────────────────────────────
    conn = get_conn()
    try:
        update_sql    = "estado = 'cancelada', motivo_cancelacion = ?"
        update_params = [motivo or None]

        if nc_data:
            update_sql += (
                ", nota_credito_emitida=1, nota_credito_tipo=?,"
                " nota_credito_numero=?, nota_credito_cae=?,"
                " nota_credito_cae_vto=?, nota_credito_fecha=?,"
                " nota_credito_pdf_path=?, nota_credito_motivo=?"
            )
            update_params += [
                nc_data['tipo'], nc_data['numero'], nc_data['cae'],
                nc_data['cae_vto'], nc_data['fecha'], nc_pdf_path,
                motivo or None,
            ]

        update_params.append(venta_id)
        conn.execute(f"UPDATE ventas SET {update_sql} WHERE id = ?", update_params)

        for item in items:
            conn.execute(
                "UPDATE productos SET stock = stock + ? WHERE id = ?",
                (item['cantidad'], item['producto_id']),
            )

        from services.caja_service import registrar_movimiento_en_conn
        registrar_movimiento_en_conn(
            conn, 'egreso', 'cancelacion', venta_id,
            f"Cancelación Venta #{venta_id}",
            venta['total'], venta['metodo_pago'], g.user_id,
        )
        conn.commit()

        detalle_audit = (
            f"Venta #{venta_id} cancelada. Total: ${venta['total']:.2f}."
            + (f" Motivo: {motivo}" if motivo else "")
            + (f" NC emitida: {nc_data['tipo']} N° {nc_data['numero']:08d} CAE {nc_data['cae']}"
               if nc_data else "")
        )
        registrar_auditoria(
            g.user_id, g.username, 'cancelar_venta', 'ventas',
            detalle=detalle_audit, ip=request.remote_addr,
        )

        if nc_data:
            flash(
                f"✅ Venta #{venta_id} cancelada. "
                f"NC {nc_data['tipo']} N° {nc_data['numero']:08d} emitida. "
                f"CAE: {nc_data['cae']}",
                "success",
            )
        else:
            flash(f"✅ Venta #{venta_id} cancelada y stock revertido.", "success")

    except Exception as e:
        conn.rollback()
        logger.exception("Error al cancelar venta #%s", venta_id)
        if nc_data:
            flash(
                f"❌ NC emitida (CAE: {nc_data['cae']}) pero error al guardar en DB: {e}. "
                f"Guardá el CAE manualmente.",
                "error",
            )
        else:
            flash(f"❌ Error al cancelar la venta: {e}", "error")
    finally:
        conn.close()

    return redirect(url_for('ventas_historial.detalle_venta', venta_id=venta_id))


@ventas_historial_bp.route('/venta/<int:venta_id>/emitir-factura', methods=['POST'])
@login_required
def emitir_factura(venta_id):
    conn = get_conn()
    try:
        venta = conn.execute(
            "SELECT * FROM ventas WHERE id = ?", (venta_id,)
        ).fetchone()
        if not venta:
            flash("❌ Venta no encontrada.", "error")
            return redirect(url_for('ventas_historial.ventas_historial'))
        if venta['estado'] == 'cancelada':
            flash("❌ No se puede facturar una venta cancelada.", "error")
            return redirect(url_for('ventas_historial.detalle_venta', venta_id=venta_id))
        if venta['factura_emitida']:
            flash("⚠️ Esta venta ya tiene factura emitida.", "warning")
            return redirect(url_for('ventas_historial.detalle_venta', venta_id=venta_id))

        cliente = conn.execute(
            "SELECT * FROM clientes WHERE id = ?", (venta['cliente_id'],)
        ).fetchone()
        productos = conn.execute("""
            SELECT p.descripcion, dv.cantidad, dv.precio_unitario
            FROM detalle_venta dv JOIN productos p ON dv.producto_id = p.id
            WHERE dv.venta_id = ?
        """, (venta_id,)).fetchall()
    finally:
        conn.close()

    try:
        from services.afip_service import emitir_factura as _emitir, generar_pdf_factura
        factura_data = _emitir(venta, cliente, productos)
    except (ValueError, RuntimeError) as e:
        logger.exception("Error al emitir factura venta #%s", venta_id)
        flash(f"❌ {e}", "error")
        return redirect(url_for('ventas_historial.detalle_venta', venta_id=venta_id))
    except Exception as e:
        logger.exception("Error inesperado al emitir factura venta #%s", venta_id)
        flash(f"❌ Error al comunicarse con ARCA: {e}", "error")
        return redirect(url_for('ventas_historial.detalle_venta', venta_id=venta_id))

    # CAE obtenido — generar PDF (no bloquea si falla)
    pdf_path = None
    try:
        pdf_path = generar_pdf_factura(venta_id, venta, cliente, productos, factura_data)
    except Exception as e:
        logger.exception("Error generando PDF factura venta #%s", venta_id)

    # Persistir en DB
    conn = get_conn()
    try:
        conn.execute("""
            UPDATE ventas
            SET factura_emitida=1, factura_tipo=?, factura_numero=?,
                factura_cae=?, factura_cae_vto=?, factura_fecha=?, factura_pdf_path=?
            WHERE id=?
        """, (
            factura_data['tipo'],
            factura_data['numero'],
            factura_data['cae'],
            factura_data['cae_vto'],
            factura_data['fecha'],
            pdf_path,
            venta_id,
        ))
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.exception("Error guardando datos de factura venta #%s en DB", venta_id)
        flash(
            f"❌ CAE obtenido ({factura_data['cae']}) pero no se pudo guardar en BD: {e}",
            "error",
        )
        return redirect(url_for('ventas_historial.detalle_venta', venta_id=venta_id))
    finally:
        conn.close()

    registrar_auditoria(
        g.user_id, g.username,
        'emitir_factura', 'ventas',
        detalle=(f"Factura {factura_data['tipo']} N° {factura_data['numero']:08d} "
                 f"emitida para Venta #{venta_id}. CAE: {factura_data['cae']}"),
        ip=request.remote_addr,
    )
    flash(
        f"✅ Factura {factura_data['tipo']} N° {factura_data['numero']:08d} emitida. "
        f"CAE: {factura_data['cae']} (vto. {factura_data['cae_vto']})",
        "success",
    )
    return redirect(url_for('ventas_historial.detalle_venta', venta_id=venta_id))


@ventas_historial_bp.route('/venta/<int:venta_id>/factura-pdf')
@login_required
def descargar_factura_pdf(venta_id):
    conn = get_conn()
    row  = conn.execute(
        "SELECT factura_pdf_path, factura_tipo, factura_numero FROM ventas WHERE id = ?",
        (venta_id,)
    ).fetchone()
    conn.close()

    if not row or not row['factura_pdf_path']:
        flash("❌ PDF de factura no disponible.", "error")
        return redirect(url_for('ventas_historial.detalle_venta', venta_id=venta_id))

    abs_path = os.path.join(BASE_DIR, row['factura_pdf_path'])
    if not os.path.exists(abs_path):
        flash("❌ Archivo PDF no encontrado en el servidor.", "error")
        return redirect(url_for('ventas_historial.detalle_venta', venta_id=venta_id))

    tipo = row['factura_tipo'] or 'X'
    nro  = row['factura_numero'] or 0
    return send_file(
        abs_path,
        as_attachment=True,
        download_name=f"factura_{tipo}_{nro:08d}_venta{venta_id}.pdf",
        mimetype='application/pdf',
    )


@ventas_historial_bp.route('/venta/<int:venta_id>/emitir-nota-credito', methods=['POST'])
@login_required
def emitir_nota_credito(venta_id):
    conn = get_conn()
    try:
        venta = conn.execute("SELECT * FROM ventas WHERE id = ?", (venta_id,)).fetchone()
        if not venta:
            flash("❌ Venta no encontrada.", "error")
            return redirect(url_for('ventas_historial.ventas_historial'))
        if not venta['factura_emitida']:
            flash("❌ La venta no tiene factura emitida.", "error")
            return redirect(url_for('ventas_historial.detalle_venta', venta_id=venta_id))
        if venta['nota_credito_emitida']:
            flash("⚠️ Ya existe una Nota de Crédito para esta venta.", "warning")
            return redirect(url_for('ventas_historial.detalle_venta', venta_id=venta_id))

        cliente = conn.execute(
            "SELECT * FROM clientes WHERE id = ?", (venta['cliente_id'],)
        ).fetchone()
        productos = conn.execute("""
            SELECT p.descripcion, dv.cantidad, dv.precio_unitario
            FROM detalle_venta dv JOIN productos p ON dv.producto_id = p.id
            WHERE dv.venta_id = ?
        """, (venta_id,)).fetchall()
    finally:
        conn.close()

    try:
        from services.afip_service import (
            emitir_nota_credito as _emitir_nc,
            generar_pdf_nota_credito,
        )
        nc_data = _emitir_nc(venta, cliente)
    except (ValueError, RuntimeError) as e:
        logger.exception("Error al emitir NC venta #%s", venta_id)
        flash(f"❌ {e}", "error")
        return redirect(url_for('ventas_historial.detalle_venta', venta_id=venta_id))
    except Exception as e:
        logger.exception("Error inesperado al emitir NC venta #%s", venta_id)
        flash(f"❌ Error al comunicarse con ARCA: {e}", "error")
        return redirect(url_for('ventas_historial.detalle_venta', venta_id=venta_id))

    nc_pdf_path = None
    try:
        nc_pdf_path = generar_pdf_nota_credito(venta_id, venta, cliente, productos, nc_data)
    except Exception:
        logger.exception("Error generando PDF de NC venta #%s", venta_id)

    conn = get_conn()
    try:
        conn.execute("""
            UPDATE ventas
            SET nota_credito_emitida=1, nota_credito_tipo=?, nota_credito_numero=?,
                nota_credito_cae=?, nota_credito_cae_vto=?, nota_credito_fecha=?,
                nota_credito_pdf_path=?
            WHERE id=?
        """, (
            nc_data['tipo'], nc_data['numero'], nc_data['cae'],
            nc_data['cae_vto'], nc_data['fecha'], nc_pdf_path, venta_id,
        ))
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.exception("Error guardando NC venta #%s en DB", venta_id)
        flash(
            f"❌ NC emitida (CAE: {nc_data['cae']}) pero no se pudo guardar en BD: {e}. "
            f"Guardá el CAE manualmente.",
            "error",
        )
        return redirect(url_for('ventas_historial.detalle_venta', venta_id=venta_id))
    finally:
        conn.close()

    registrar_auditoria(
        g.user_id, g.username,
        'emitir_nota_credito', 'ventas',
        detalle=(f"NC {nc_data['tipo']} N° {nc_data['numero']:08d} "
                 f"emitida para Venta #{venta_id}. CAE: {nc_data['cae']}"),
        ip=request.remote_addr,
    )
    flash(
        f"✅ Nota de Crédito {nc_data['tipo']} N° {nc_data['numero']:08d} emitida. "
        f"CAE: {nc_data['cae']} (vto. {nc_data['cae_vto']})",
        "success",
    )
    return redirect(url_for('ventas_historial.detalle_venta', venta_id=venta_id))


@ventas_historial_bp.route('/venta/<int:venta_id>/nota-credito-pdf')
@login_required
def descargar_nc_pdf(venta_id):
    conn = get_conn()
    row  = conn.execute(
        "SELECT nota_credito_pdf_path, nota_credito_tipo, nota_credito_numero"
        " FROM ventas WHERE id = ?",
        (venta_id,),
    ).fetchone()
    conn.close()

    if not row or not row['nota_credito_pdf_path']:
        flash("❌ PDF de Nota de Crédito no disponible.", "error")
        return redirect(url_for('ventas_historial.detalle_venta', venta_id=venta_id))

    abs_path = os.path.join(BASE_DIR, row['nota_credito_pdf_path'])
    if not os.path.exists(abs_path):
        flash("❌ Archivo PDF no encontrado en el servidor.", "error")
        return redirect(url_for('ventas_historial.detalle_venta', venta_id=venta_id))

    tipo = row['nota_credito_tipo'] or 'X'
    nro  = row['nota_credito_numero'] or 0
    return send_file(
        abs_path,
        as_attachment=True,
        download_name=f"nota_credito_{tipo}_{nro:08d}_venta{venta_id}.pdf",
        mimetype='application/pdf',
    )