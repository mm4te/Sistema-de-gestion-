# services/remito_service.py
import io
import logging
from datetime import datetime

from models import get_conn
from services.tiendanube_service import actualizar_stock_tn_service

logger = logging.getLogger(__name__)

ESTADOS_VALIDOS = ('pendiente', 'en_transito', 'entregado', 'devuelto')

TRANSICIONES_VALIDAS = {
    'pendiente':   ('en_transito', 'entregado', 'devuelto'),
    'en_transito': ('entregado', 'devuelto'),
    'entregado':   (),
    'devuelto':    ('pendiente',),
}


# ── Número correlativo ───────────────────────────────────────────────────────

def _siguiente_numero(cursor):
    año = datetime.now().year
    cursor.execute(
        "SELECT numero FROM remitos WHERE numero LIKE ? ORDER BY numero DESC LIMIT 1",
        (f"REM-{año}-%",)
    )
    ultimo = cursor.fetchone()
    n = (int(ultimo['numero'].split('-')[-1]) + 1) if ultimo else 1
    return f"REM-{año}-{n:05d}"


# ── Cargar datos de origen para precompletar ─────────────────────────────────

def datos_desde_presupuesto(presupuesto_id):
    """Devuelve dict con datos para precompletar el form desde un presupuesto."""
    conn = get_conn()
    p = conn.execute("""
        SELECT p.*, c.nombre AS cliente_nombre
        FROM presupuestos p JOIN clientes c ON p.cliente_id = c.id
        WHERE p.id = ?
    """, (presupuesto_id,)).fetchone()
    if not p:
        conn.close()
        return None
    items = conn.execute(
        "SELECT descripcion, cantidad, producto_id FROM presupuesto_items WHERE presupuesto_id = ?",
        (presupuesto_id,)
    ).fetchall()
    conn.close()
    return {
        'cliente_id':    p['cliente_id'],
        'destinatario':  p['cliente_nombre'],
        'presupuesto_id': presupuesto_id,
        'items':         [dict(i) for i in items],
    }


def datos_desde_venta(venta_id):
    """Devuelve dict con datos para precompletar el form desde una venta."""
    conn = get_conn()
    v = conn.execute("""
        SELECT v.*, c.nombre AS cliente_nombre
        FROM ventas v JOIN clientes c ON v.cliente_id = c.id
        WHERE v.id = ?
    """, (venta_id,)).fetchone()
    if not v:
        conn.close()
        return None
    items = conn.execute("""
        SELECT p.descripcion, dv.cantidad, dv.producto_id
        FROM detalle_venta dv JOIN productos p ON dv.producto_id = p.id
        WHERE dv.venta_id = ?
    """, (venta_id,)).fetchall()
    conn.close()
    return {
        'cliente_id':       v['cliente_id'],
        'destinatario':     v['cliente_nombre'],
        'venta_id':         venta_id,
        'stock_descontado': 1,  # la venta ya descontó stock
        'items':            [dict(i) for i in items],
    }


# ── Listado ──────────────────────────────────────────────────────────────────

def listar_remitos(estado=None, page=1, per_page=20):
    conn = get_conn()
    conds, params = [], []
    if estado:
        conds.append("r.estado = ?")
        params.append(estado)
    where = ("WHERE " + " AND ".join(conds)) if conds else ""

    total = conn.execute(
        f"SELECT COUNT(*) FROM remitos r {where}", params
    ).fetchone()[0]

    offset = (page - 1) * per_page
    rows = conn.execute(f"""
        SELECT r.*,
               c.nombre  AS cliente_nombre,
               p.numero  AS presupuesto_numero,
               v.id      AS venta_numero
        FROM remitos r
        LEFT JOIN clientes     c ON r.cliente_id      = c.id
        LEFT JOIN presupuestos p ON r.presupuesto_id  = p.id
        LEFT JOIN ventas        v ON r.venta_id        = v.id
        {where}
        ORDER BY r.id DESC
        LIMIT ? OFFSET ?
    """, (*params, per_page, offset)).fetchall()

    conn.close()
    return rows, total


# ── Detalle ──────────────────────────────────────────────────────────────────

def get_remito(remito_id):
    conn = get_conn()
    r = conn.execute("""
        SELECT r.*,
               c.nombre  AS cliente_nombre,
               p.numero  AS presupuesto_numero,
               v.id      AS venta_numero
        FROM remitos r
        LEFT JOIN clientes     c ON r.cliente_id      = c.id
        LEFT JOIN presupuestos p ON r.presupuesto_id  = p.id
        LEFT JOIN ventas        v ON r.venta_id        = v.id
        WHERE r.id = ?
    """, (remito_id,)).fetchone()

    if not r:
        conn.close()
        return None, []

    items = conn.execute("""
        SELECT ri.*, pr.sku
        FROM remito_items ri
        LEFT JOIN productos pr ON ri.producto_id = pr.id
        WHERE ri.remito_id = ?
        ORDER BY ri.id
    """, (remito_id,)).fetchall()

    conn.close()
    return r, items


# ── Crear ────────────────────────────────────────────────────────────────────

def crear_remito(cliente_id, destinatario, direccion, items,
                 bultos=1, peso=None, fecha_entrega_estimada=None,
                 observaciones=None, presupuesto_id=None, venta_id=None,
                 stock_descontado=0, usuario_id=None,
                 retira_nombre=None, retira_dni=None, retiro_observaciones=None):
    if not items:
        return False, "El remito debe tener al menos un ítem"
    if not destinatario or not direccion:
        return False, "Destinatario y dirección son obligatorios"

    conn = get_conn()
    try:
        cursor = conn.cursor()
        numero = _siguiente_numero(cursor)
        fecha  = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        cursor.execute("""
            INSERT INTO remitos
                (numero, cliente_id, presupuesto_id, venta_id,
                 destinatario, direccion, bultos, peso,
                 estado, fecha, fecha_entrega_estimada,
                 observaciones, stock_descontado, creado_por,
                 retira_nombre, retira_dni, retiro_observaciones)
            VALUES (?,?,?,?,?,?,?,?,'pendiente',?,?,?,?,?,?,?,?)
        """, (numero, cliente_id or None, presupuesto_id or None, venta_id or None,
              destinatario, direccion, bultos, peso,
              fecha, fecha_entrega_estimada or None,
              observaciones or None, stock_descontado, usuario_id,
              retira_nombre or None, retira_dni or None, retiro_observaciones or None))

        remito_id = cursor.lastrowid

        for item in items:
            cursor.execute("""
                INSERT INTO remito_items (remito_id, producto_id, descripcion, cantidad)
                VALUES (?, ?, ?, ?)
            """, (remito_id,
                  item.get('producto_id') or None,
                  item['descripcion'],
                  float(item['cantidad'])))

        conn.commit()
        logger.info("Remito %s creado (id=%s)", numero, remito_id)
        return True, remito_id

    except Exception as e:
        conn.rollback()
        logger.exception("Error creando remito")
        return False, str(e)
    finally:
        conn.close()


# ── Actualizar ───────────────────────────────────────────────────────────────

def actualizar_remito(remito_id, cliente_id, destinatario, direccion, items,
                      bultos=1, peso=None, fecha_entrega_estimada=None,
                      observaciones=None,
                      retira_nombre=None, retira_dni=None, retiro_observaciones=None):
    if not items:
        return False, "El remito debe tener al menos un ítem"

    conn = get_conn()
    try:
        r = conn.execute(
            "SELECT estado FROM remitos WHERE id = ?", (remito_id,)
        ).fetchone()
        if not r:
            return False, "Remito no encontrado"
        if r['estado'] != 'pendiente':
            return False, "Solo se pueden editar remitos en estado pendiente"

        conn.execute("""
            UPDATE remitos
            SET cliente_id=?, destinatario=?, direccion=?,
                bultos=?, peso=?, fecha_entrega_estimada=?, observaciones=?,
                retira_nombre=?, retira_dni=?, retiro_observaciones=?
            WHERE id=?
        """, (cliente_id or None, destinatario, direccion,
              bultos, peso, fecha_entrega_estimada or None,
              observaciones or None,
              retira_nombre or None, retira_dni or None, retiro_observaciones or None,
              remito_id))

        conn.execute("DELETE FROM remito_items WHERE remito_id = ?", (remito_id,))
        for item in items:
            conn.execute("""
                INSERT INTO remito_items (remito_id, producto_id, descripcion, cantidad)
                VALUES (?, ?, ?, ?)
            """, (remito_id,
                  item.get('producto_id') or None,
                  item['descripcion'],
                  float(item['cantidad'])))

        conn.commit()
        return True, remito_id

    except Exception as e:
        conn.rollback()
        logger.exception("Error actualizando remito %s", remito_id)
        return False, str(e)
    finally:
        conn.close()


# ── Cambio de estado ─────────────────────────────────────────────────────────

def cambiar_estado(remito_id, nuevo_estado, recibido_por=None):
    if nuevo_estado not in ESTADOS_VALIDOS:
        return False, f"Estado inválido: {nuevo_estado}"

    conn = get_conn()
    try:
        r = conn.execute(
            "SELECT estado, stock_descontado, venta_id FROM remitos WHERE id = ?",
            (remito_id,)
        ).fetchone()
        if not r:
            return False, "Remito no encontrado"

        estado_actual = r['estado']
        if nuevo_estado not in TRANSICIONES_VALIDAS.get(estado_actual, ()):
            return False, f"No se puede pasar de '{estado_actual}' a '{nuevo_estado}'"

        ahora = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        update_fields = "estado = ?"
        params = [nuevo_estado]

        if nuevo_estado == 'entregado':
            update_fields += ", fecha_entrega_real = ?"
            params.append(ahora)
            if recibido_por:
                update_fields += ", recibido_por = ?"
                params.append(recibido_por)

        params.append(remito_id)
        conn.execute(f"UPDATE remitos SET {update_fields} WHERE id = ?", params)

        # ── Descontar stock si el remito es independiente (sin venta origen) ──
        if nuevo_estado == 'entregado' and not r['stock_descontado'] and not r['venta_id']:
            items = conn.execute(
                "SELECT producto_id, cantidad FROM remito_items WHERE remito_id = ? AND producto_id IS NOT NULL",
                (remito_id,)
            ).fetchall()
            for item in items:
                conn.execute(
                    "UPDATE productos SET stock = MAX(0, stock - ?) WHERE id = ?",
                    (int(item['cantidad']), item['producto_id'])
                )
                # Obtener nuevo stock y variant_id para sincronizar con TN
                prod = conn.execute(
                    "SELECT stock, variant_id FROM productos WHERE id = ?",
                    (item['producto_id'],)
                ).fetchone()
                if prod and prod['variant_id']:
                    try:
                        actualizar_stock_tn_service(prod['variant_id'], prod['stock'])
                    except Exception:
                        logger.warning("No se pudo sincronizar stock TN para producto %s",
                                       item['producto_id'])

            conn.execute(
                "UPDATE remitos SET stock_descontado = 1 WHERE id = ?", (remito_id,)
            )

        conn.commit()
        logger.info("Remito %s: %s -> %s", remito_id, estado_actual, nuevo_estado)
        return True, nuevo_estado

    except Exception as e:
        conn.rollback()
        logger.exception("Error cambiando estado remito %s", remito_id)
        return False, str(e)
    finally:
        conn.close()


# ── Eliminar ─────────────────────────────────────────────────────────────────

def eliminar_remito(remito_id):
    conn = get_conn()
    try:
        r = conn.execute(
            "SELECT estado FROM remitos WHERE id = ?", (remito_id,)
        ).fetchone()
        if not r:
            return False, "Remito no encontrado"
        if r['estado'] != 'pendiente':
            return False, "Solo se pueden eliminar remitos en estado pendiente"

        conn.execute("DELETE FROM remito_items WHERE remito_id = ?", (remito_id,))
        conn.execute("DELETE FROM remitos WHERE id = ?", (remito_id,))
        conn.commit()
        return True, "Eliminado"

    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


# ── Generación de PDF ────────────────────────────────────────────────────────

def generar_pdf(remito_id):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle,
        Paragraph, Spacer, HRFlowable
    )

    r, items = get_remito(remito_id)
    if not r:
        return None

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            title=f"Remito {r['numero']}",
                            rightMargin=2*cm, leftMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    styles  = getSampleStyleSheet()
    story   = []

    PRIMARY = colors.HexColor('#4361ee')
    LIGHT   = colors.HexColor('#f1f3f9')
    BORDER  = colors.HexColor('#dee2e6')
    ALT_ROW = colors.HexColor('#f8f9fa')

    right_style  = ParagraphStyle('right',  parent=styles['Normal'], alignment=TA_RIGHT)
    center_style = ParagraphStyle('center', parent=styles['Normal'], alignment=TA_CENTER)
    small_gray   = ParagraphStyle('small',  parent=styles['Normal'],
                                  fontSize=8, textColor=colors.HexColor('#6c757d'),
                                  alignment=TA_CENTER)

    # ── Cabecera ──────────────────────────────────────────────────────────
    hdr = Table([[
        Paragraph("<b><font size='18' color='#4361ee'>COMENDA DECO</font></b>",
                  styles['Normal']),
        Paragraph(
            f"<b><font size='14'>REMITO</font></b><br/>"
            f"<font size='11'>N° {r['numero']}</font>",
            right_style
        )
    ]], colWidths=[10*cm, 7*cm])
    hdr.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
    ]))
    story += [hdr, HRFlowable(width="100%", thickness=2, color=PRIMARY), Spacer(1, .4*cm)]

    # ── Info general ──────────────────────────────────────────────────────
    fecha_str    = (r['fecha'] or '')[:10]
    est_str      = r['fecha_entrega_estimada'] or '—'
    estado_label = r['estado'].upper().replace('_', ' ')

    info = Table([[
        Paragraph(f"<b>Fecha:</b> {fecha_str}", styles['Normal']),
        Paragraph(f"<b>Entrega estimada:</b> {est_str}", styles['Normal']),
        Paragraph(f"<b>Estado:</b> {estado_label}", styles['Normal']),
    ]], colWidths=[6*cm, 6*cm, 5*cm])
    info.setStyle(TableStyle([('BOTTOMPADDING', (0,0), (-1,-1), 8)]))
    story += [info, Spacer(1, .3*cm)]

    # ── Origen ────────────────────────────────────────────────────────────
    if r['presupuesto_numero'] or r['venta_numero']:
        origen = []
        if r['presupuesto_numero']:
            origen.append(f"Presupuesto: {r['presupuesto_numero']}")
        if r['venta_numero']:
            origen.append(f"Venta: #{r['venta_numero']}")
        story.append(Paragraph(" · ".join(origen),
                                ParagraphStyle('orig', parent=styles['Normal'],
                                               textColor=colors.HexColor('#6c757d'),
                                               fontSize=9)))
        story.append(Spacer(1, .2*cm))

    # ── Destinatario ──────────────────────────────────────────────────────
    story.append(Paragraph("<b>DESTINATARIO</b>",
                           ParagraphStyle('hdr', parent=styles['Normal'],
                                          backColor=LIGHT, leftPadding=6, fontSize=10)))
    story.append(Spacer(1, .2*cm))

    dest_txt = f"<b>{r['destinatario']}</b>"
    if r['cliente_nombre'] and r['cliente_nombre'] != r['destinatario']:
        dest_txt += f" ({r['cliente_nombre']})"
    story.append(Paragraph(dest_txt, styles['Normal']))
    story.append(Paragraph(f"<b>Dirección:</b> {r['direccion']}", styles['Normal']))
    story.append(Spacer(1, .4*cm))

    # ── Logística ─────────────────────────────────────────────────────────
    log_data = [[
        Paragraph(f"<b>Bultos:</b> {r['bultos'] or 1}", styles['Normal']),
        Paragraph(f"<b>Peso:</b> {r['peso'] if r['peso'] else '—'} kg", styles['Normal']),
    ]]
    log_tbl = Table(log_data, colWidths=[8.5*cm, 8.5*cm])
    story += [log_tbl, Spacer(1, .4*cm)]

    # ── Ítems ────────────────────────────────────────────────────────────
    story.append(Paragraph("<b>ARTÍCULOS A ENTREGAR</b>",
                           ParagraphStyle('hdr', parent=styles['Normal'],
                                          backColor=LIGHT, leftPadding=6, fontSize=10)))
    story.append(Spacer(1, .2*cm))

    tbl_data = [['#', 'Descripción', 'Cantidad']]
    for i, it in enumerate(items, 1):
        tbl_data.append([str(i), it['descripcion'], f"{float(it['cantidad']):.0f}"])

    tbl = Table(tbl_data, colWidths=[1*cm, 14*cm, 2*cm])
    tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,0),  PRIMARY),
        ('TEXTCOLOR',     (0,0), (-1,0),  colors.white),
        ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
        ('FONTSIZE',      (0,0), (-1,-1), 9),
        ('ROWBACKGROUNDS',(0,1), (-1,-1), [colors.white, ALT_ROW]),
        ('GRID',          (0,0), (-1,-1), 0.5, BORDER),
        ('ALIGN',         (2,0), (-1,-1), 'CENTER'),
        ('TOPPADDING',    (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    story += [tbl, Spacer(1, .4*cm)]

    # ── Observaciones ─────────────────────────────────────────────────────
    if r['observaciones']:
        story.append(Paragraph("<b>OBSERVACIONES</b>",
                               ParagraphStyle('hdr', parent=styles['Normal'],
                                              backColor=LIGHT, leftPadding=6, fontSize=10)))
        story += [Spacer(1, .2*cm),
                  Paragraph(r['observaciones'], styles['Normal']),
                  Spacer(1, .4*cm)]

    # ── Área de firma ─────────────────────────────────────────────────────
    story.append(Spacer(1, 1*cm))
    story.append(HRFlowable(width="100%", thickness=1, color=BORDER))
    story.append(Spacer(1, .3*cm))

    if r['recibido_por']:
        firma_txt = f"<b>Recibido por:</b> {r['recibido_por']}"
        if r['fecha_entrega_real']:
            firma_txt += f"&nbsp;&nbsp;&nbsp;<b>Fecha:</b> {r['fecha_entrega_real'][:10]}"
        story.append(Paragraph(firma_txt, styles['Normal']))
    else:
        firma = Table([[
            Paragraph("Firma y aclaración del receptor:", styles['Normal']),
            Paragraph("Fecha de recepción:", styles['Normal']),
        ]], colWidths=[10*cm, 7*cm])
        firma.setStyle(TableStyle([('TOPPADDING', (0,0), (-1,-1), 20)]))
        story += [firma, Spacer(1, 1.5*cm)]
        lineas = Table([[
            HRFlowable(width=9*cm, thickness=1, color=colors.black),
            HRFlowable(width=6*cm, thickness=1, color=colors.black),
        ]], colWidths=[10*cm, 7*cm])
        story.append(lineas)

    story += [
        Spacer(1, .4*cm),
        HRFlowable(width="100%", thickness=1, color=BORDER),
        Spacer(1, .2*cm),
        Paragraph("Documento generado por Sistema de Gestión · Comenda Deco", small_gray),
    ]

    doc.build(story)
    buf.seek(0)
    return buf
