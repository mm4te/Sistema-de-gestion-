# services/presupuesto_service.py
import io
import logging
from datetime import datetime, date

from models import get_conn, registrar_venta

logger = logging.getLogger(__name__)

ESTADOS_VALIDOS = ('borrador', 'enviado', 'aprobado', 'rechazado', 'vencido')

# Qué transiciones de estado están permitidas
TRANSICIONES_VALIDAS = {
    'borrador':  ('enviado', 'aprobado', 'rechazado'),
    'enviado':   ('aprobado', 'rechazado', 'vencido'),
    'aprobado':  (),
    'rechazado': ('borrador',),
    'vencido':   ('borrador',),
}


# ── Número correlativo ───────────────────────────────────────────────────────

def _siguiente_numero(cursor):
    año = datetime.now().year
    cursor.execute(
        "SELECT numero FROM presupuestos WHERE numero LIKE ? ORDER BY numero DESC LIMIT 1",
        (f"PRES-{año}-%",)
    )
    ultimo = cursor.fetchone()
    n = (int(ultimo['numero'].split('-')[-1]) + 1) if ultimo else 1
    return f"PRES-{año}-{n:05d}"


# ── Listado ──────────────────────────────────────────────────────────────────

def listar_presupuestos(estado=None, cliente_id=None, page=1, per_page=20):
    conn = get_conn()
    conds, params = [], []
    if estado:
        conds.append("p.estado = ?")
        params.append(estado)
    if cliente_id:
        conds.append("p.cliente_id = ?")
        params.append(cliente_id)
    where = ("WHERE " + " AND ".join(conds)) if conds else ""

    total = conn.execute(
        f"SELECT COUNT(*) FROM presupuestos p {where}", params
    ).fetchone()[0]

    offset = (page - 1) * per_page
    rows = conn.execute(f"""
        SELECT p.*, c.nombre AS cliente_nombre
        FROM presupuestos p
        JOIN clientes c ON p.cliente_id = c.id
        {where}
        ORDER BY p.id DESC
        LIMIT ? OFFSET ?
    """, (*params, per_page, offset)).fetchall()

    conn.close()
    return rows, total


# ── Detalle ──────────────────────────────────────────────────────────────────

def get_presupuesto(presupuesto_id):
    conn = get_conn()
    p = conn.execute("""
        SELECT p.*, c.nombre AS cliente_nombre, c.cuit, c.telefono, c.email, c.dni
        FROM presupuestos p
        JOIN clientes c ON p.cliente_id = c.id
        WHERE p.id = ?
    """, (presupuesto_id,)).fetchone()

    if not p:
        conn.close()
        return None, [], []

    items = conn.execute("""
        SELECT pi.*, pr.sku
        FROM presupuesto_items pi
        LEFT JOIN productos pr ON pi.producto_id = pr.id
        WHERE pi.presupuesto_id = ?
        ORDER BY pi.id
    """, (presupuesto_id,)).fetchall()

    historial = conn.execute("""
        SELECT ph.*, u.username
        FROM presupuesto_historial ph
        LEFT JOIN usuarios u ON ph.usuario_id = u.id
        WHERE ph.presupuesto_id = ?
        ORDER BY ph.fecha ASC
    """, (presupuesto_id,)).fetchall()

    conn.close()
    return p, items, historial


# ── Crear ────────────────────────────────────────────────────────────────────

def crear_presupuesto(cliente_id, fecha_validez, items, observaciones=None, usuario_id=None):
    if not items:
        return False, "El presupuesto debe tener al menos un ítem"

    conn = get_conn()
    try:
        cursor = conn.cursor()
        numero = _siguiente_numero(cursor)
        fecha = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        total = sum(float(i['precio_unitario']) * float(i['cantidad']) for i in items)

        cursor.execute("""
            INSERT INTO presupuestos
                (numero, cliente_id, fecha, fecha_validez, estado, total, observaciones, creado_por)
            VALUES (?, ?, ?, ?, 'borrador', ?, ?, ?)
        """, (numero, cliente_id, fecha, fecha_validez, total, observaciones, usuario_id))

        presupuesto_id = cursor.lastrowid

        for item in items:
            subtotal = float(item['precio_unitario']) * float(item['cantidad'])
            cursor.execute("""
                INSERT INTO presupuesto_items
                    (presupuesto_id, producto_id, descripcion, cantidad, precio_unitario, subtotal)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (presupuesto_id,
                  item.get('producto_id') or None,
                  item['descripcion'],
                  float(item['cantidad']),
                  float(item['precio_unitario']),
                  subtotal))

        cursor.execute("""
            INSERT INTO presupuesto_historial
                (presupuesto_id, estado_anterior, estado_nuevo, fecha, usuario_id, nota)
            VALUES (?, NULL, 'borrador', ?, ?, 'Presupuesto creado')
        """, (presupuesto_id, fecha, usuario_id))

        conn.commit()
        logger.info("Presupuesto %s creado (id=%s)", numero, presupuesto_id)
        return True, presupuesto_id

    except Exception as e:
        conn.rollback()
        logger.exception("Error creando presupuesto")
        return False, str(e)
    finally:
        conn.close()


# ── Actualizar ───────────────────────────────────────────────────────────────

def actualizar_presupuesto(presupuesto_id, cliente_id, fecha_validez, items, observaciones=None):
    if not items:
        return False, "El presupuesto debe tener al menos un ítem"

    conn = get_conn()
    try:
        p = conn.execute(
            "SELECT estado FROM presupuestos WHERE id = ?", (presupuesto_id,)
        ).fetchone()
        if not p:
            return False, "Presupuesto no encontrado"
        if p['estado'] != 'borrador':
            return False, "Solo se pueden editar presupuestos en estado borrador"

        total = sum(float(i['precio_unitario']) * float(i['cantidad']) for i in items)

        conn.execute("""
            UPDATE presupuestos
            SET cliente_id=?, fecha_validez=?, total=?, observaciones=?
            WHERE id=?
        """, (cliente_id, fecha_validez, total, observaciones, presupuesto_id))

        conn.execute(
            "DELETE FROM presupuesto_items WHERE presupuesto_id = ?", (presupuesto_id,)
        )
        for item in items:
            subtotal = float(item['precio_unitario']) * float(item['cantidad'])
            conn.execute("""
                INSERT INTO presupuesto_items
                    (presupuesto_id, producto_id, descripcion, cantidad, precio_unitario, subtotal)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (presupuesto_id,
                  item.get('producto_id') or None,
                  item['descripcion'],
                  float(item['cantidad']),
                  float(item['precio_unitario']),
                  subtotal))

        conn.commit()
        return True, presupuesto_id

    except Exception as e:
        conn.rollback()
        logger.exception("Error actualizando presupuesto %s", presupuesto_id)
        return False, str(e)
    finally:
        conn.close()


# ── Cambio de estado ─────────────────────────────────────────────────────────

def cambiar_estado(presupuesto_id, nuevo_estado, usuario_id=None, nota=None):
    if nuevo_estado not in ESTADOS_VALIDOS:
        return False, f"Estado inválido: {nuevo_estado}"

    conn = get_conn()
    try:
        p = conn.execute(
            "SELECT estado FROM presupuestos WHERE id = ?", (presupuesto_id,)
        ).fetchone()
        if not p:
            return False, "Presupuesto no encontrado"

        estado_actual = p['estado']
        if nuevo_estado not in TRANSICIONES_VALIDAS.get(estado_actual, ()):
            return False, f"No se puede pasar de '{estado_actual}' a '{nuevo_estado}'"

        fecha = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            "UPDATE presupuestos SET estado = ? WHERE id = ?", (nuevo_estado, presupuesto_id)
        )
        conn.execute("""
            INSERT INTO presupuesto_historial
                (presupuesto_id, estado_anterior, estado_nuevo, fecha, usuario_id, nota)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (presupuesto_id, estado_actual, nuevo_estado, fecha, usuario_id, nota))

        conn.commit()
        logger.info("Presupuesto %s: %s → %s", presupuesto_id, estado_actual, nuevo_estado)
        return True, nuevo_estado

    except Exception as e:
        conn.rollback()
        logger.exception("Error cambiando estado presupuesto %s", presupuesto_id)
        return False, str(e)
    finally:
        conn.close()


# ── Eliminar ─────────────────────────────────────────────────────────────────

def eliminar_presupuesto(presupuesto_id):
    conn = get_conn()
    try:
        p = conn.execute(
            "SELECT estado FROM presupuestos WHERE id = ?", (presupuesto_id,)
        ).fetchone()
        if not p:
            return False, "Presupuesto no encontrado"
        if p['estado'] != 'borrador':
            return False, "Solo se pueden eliminar presupuestos en estado borrador"

        conn.execute("DELETE FROM presupuesto_items WHERE presupuesto_id = ?", (presupuesto_id,))
        conn.execute("DELETE FROM presupuesto_historial WHERE presupuesto_id = ?", (presupuesto_id,))
        conn.execute("DELETE FROM presupuestos WHERE id = ?", (presupuesto_id,))
        conn.commit()
        return True, "Eliminado"

    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


# ── Convertir a venta ────────────────────────────────────────────────────────

def convertir_a_venta(presupuesto_id, metodo_pago, cuotas=None,
                      monto_recibido=None, vuelto=None, creado_por=None):
    conn = get_conn()
    p = conn.execute(
        "SELECT * FROM presupuestos WHERE id = ?", (presupuesto_id,)
    ).fetchone()
    if not p:
        conn.close()
        return False, "Presupuesto no encontrado"

    # Guard: evitar conversiones duplicadas
    if p['estado'] == 'convertido' or p['venta_id']:
        conn.close()
        return False, "Este presupuesto ya fue convertido a venta."

    if p['estado'] in ('rechazado', 'vencido'):
        conn.close()
        return False, f"No se puede convertir un presupuesto en estado '{p['estado']}'"

    items = conn.execute(
        "SELECT * FROM presupuesto_items WHERE presupuesto_id = ?", (presupuesto_id,)
    ).fetchall()
    conn.close()

    carrito = [
        {
            'id':          item['producto_id'],
            'descripcion': item['descripcion'],
            'precio':      float(item['precio_unitario']),
            'cantidad':    int(item['cantidad']),
        }
        for item in items if item['producto_id']
    ]

    if not carrito:
        return False, "Ningún ítem tiene producto del inventario asociado"

    success, result = registrar_venta(p['cliente_id'], carrito, metodo_pago, cuotas,
                                      monto_recibido, vuelto, creado_por)
    if not success:
        return False, result

    venta_id = result

    # Marcar presupuesto como convertido y guardar referencia a la venta
    conn = get_conn()
    try:
        fecha = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            "UPDATE presupuestos SET estado='convertido', venta_id=? WHERE id=?",
            (venta_id, presupuesto_id)
        )
        conn.execute("""
            INSERT INTO presupuesto_historial
                (presupuesto_id, estado_anterior, estado_nuevo, fecha, usuario_id, nota)
            VALUES (?, ?, 'convertido', ?, ?, ?)
        """, (presupuesto_id, p['estado'], fecha, creado_por,
              f"Convertido a Venta #{venta_id}"))
        conn.commit()
        logger.info("Presupuesto %s convertido a venta #%s", presupuesto_id, venta_id)
    except Exception as e:
        conn.rollback()
        logger.exception("Error marcando presupuesto %s como convertido", presupuesto_id)
    finally:
        conn.close()

    return True, venta_id


# ── Vencimiento automático ───────────────────────────────────────────────────

def marcar_vencidos():
    hoy = date.today().isoformat()
    conn = get_conn()
    vencidos = conn.execute("""
        SELECT id FROM presupuestos
        WHERE estado = 'enviado' AND fecha_validez < ?
    """, (hoy,)).fetchall()
    conn.close()

    count = 0
    for row in vencidos:
        ok, _ = cambiar_estado(row['id'], 'vencido', nota='Vencimiento automático')
        if ok:
            count += 1
    return count


# ── Generación de PDF ────────────────────────────────────────────────────────

def generar_pdf(presupuesto_id):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle,
        Paragraph, Spacer, HRFlowable
    )

    p, items, _ = get_presupuesto(presupuesto_id)
    if not p:
        return None

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            title=f"Presupuesto {p['numero']}",
                            rightMargin=2*cm, leftMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    story  = []

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
            f"<b><font size='14'>PRESUPUESTO</font></b><br/>"
            f"<font size='11'>N° {p['numero']}</font>",
            right_style
        )
    ]], colWidths=[10*cm, 7*cm])
    hdr.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    story += [hdr, HRFlowable(width="100%", thickness=2, color=PRIMARY), Spacer(1, .4*cm)]

    # ── Fechas / Estado ───────────────────────────────────────────────────
    fecha_str   = (p['fecha'] or '')[:10]
    validez_str = p['fecha_validez']
    estado_lbl  = p['estado'].upper()

    fechas = Table([[
        Paragraph(f"<b>Fecha:</b> {fecha_str}", styles['Normal']),
        Paragraph(f"<b>Válido hasta:</b> {validez_str}", styles['Normal']),
        Paragraph(f"<b>Estado:</b> {estado_lbl}", styles['Normal']),
    ]], colWidths=[6*cm, 6*cm, 5*cm])
    fechas.setStyle(TableStyle([('BOTTOMPADDING', (0, 0), (-1, -1), 8)]))
    story += [fechas, Spacer(1, .3*cm)]

    # ── Cliente ───────────────────────────────────────────────────────────
    story.append(Paragraph(
        "<b>CLIENTE</b>",
        ParagraphStyle('hdr', parent=styles['Normal'],
                       backColor=LIGHT, leftPadding=6, fontSize=10)
    ))
    story.append(Spacer(1, .2*cm))
    cli_txt = f"<b>{p['cliente_nombre']}</b>"
    if p['cuit']:    cli_txt += f"&nbsp;&nbsp;CUIT: {p['cuit']}"
    if p['telefono']:cli_txt += f"&nbsp;&nbsp;Tel: {p['telefono']}"
    if p['email']:   cli_txt += f"&nbsp;&nbsp;Email: {p['email']}"
    story += [Paragraph(cli_txt, styles['Normal']), Spacer(1, .5*cm)]

    # ── Tabla de ítems ────────────────────────────────────────────────────
    story.append(Paragraph(
        "<b>DETALLE</b>",
        ParagraphStyle('hdr', parent=styles['Normal'],
                       backColor=LIGHT, leftPadding=6, fontSize=10)
    ))
    story.append(Spacer(1, .2*cm))

    tbl_data = [['#', 'Descripción', 'Cantidad', 'Precio unit.', 'Subtotal']]
    for i, it in enumerate(items, 1):
        tbl_data.append([
            str(i),
            it['descripcion'],
            f"{float(it['cantidad']):.0f}",
            f"${float(it['precio_unitario']):,.2f}",
            f"${float(it['subtotal']):,.2f}",
        ])
    tbl_data.append([
        '', '', '',
        Paragraph('<b>TOTAL</b>', right_style),
        Paragraph(f"<b>${float(p['total']):,.2f}</b>", right_style),
    ])

    tbl = Table(tbl_data, colWidths=[1*cm, 8*cm, 2.5*cm, 3*cm, 2.5*cm])
    tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, 0),  PRIMARY),
        ('TEXTCOLOR',     (0, 0), (-1, 0),  colors.white),
        ('FONTNAME',      (0, 0), (-1, 0),  'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0), (-1, -1), 9),
        ('ROWBACKGROUNDS',(0, 1), (-1, -2), [colors.white, ALT_ROW]),
        ('GRID',          (0, 0), (-1, -2), 0.5, BORDER),
        ('ALIGN',         (2, 0), (-1, -1), 'RIGHT'),
        ('LINEABOVE',     (0, -1),(-1, -1), 1, PRIMARY),
        ('TOPPADDING',    (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story += [tbl, Spacer(1, .5*cm)]

    # ── Observaciones ─────────────────────────────────────────────────────
    if p['observaciones']:
        story.append(Paragraph(
            "<b>OBSERVACIONES</b>",
            ParagraphStyle('hdr', parent=styles['Normal'],
                           backColor=LIGHT, leftPadding=6, fontSize=10)
        ))
        story += [Spacer(1, .2*cm),
                  Paragraph(p['observaciones'], styles['Normal']),
                  Spacer(1, .5*cm)]

    # ── Pie ───────────────────────────────────────────────────────────────
    story += [
        HRFlowable(width="100%", thickness=1, color=BORDER),
        Spacer(1, .2*cm),
        Paragraph(
            "Documento generado por Sistema de Gestión · Comenda Deco",
            small_gray
        ),
    ]

    doc.build(story)
    buf.seek(0)
    return buf
