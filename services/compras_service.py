# services/compras_service.py
import io
import logging
from datetime import datetime, date

from models import get_conn
from services.caja_service import registrar_movimiento_en_conn

logger = logging.getLogger(__name__)

ESTADOS_COMPRA = [
    ('pendiente_pago',   'Pendiente de pago'),
    ('pago_parcial',     'Pago parcial'),
    ('pagado',           'Pagado'),
    ('recibido_parcial', 'Recibido parcial'),
    ('recibido',         'Recibido'),
    ('cerrado',          'Cerrado'),
]

METODOS_PAGO = ['transferencia', 'efectivo', 'tarjeta', 'otro']

CONDICIONES_IVA = [
    'Responsable Inscripto',
    'Monotributista',
    'Exento',
    'Consumidor Final',
]


# ── Número automático ─────────────────────────────────────────────────────────

def _generar_numero(conn):
    year = datetime.now().year
    row = conn.execute(
        "SELECT COUNT(*) FROM compras WHERE numero LIKE ?",
        (f'COMP-{year}-%',)
    ).fetchone()
    seq = row[0] + 1
    return f'COMP-{year}-{seq:05d}'


# ── Proveedores (nacionales) ──────────────────────────────────────────────────

def listar_proveedores_nacionales():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM proveedores WHERE tipo = 'nacional' ORDER BY nombre ASC"
    ).fetchall()
    conn.close()
    return rows


def get_proveedor(proveedor_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM proveedores WHERE id = ?", (proveedor_id,)).fetchone()
    conn.close()
    return row


def crear_proveedor_nacional(nombre, cuit=None, condicion_iva=None,
                              contacto=None, telefono=None, email=None,
                              direccion=None, notas=None):
    if not nombre:
        return False, "El nombre es requerido"
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO proveedores
               (nombre, tipo, cuit, condicion_iva, contacto, telefono, email, direccion, notas)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (nombre, 'nacional', cuit or None, condicion_iva or None,
             contacto or None, telefono or None, email or None,
             direccion or None, notas or None)
        )
        conn.commit()
        new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        return True, new_id
    except Exception as e:
        conn.rollback()
        logger.error("crear_proveedor_nacional: %s", e)
        return False, str(e)
    finally:
        conn.close()


def actualizar_proveedor_nacional(proveedor_id, nombre, cuit=None, condicion_iva=None,
                                   contacto=None, telefono=None, email=None,
                                   direccion=None, notas=None):
    if not nombre:
        return False, "El nombre es requerido"
    conn = get_conn()
    try:
        conn.execute(
            """UPDATE proveedores
               SET nombre=?, tipo='nacional', cuit=?, condicion_iva=?,
                   contacto=?, telefono=?, email=?, direccion=?, notas=?
               WHERE id=?""",
            (nombre, cuit or None, condicion_iva or None,
             contacto or None, telefono or None, email or None,
             direccion or None, notas or None, proveedor_id)
        )
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def eliminar_proveedor_nacional(proveedor_id):
    conn = get_conn()
    tiene = conn.execute(
        "SELECT COUNT(*) FROM compras WHERE proveedor_id = ?", (proveedor_id,)
    ).fetchone()[0]
    conn.close()
    if tiene > 0:
        return False, "El proveedor tiene compras asociadas y no puede eliminarse"
    conn = get_conn()
    conn.execute("DELETE FROM proveedores WHERE id = ?", (proveedor_id,))
    conn.commit()
    conn.close()
    return True, None


# ── Compras ───────────────────────────────────────────────────────────────────

def listar_compras(estado=None, proveedor_id=None, fecha_desde=None,
                   fecha_hasta=None, page=1, per_page=20):
    conn = get_conn()
    conds, params = ["p.tipo = 'nacional'"], []
    if estado:
        conds.append("c.estado = ?"); params.append(estado)
    if proveedor_id:
        conds.append("c.proveedor_id = ?"); params.append(proveedor_id)
    if fecha_desde:
        conds.append("c.fecha >= ?"); params.append(fecha_desde)
    if fecha_hasta:
        conds.append("c.fecha <= ?"); params.append(fecha_hasta)
    where = "WHERE " + " AND ".join(conds)

    total = conn.execute(
        f"""SELECT COUNT(*) FROM compras c
            JOIN proveedores p ON c.proveedor_id = p.id {where}""", params
    ).fetchone()[0]

    offset = (page - 1) * per_page
    rows = conn.execute(f"""
        SELECT c.*,
               p.nombre AS proveedor_nombre,
               COALESCE((SELECT SUM(ci.cantidad * ci.costo_unitario)
                         FROM compra_items ci WHERE ci.compra_id = c.id), 0) AS total_compra
        FROM compras c
        JOIN proveedores p ON c.proveedor_id = p.id
        {where}
        ORDER BY c.id DESC
        LIMIT ? OFFSET ?
    """, (*params, per_page, offset)).fetchall()
    conn.close()
    return rows, total


def get_compra(compra_id):
    conn = get_conn()
    row = conn.execute("""
        SELECT c.*, p.nombre AS proveedor_nombre, p.cuit, p.condicion_iva
        FROM compras c
        JOIN proveedores p ON c.proveedor_id = p.id
        WHERE c.id = ?
    """, (compra_id,)).fetchone()
    conn.close()
    return row


def get_compra_items(compra_id):
    conn = get_conn()
    rows = conn.execute("""
        SELECT ci.*, pr.descripcion AS producto_desc, pr.sku
        FROM compra_items ci
        LEFT JOIN productos pr ON ci.producto_id = pr.id
        WHERE ci.compra_id = ?
        ORDER BY ci.id ASC
    """, (compra_id,)).fetchall()
    conn.close()
    return rows


def get_compra_pagos(compra_id):
    conn = get_conn()
    rows = conn.execute("""
        SELECT cp.*, u.username AS usuario_nombre
        FROM compra_pagos cp
        LEFT JOIN usuarios u ON cp.registrado_por = u.id
        WHERE cp.compra_id = ?
        ORDER BY cp.id ASC
    """, (compra_id,)).fetchall()
    conn.close()
    return rows


def crear_compra(proveedor_id, fecha, numero_factura_proveedor=None, observaciones=None):
    conn = get_conn()
    try:
        numero = _generar_numero(conn)
        conn.execute(
            """INSERT INTO compras
               (proveedor_id, numero, fecha, estado, numero_factura_proveedor, observaciones)
               VALUES (?,?,?,?,?,?)""",
            (proveedor_id, numero, fecha, 'pendiente_pago',
             numero_factura_proveedor or None, observaciones or None)
        )
        conn.commit()
        new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        return True, new_id
    except Exception as e:
        conn.rollback()
        logger.error("crear_compra: %s", e)
        return False, str(e)
    finally:
        conn.close()


def actualizar_compra(compra_id, proveedor_id, fecha,
                      numero_factura_proveedor=None, observaciones=None):
    conn = get_conn()
    try:
        conn.execute(
            """UPDATE compras
               SET proveedor_id=?, fecha=?, numero_factura_proveedor=?, observaciones=?
               WHERE id=?""",
            (proveedor_id, fecha, numero_factura_proveedor or None,
             observaciones or None, compra_id)
        )
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


# ── Items ─────────────────────────────────────────────────────────────────────

def agregar_item(compra_id, producto_id, descripcion, cantidad, costo_unitario):
    if cantidad <= 0:
        return False, "La cantidad debe ser mayor a cero"
    if costo_unitario < 0:
        return False, "El costo no puede ser negativo"
    conn = get_conn()
    try:
        desc_final = descripcion
        if producto_id:
            p = conn.execute(
                "SELECT descripcion FROM productos WHERE id = ?", (producto_id,)
            ).fetchone()
            if p:
                desc_final = p['descripcion']
        if not desc_final:
            return False, "La descripción es requerida"
        conn.execute(
            """INSERT INTO compra_items
               (compra_id, producto_id, descripcion, cantidad, costo_unitario)
               VALUES (?,?,?,?,?)""",
            (compra_id, producto_id or None, desc_final, cantidad, costo_unitario)
        )
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def eliminar_item(item_id):
    conn = get_conn()
    conn.execute("DELETE FROM compra_items WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    return True, None


# ── Pagos ─────────────────────────────────────────────────────────────────────

def registrar_pago(compra_id, monto, metodo_pago=None, fecha_pago=None,
                   comprobante=None, usuario_id=None):
    if monto <= 0:
        return False, "El monto debe ser mayor a cero"
    conn = get_conn()
    try:
        compra = conn.execute("SELECT * FROM compras WHERE id = ?", (compra_id,)).fetchone()
        if not compra:
            return False, "Compra no encontrada"
        if compra['estado'] not in ('pendiente_pago', 'pago_parcial'):
            return False, f"No se puede registrar pago en estado '{dict(ESTADOS_COMPRA).get(compra['estado'], compra['estado'])}'"

        total_items = conn.execute(
            "SELECT COALESCE(SUM(cantidad * costo_unitario), 0) FROM compra_items WHERE compra_id = ?",
            (compra_id,)
        ).fetchone()[0]
        if float(total_items) <= 0:
            return False, "La compra no tiene productos. Agregá ítems antes de registrar el pago."

        if not fecha_pago:
            fecha_pago = datetime.now().strftime('%Y-%m-%d')

        conn.execute(
            """INSERT INTO compra_pagos
               (compra_id, monto, metodo_pago, fecha_pago, comprobante, registrado_por)
               VALUES (?,?,?,?,?,?)""",
            (compra_id, monto, metodo_pago, fecha_pago, comprobante or None, usuario_id)
        )

        total_pagado = conn.execute(
            "SELECT COALESCE(SUM(monto), 0) FROM compra_pagos WHERE compra_id = ?",
            (compra_id,)
        ).fetchone()[0]

        if float(total_pagado) >= float(total_items) * 0.999:
            conn.execute("UPDATE compras SET estado='pagado' WHERE id=?", (compra_id,))
        else:
            conn.execute("UPDATE compras SET estado='pago_parcial' WHERE id=?", (compra_id,))

        registrar_movimiento_en_conn(
            conn, 'egreso', 'compra', compra_id,
            f"Pago a proveedor {compra['numero']} (ARS {float(monto):,.2f})",
            monto, metodo_pago, usuario_id
        )
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        logger.error("registrar_pago compra: %s", e)
        return False, str(e)
    finally:
        conn.close()


# ── Recepción parcial ─────────────────────────────────────────────────────────

def registrar_recepcion(compra_id, recepciones_dict, usuario_id=None):
    """recepciones_dict: {str(item_id): cantidad_adicional}"""
    conn = get_conn()
    try:
        compra = conn.execute("SELECT * FROM compras WHERE id = ?", (compra_id,)).fetchone()
        if not compra:
            return False, "Compra no encontrada"
        estados_validos = ('pagado', 'recibido_parcial', 'pago_parcial', 'pendiente_pago')
        if compra['estado'] not in estados_validos:
            return False, "Solo se puede registrar recepción en compras pendientes, pagadas o con recepción parcial"

        items = conn.execute(
            "SELECT * FROM compra_items WHERE compra_id = ?", (compra_id,)
        ).fetchall()

        alguno = False
        for it in items:
            adicional = float(recepciones_dict.get(str(it['id']), 0) or 0)
            if adicional <= 0:
                continue
            alguno = True
            nueva_recibida = float(it['cantidad_recibida'] or 0) + adicional
            if nueva_recibida > float(it['cantidad']) + 0.001:
                return False, (
                    f"'{it['descripcion']}': la cantidad recibida ({nueva_recibida:.0f}) "
                    f"supera lo pedido ({it['cantidad']:.0f})"
                )
            conn.execute(
                "UPDATE compra_items SET cantidad_recibida=? WHERE id=?",
                (nueva_recibida, it['id'])
            )

        if not alguno:
            return False, "No se ingresó ninguna cantidad a recibir"

        items_act = conn.execute(
            "SELECT cantidad, cantidad_recibida FROM compra_items WHERE compra_id = ?",
            (compra_id,)
        ).fetchall()
        todo_recibido = all(
            float(it['cantidad_recibida'] or 0) >= float(it['cantidad']) * 0.999
            for it in items_act
        )

        fecha_hoy = datetime.now().strftime('%Y-%m-%d')
        if todo_recibido:
            conn.execute("UPDATE compras SET estado='recibido' WHERE id=?", (compra_id,))
        else:
            conn.execute("UPDATE compras SET estado='recibido_parcial' WHERE id=?", (compra_id,))

        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        logger.error("registrar_recepcion compra: %s", e)
        return False, str(e)
    finally:
        conn.close()


# ── Cerrar (aplicar costos a inventario) ──────────────────────────────────────

def cerrar_compra(compra_id, usuario_id=None):
    conn = get_conn()
    try:
        compra = conn.execute("SELECT * FROM compras WHERE id = ?", (compra_id,)).fetchone()
        if not compra:
            return False, "Compra no encontrada"
        if compra['estado'] == 'cerrado':
            return False, "La compra ya está cerrada"

        items = conn.execute(
            "SELECT * FROM compra_items WHERE compra_id = ?", (compra_id,)
        ).fetchall()
        if not items:
            return False, "La compra no tiene productos"

        for it in items:
            cant_recibida = float(it['cantidad_recibida'] or 0)
            cant_inventario = int(cant_recibida) if cant_recibida > 0 else int(float(it['cantidad']))
            costo = float(it['costo_unitario'])

            if it['producto_id']:
                conn.execute(
                    "UPDATE productos SET costo=?, stock=stock+? WHERE id=?",
                    (costo, cant_inventario, it['producto_id'])
                )
            else:
                sku = f"COMP-{compra_id}-{it['id']}"
                existing = conn.execute(
                    "SELECT id FROM productos WHERE sku = ?", (sku,)
                ).fetchone()
                if not existing:
                    conn.execute(
                        """INSERT INTO productos
                           (sku, descripcion, precio, stock, costo, activo)
                           VALUES (?,?,?,?,?,1)""",
                        (sku, it['descripcion'], costo, cant_inventario, costo)
                    )
                    new_prod_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                    conn.execute(
                        "UPDATE compra_items SET producto_id=? WHERE id=?",
                        (new_prod_id, it['id'])
                    )
                else:
                    conn.execute(
                        "UPDATE productos SET costo=?, stock=stock+? WHERE id=?",
                        (costo, cant_inventario, existing['id'])
                    )

        conn.execute("UPDATE compras SET estado='cerrado' WHERE id=?", (compra_id,))
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        logger.error("cerrar_compra: %s", e)
        return False, str(e)
    finally:
        conn.close()


# ── Cálculos (sin persistir) ──────────────────────────────────────────────────

def calcular_totales(compra_id):
    conn = get_conn()
    items = conn.execute(
        "SELECT * FROM compra_items WHERE compra_id = ? ORDER BY id ASC", (compra_id,)
    ).fetchall()
    total_pagado = conn.execute(
        "SELECT COALESCE(SUM(monto), 0) FROM compra_pagos WHERE compra_id = ?", (compra_id,)
    ).fetchone()[0]
    conn.close()

    total_compra = sum(float(it['cantidad']) * float(it['costo_unitario']) for it in items)
    saldo = total_compra - float(total_pagado)
    return {
        'total_compra': total_compra,
        'total_pagado':  float(total_pagado),
        'saldo':         max(0, saldo),
    }


# ── PDF de la orden ───────────────────────────────────────────────────────────

def generar_pdf_compra(compra_id):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle,
        Paragraph, Spacer, HRFlowable
    )

    compra = get_compra(compra_id)
    if not compra:
        return None

    items = get_compra_items(compra_id)
    pagos = get_compra_pagos(compra_id)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            title=f"Compra {compra['numero']}",
                            rightMargin=1.8*cm, leftMargin=1.8*cm,
                            topMargin=2*cm, bottomMargin=2*cm)

    styles  = getSampleStyleSheet()
    story   = []

    PRIMARY = colors.HexColor('#4361ee')
    LIGHT   = colors.HexColor('#f1f3f9')
    BORDER  = colors.HexColor('#dee2e6')
    ALT_ROW = colors.HexColor('#f8f9fa')

    right_s  = ParagraphStyle('right',  parent=styles['Normal'], alignment=TA_RIGHT)
    center_s = ParagraphStyle('center', parent=styles['Normal'], alignment=TA_CENTER)
    small_g  = ParagraphStyle('small',  parent=styles['Normal'],
                               fontSize=8, textColor=colors.HexColor('#6c757d'))

    # ── Cabecera ──────────────────────────────────────────────────────────────
    hdr = Table([[
        Paragraph("<b><font size='16' color='#4361ee'>COMENDA DECO</font></b>",
                  styles['Normal']),
        Paragraph(
            f"<b><font size='13'>ORDEN DE COMPRA</font></b><br/>"
            f"<font size='11'>N° {compra['numero']}</font>",
            right_s
        ),
    ]], colWidths=[10*cm, 7.4*cm])
    hdr.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story += [hdr, HRFlowable(width="100%", thickness=2, color=PRIMARY), Spacer(1, .3*cm)]

    # ── Fechas / Estado ───────────────────────────────────────────────────────
    estado_lbl = dict(ESTADOS_COMPRA).get(compra['estado'], compra['estado']).upper()
    fecha_row = Table([[
        Paragraph(f"<b>Fecha:</b> {compra['fecha']}", styles['Normal']),
        Paragraph(f"<b>Estado:</b> {estado_lbl}", styles['Normal']),
        Paragraph(
            f"<b>Factura proveedor:</b> {compra['numero_factura_proveedor'] or '—'}",
            styles['Normal']
        ),
    ]], colWidths=[5*cm, 5*cm, 7.4*cm])
    fecha_row.setStyle(TableStyle([('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))
    story += [fecha_row, Spacer(1, .2*cm)]

    # ── Proveedor ─────────────────────────────────────────────────────────────
    story.append(Paragraph(
        "<b>PROVEEDOR</b>",
        ParagraphStyle('hdr_sec', parent=styles['Normal'],
                       backColor=LIGHT, leftPadding=6, fontSize=10)
    ))
    story.append(Spacer(1, .15*cm))
    prov_lines = [f"<b>{compra['proveedor_nombre']}</b>"]
    if compra['cuit']:
        prov_lines.append(f"CUIT: {compra['cuit']}")
    if compra['condicion_iva']:
        prov_lines.append(f"IVA: {compra['condicion_iva']}")
    story += [Paragraph("<br/>".join(prov_lines), styles['Normal']), Spacer(1, .3*cm)]

    # ── Tabla de ítems ────────────────────────────────────────────────────────
    story.append(Paragraph(
        "<b>PRODUCTOS DEL PEDIDO</b>",
        ParagraphStyle('hdr_sec', parent=styles['Normal'],
                       backColor=LIGHT, leftPadding=6, fontSize=10)
    ))
    story.append(Spacer(1, .15*cm))

    total_compra = 0.0
    if items:
        tbl_data = [[
            Paragraph("<b>Descripción</b>", styles['Normal']),
            Paragraph("<b>Cant.</b>", right_s),
            Paragraph("<b>Costo Unit. (ARS)</b>", right_s),
            Paragraph("<b>Subtotal (ARS)</b>", right_s),
        ]]
        for it in items:
            subtotal = float(it['cantidad']) * float(it['costo_unitario'])
            total_compra += subtotal
            tbl_data.append([
                Paragraph(it['descripcion'], styles['Normal']),
                Paragraph(f"{it['cantidad']:.0f}", right_s),
                Paragraph(f"$ {float(it['costo_unitario']):,.2f}".replace(',', '.'), right_s),
                Paragraph(f"$ {subtotal:,.2f}".replace(',', '.'), right_s),
            ])
        tbl_data.append([
            Paragraph("<b>TOTAL</b>", right_s), '', '',
            Paragraph(f"<b>$ {total_compra:,.2f}</b>".replace(',', '.'), right_s),
        ])
        t = Table(tbl_data, colWidths=[8*cm, 2*cm, 4*cm, 3.4*cm])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), PRIMARY),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, ALT_ROW]),
            ('BACKGROUND', (0, -1), (-1, -1), LIGHT),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('SPAN', (0, -1), (2, -1)),
        ]))
        story += [t, Spacer(1, .4*cm)]

    # ── Pagos al proveedor ────────────────────────────────────────────────────
    story.append(Paragraph(
        "<b>PAGOS AL PROVEEDOR</b>",
        ParagraphStyle('hdr_sec', parent=styles['Normal'],
                       backColor=LIGHT, leftPadding=6, fontSize=10)
    ))
    story.append(Spacer(1, .15*cm))

    if pagos:
        total_pagado = sum(float(p['monto']) for p in pagos)
        saldo = total_compra - total_pagado

        p_data = [[
            Paragraph("<b>Fecha</b>", styles['Normal']),
            Paragraph("<b>Monto (ARS)</b>", right_s),
            Paragraph("<b>Método</b>", styles['Normal']),
        ]]
        for pg in pagos:
            p_data.append([
                Paragraph(pg['fecha_pago'], styles['Normal']),
                Paragraph(f"$ {float(pg['monto']):,.2f}".replace(',', '.'), right_s),
                Paragraph(pg['metodo_pago'] or '—', styles['Normal']),
            ])
        p_data.append([
            Paragraph("<b>TOTAL PAGADO</b>", right_s),
            Paragraph(f"<b>$ {total_pagado:,.2f}</b>".replace(',', '.'), right_s),
            '',
        ])
        pt = Table(p_data, colWidths=[5*cm, 5*cm, 7.4*cm])
        pt.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), PRIMARY),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, ALT_ROW]),
            ('BACKGROUND', (0, -1), (-1, -1), LIGHT),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('SPAN', (0, -1), (0, -1)),
        ]))
        story += [pt, Spacer(1, .2*cm)]

        if saldo > 0.01:
            story.append(Paragraph(
                f"<font color='#dc2626'><b>Saldo pendiente: $ {saldo:,.2f}</b></font>",
                styles['Normal']
            ))
        else:
            story.append(Paragraph(
                "<font color='#16a34a'><b>Pagado en su totalidad</b></font>",
                styles['Normal']
            ))
        story.append(Spacer(1, .4*cm))
    else:
        story += [Paragraph("Sin pagos registrados.", small_g), Spacer(1, .4*cm)]

    # ── Observaciones ─────────────────────────────────────────────────────────
    if compra['observaciones']:
        story.append(Paragraph(
            "<b>OBSERVACIONES</b>",
            ParagraphStyle('hdr_sec', parent=styles['Normal'],
                           backColor=LIGHT, leftPadding=6, fontSize=10)
        ))
        story.append(Spacer(1, .15*cm))
        story.append(Paragraph(compra['observaciones'], styles['Normal']))
        story.append(Spacer(1, .3*cm))

    # ── Pie ───────────────────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=1, color=BORDER))
    story.append(Spacer(1, .15*cm))
    from datetime import datetime as _dt
    story.append(Paragraph(
        f"<font size='8' color='#6c757d'>Generado el {_dt.now().strftime('%d/%m/%Y %H:%M')}</font>",
        center_s
    ))

    doc.build(story)
    buf.seek(0)
    return buf
