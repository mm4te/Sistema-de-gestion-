# services/importaciones_service.py
import io
import logging
from datetime import datetime, date

from models import get_conn
from services.caja_service import registrar_movimiento_en_conn

logger = logging.getLogger(__name__)

ESTADOS_IMPORTACION = [
    ('pendiente_pago',   'Pendiente de pago'),
    ('pago_parcial',     'Pago parcial'),
    ('pagado',           'Pagado'),
    ('en_transito',      'En tránsito'),
    ('en_aduana',        'En aduana'),
    ('recibido_parcial', 'Recibido parcial'),
    ('recibido',         'Recibido'),
    ('cerrado',          'Cerrado'),
]

MONEDAS = ['USD', 'CNY', 'EUR']

TIPOS_GASTO_IMP = [
    ('flete',                'Flete internacional'),
    ('seguro',               'Seguro'),
    ('naviera',              'Gastos de barco/naviera'),
    ('derechos_importacion', 'Derechos de importación'),
    ('impuestos_aduaneros',  'Impuestos aduaneros'),
    ('despachante',          'Honorarios de despachante'),
    ('otros',                'Otros gastos'),
]

METODOS_PAGO = ['transferencia', 'efectivo', 'tarjeta', 'otro']

TIPOS_DOCUMENTO = [
    ('proforma',              'Proforma'),
    ('factura_comercial',     'Factura Comercial'),
    ('packing_list',          'Packing List'),
    ('conocimiento_embarque', 'Conocimiento de Embarque (BL)'),
    ('certificado_origen',    'Certificado de Origen'),
    ('seguro',                'Póliza de Seguro'),
    ('otros',                 'Otros'),
]


def _label_estado(estado):
    return dict(ESTADOS_IMPORTACION).get(estado, estado)


# ── Número automático ─────────────────────────────────────────────────────────

def _generar_numero(conn):
    year = datetime.now().year
    row = conn.execute(
        "SELECT COUNT(*) FROM importaciones WHERE numero LIKE ?",
        (f'IMP-{year}-%',)
    ).fetchone()
    seq = row[0] + 1
    return f'IMP-{year}-{seq:05d}'


# ── Proveedores ───────────────────────────────────────────────────────────────

def listar_proveedores(tipo=None):
    conn = get_conn()
    if tipo:
        rows = conn.execute(
            "SELECT * FROM proveedores WHERE tipo=? ORDER BY nombre ASC", (tipo,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM proveedores ORDER BY nombre ASC").fetchall()
    conn.close()
    return rows


def get_proveedor(proveedor_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM proveedores WHERE id = ?", (proveedor_id,)).fetchone()
    conn.close()
    return row


def crear_proveedor(nombre, pais=None, contacto=None, telefono=None, email=None,
                    notas=None, tipo='internacional', cuit=None,
                    condicion_iva=None, direccion=None):
    if not nombre:
        return False, "El nombre es requerido"
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO proveedores
               (nombre, pais, contacto, telefono, email, notas, tipo, cuit, condicion_iva, direccion)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (nombre, pais, contacto, telefono, email, notas,
             tipo or 'internacional', cuit or None, condicion_iva or None, direccion or None)
        )
        conn.commit()
        new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        return True, new_id
    except Exception as e:
        conn.rollback()
        logger.error("crear_proveedor: %s", e)
        return False, str(e)
    finally:
        conn.close()


def actualizar_proveedor(proveedor_id, nombre, pais=None, contacto=None,
                          telefono=None, email=None, notas=None,
                          tipo='internacional', cuit=None,
                          condicion_iva=None, direccion=None):
    if not nombre:
        return False, "El nombre es requerido"
    conn = get_conn()
    try:
        conn.execute(
            """UPDATE proveedores
               SET nombre=?, pais=?, contacto=?, telefono=?, email=?, notas=?,
                   tipo=?, cuit=?, condicion_iva=?, direccion=?
               WHERE id=?""",
            (nombre, pais, contacto, telefono, email, notas,
             tipo or 'internacional', cuit or None, condicion_iva or None,
             direccion or None, proveedor_id)
        )
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def eliminar_proveedor(proveedor_id):
    conn = get_conn()
    tiene_imp = conn.execute(
        "SELECT COUNT(*) FROM importaciones WHERE proveedor_id = ?", (proveedor_id,)
    ).fetchone()[0]
    tiene_comp = conn.execute(
        "SELECT COUNT(*) FROM compras WHERE proveedor_id = ?", (proveedor_id,)
    ).fetchone()[0]
    conn.close()
    if tiene_imp > 0:
        return False, "El proveedor tiene importaciones asociadas y no puede eliminarse"
    if tiene_comp > 0:
        return False, "El proveedor tiene compras nacionales asociadas y no puede eliminarse"
    conn = get_conn()
    conn.execute("DELETE FROM proveedores WHERE id = ?", (proveedor_id,))
    conn.commit()
    conn.close()
    return True, None


# ── Importaciones ─────────────────────────────────────────────────────────────

def listar_importaciones(estado=None, proveedor_id=None, page=1, per_page=20):
    conn = get_conn()
    conds, params = [], []
    if estado:
        conds.append("i.estado = ?"); params.append(estado)
    if proveedor_id:
        conds.append("i.proveedor_id = ?"); params.append(proveedor_id)
    where = ("WHERE " + " AND ".join(conds)) if conds else ""

    total = conn.execute(
        f"SELECT COUNT(*) FROM importaciones i {where}", params
    ).fetchone()[0]

    offset = (page - 1) * per_page
    rows = conn.execute(f"""
        SELECT i.*,
               p.nombre AS proveedor_nombre,
               COALESCE((SELECT SUM(ii.cantidad * ii.precio_unitario_fob)
                         FROM importacion_items ii WHERE ii.importacion_id = i.id), 0) AS total_fob,
               COALESCE((SELECT SUM(ig.monto)
                         FROM importacion_gastos ig WHERE ig.importacion_id = i.id), 0) AS total_gastos
        FROM importaciones i
        JOIN proveedores p ON i.proveedor_id = p.id
        {where}
        ORDER BY i.id DESC
        LIMIT ? OFFSET ?
    """, (*params, per_page, offset)).fetchall()
    conn.close()
    return rows, total


def get_importacion(imp_id):
    conn = get_conn()
    row = conn.execute("""
        SELECT i.*, p.nombre AS proveedor_nombre
        FROM importaciones i
        JOIN proveedores p ON i.proveedor_id = p.id
        WHERE i.id = ?
    """, (imp_id,)).fetchone()
    conn.close()
    return row


def get_importacion_items(imp_id):
    conn = get_conn()
    rows = conn.execute("""
        SELECT ii.*, pr.descripcion AS producto_desc, pr.sku
        FROM importacion_items ii
        LEFT JOIN productos pr ON ii.producto_id = pr.id
        WHERE ii.importacion_id = ?
        ORDER BY ii.id ASC
    """, (imp_id,)).fetchall()
    conn.close()
    return rows


def get_importacion_gastos(imp_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM importacion_gastos WHERE importacion_id = ? ORDER BY id ASC",
        (imp_id,)
    ).fetchall()
    conn.close()
    return rows


def get_importacion_pagos(imp_id):
    conn = get_conn()
    rows = conn.execute("""
        SELECT pg.*, u.username AS usuario_nombre
        FROM importacion_pagos pg
        LEFT JOIN usuarios u ON pg.registrado_por = u.id
        WHERE pg.importacion_id = ?
        ORDER BY pg.id ASC
    """, (imp_id,)).fetchall()
    conn.close()
    return rows


def crear_importacion(proveedor_id, fecha_pedido, moneda_origen='USD',
                       tipo_cambio=1.0, observaciones=None):
    conn = get_conn()
    try:
        numero = _generar_numero(conn)
        conn.execute(
            """INSERT INTO importaciones
               (proveedor_id, numero, fecha_pedido, estado, moneda_origen, tipo_cambio, observaciones)
               VALUES (?,?,?,?,?,?,?)""",
            (proveedor_id, numero, fecha_pedido, 'pendiente_pago',
             moneda_origen, tipo_cambio, observaciones)
        )
        conn.commit()
        new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        return True, new_id
    except Exception as e:
        conn.rollback()
        logger.error("crear_importacion: %s", e)
        return False, str(e)
    finally:
        conn.close()


def actualizar_importacion(imp_id, proveedor_id, fecha_pedido,
                            moneda_origen, tipo_cambio, observaciones=None):
    conn = get_conn()
    try:
        conn.execute(
            """UPDATE importaciones
               SET proveedor_id=?, fecha_pedido=?, moneda_origen=?, tipo_cambio=?, observaciones=?
               WHERE id=?""",
            (proveedor_id, fecha_pedido, moneda_origen, tipo_cambio, observaciones, imp_id)
        )
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


# ── Items ─────────────────────────────────────────────────────────────────────

def agregar_item(imp_id, producto_id, descripcion, cantidad, precio_unitario_fob):
    if cantidad <= 0:
        return False, "La cantidad debe ser mayor a cero"
    if precio_unitario_fob < 0:
        return False, "El precio no puede ser negativo"
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
            """INSERT INTO importacion_items
               (importacion_id, producto_id, descripcion, cantidad, precio_unitario_fob)
               VALUES (?,?,?,?,?)""",
            (imp_id, producto_id or None, desc_final, cantidad, precio_unitario_fob)
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
    conn.execute("DELETE FROM importacion_items WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    return True, None


# ── Gastos adicionales ────────────────────────────────────────────────────────

def agregar_gasto_importacion(imp_id, tipo, descripcion, monto,
                               metodo_pago=None, comprobante_nombre=None,
                               comprobante_ruta=None, usuario_id=None):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO importacion_gastos
               (importacion_id, tipo, descripcion, monto, comprobante_nombre, comprobante_ruta)
               VALUES (?,?,?,?,?,?)""",
            (imp_id, tipo, descripcion, monto, comprobante_nombre, comprobante_ruta)
        )
        imp = conn.execute(
            "SELECT numero FROM importaciones WHERE id = ?", (imp_id,)
        ).fetchone()
        tipo_labels = dict(TIPOS_GASTO_IMP)
        desc_caja = f"Importación {imp['numero']} - {tipo_labels.get(tipo, tipo)}"
        if descripcion:
            desc_caja += f": {descripcion}"
        registrar_movimiento_en_conn(
            conn, 'egreso', 'importacion', imp_id,
            desc_caja, monto, metodo_pago, usuario_id
        )
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        logger.error("agregar_gasto_importacion: %s", e)
        return False, str(e)
    finally:
        conn.close()


def eliminar_gasto_importacion(gasto_id):
    conn = get_conn()
    conn.execute("DELETE FROM importacion_gastos WHERE id = ?", (gasto_id,))
    conn.commit()
    conn.close()
    return True, None


# ── Pagos parciales al proveedor ──────────────────────────────────────────────

def registrar_pago_parcial(imp_id, monto, tipo_cambio, fecha_pago=None,
                            metodo_pago=None, usuario_id=None):
    if monto <= 0:
        return False, "El monto debe ser mayor a cero"
    conn = get_conn()
    try:
        imp = conn.execute(
            "SELECT * FROM importaciones WHERE id = ?", (imp_id,)
        ).fetchone()
        if not imp:
            return False, "Importación no encontrada"
        if imp['estado'] not in ('pendiente_pago', 'pago_parcial'):
            return False, f"No se puede registrar pago en estado '{_label_estado(imp['estado'])}'"

        total_fob = conn.execute(
            """SELECT COALESCE(SUM(cantidad * precio_unitario_fob), 0)
               FROM importacion_items WHERE importacion_id = ?""",
            (imp_id,)
        ).fetchone()[0]

        if float(total_fob) <= 0:
            return False, "La importación no tiene productos. Agregá items antes de registrar el pago."

        if not fecha_pago:
            fecha_pago = datetime.now().strftime('%Y-%m-%d')

        monto_ars = float(monto) * float(tipo_cambio)

        conn.execute(
            """INSERT INTO importacion_pagos
               (importacion_id, monto, tipo_cambio, monto_ars, fecha_pago, metodo_pago, registrado_por)
               VALUES (?,?,?,?,?,?,?)""",
            (imp_id, monto, tipo_cambio, monto_ars, fecha_pago, metodo_pago, usuario_id)
        )

        total_pagado = conn.execute(
            "SELECT COALESCE(SUM(monto), 0) FROM importacion_pagos WHERE importacion_id = ?",
            (imp_id,)
        ).fetchone()[0]

        if float(total_pagado) >= float(total_fob) * 0.999:
            conn.execute(
                "UPDATE importaciones SET estado='pagado', fecha_pago=?, tipo_cambio=? WHERE id=?",
                (fecha_pago, tipo_cambio, imp_id)
            )
        else:
            conn.execute(
                "UPDATE importaciones SET estado='pago_parcial', tipo_cambio=? WHERE id=?",
                (tipo_cambio, imp_id)
            )

        registrar_movimiento_en_conn(
            conn, 'egreso', 'importacion', imp_id,
            f"Pago a proveedor {imp['numero']} ({imp['moneda_origen']} {float(monto):,.2f} × {tipo_cambio})",
            monto_ars, metodo_pago, usuario_id
        )
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        logger.error("registrar_pago_parcial: %s", e)
        return False, str(e)
    finally:
        conn.close()


# ── Recepción parcial ─────────────────────────────────────────────────────────

def registrar_recepcion(imp_id, recepciones_dict, usuario_id=None):
    """recepciones_dict: {str(item_id): cantidad_adicional}"""
    conn = get_conn()
    try:
        imp = conn.execute(
            "SELECT * FROM importaciones WHERE id = ?", (imp_id,)
        ).fetchone()
        if not imp:
            return False, "Importación no encontrada"
        estados_validos = ('en_transito', 'en_aduana', 'recibido_parcial')
        if imp['estado'] not in estados_validos:
            return False, "Solo se puede registrar recepción en estados en tránsito, en aduana o recibido parcial"

        items = conn.execute(
            "SELECT * FROM importacion_items WHERE importacion_id = ?", (imp_id,)
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
                "UPDATE importacion_items SET cantidad_recibida=? WHERE id=?",
                (nueva_recibida, it['id'])
            )

        if not alguno:
            return False, "No se ingresó ninguna cantidad a recibir"

        items_act = conn.execute(
            "SELECT cantidad, cantidad_recibida FROM importacion_items WHERE importacion_id = ?",
            (imp_id,)
        ).fetchall()

        todo_recibido = all(
            float(it['cantidad_recibida'] or 0) >= float(it['cantidad']) * 0.999
            for it in items_act
        )

        fecha_hoy = datetime.now().strftime('%Y-%m-%d')
        if todo_recibido:
            conn.execute(
                "UPDATE importaciones SET estado='recibido', fecha_llegada=COALESCE(fecha_llegada, ?) WHERE id=?",
                (fecha_hoy, imp_id)
            )
        else:
            conn.execute(
                "UPDATE importaciones SET estado='recibido_parcial' WHERE id=?",
                (imp_id,)
            )

        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        logger.error("registrar_recepcion: %s", e)
        return False, str(e)
    finally:
        conn.close()


# ── Seguimiento de envío ──────────────────────────────────────────────────────

def actualizar_seguimiento(imp_id, naviera=None, numero_tracking=None,
                            eta=None, contenedor=None):
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE importaciones SET naviera=?, numero_tracking=?, eta=?, contenedor=? WHERE id=?",
            (naviera or None, numero_tracking or None, eta or None, contenedor or None, imp_id)
        )
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


# ── Cálculo de costos (sin persistir) ────────────────────────────────────────

def calcular_costos(imp_id):
    conn = get_conn()
    imp = conn.execute(
        "SELECT * FROM importaciones WHERE id = ?", (imp_id,)
    ).fetchone()
    items = conn.execute(
        "SELECT * FROM importacion_items WHERE importacion_id = ? ORDER BY id ASC", (imp_id,)
    ).fetchall()
    total_gastos = conn.execute(
        "SELECT COALESCE(SUM(monto), 0) FROM importacion_gastos WHERE importacion_id = ?",
        (imp_id,)
    ).fetchone()[0]
    conn.close()

    if not imp or not items:
        return []

    tipo_cambio = float(imp['tipo_cambio'])
    total_fob_ars = sum(
        float(it['cantidad']) * float(it['precio_unitario_fob']) * tipo_cambio
        for it in items
    )

    resultados = []
    for it in items:
        subtotal_fob_ars = float(it['cantidad']) * float(it['precio_unitario_fob']) * tipo_cambio

        if total_fob_ars > 0:
            proporcion = subtotal_fob_ars / total_fob_ars
        else:
            proporcion = 1.0 / len(items)

        gastos_asignados = float(total_gastos) * proporcion
        costo_total = subtotal_fob_ars + gastos_asignados
        cantidad = float(it['cantidad'])
        costo_unitario = costo_total / cantidad if cantidad > 0 else 0

        resultados.append({
            'id':                   it['id'],
            'producto_id':          it['producto_id'],
            'descripcion':          it['descripcion'],
            'cantidad':             cantidad,
            'precio_unitario_fob':  float(it['precio_unitario_fob']),
            'subtotal_fob_ars':     subtotal_fob_ars,
            'proporcion':           proporcion,
            'gastos_asignados':     gastos_asignados,
            'costo_total':          costo_total,
            'costo_final_unitario': costo_unitario,
        })

    return resultados


# ── Cerrar importación (aplicar costos a inventario) ─────────────────────────

def cerrar_importacion(imp_id, usuario_id=None):
    conn = get_conn()
    try:
        imp = conn.execute(
            "SELECT * FROM importaciones WHERE id = ?", (imp_id,)
        ).fetchone()
        if not imp:
            return False, "Importación no encontrada"
        if imp['estado'] == 'cerrado':
            return False, "La importación ya está cerrada"

        items = conn.execute(
            "SELECT * FROM importacion_items WHERE importacion_id = ?", (imp_id,)
        ).fetchall()
        if not items:
            return False, "La importación no tiene productos"

        total_gastos = conn.execute(
            "SELECT COALESCE(SUM(monto), 0) FROM importacion_gastos WHERE importacion_id = ?",
            (imp_id,)
        ).fetchone()[0]

        tipo_cambio = float(imp['tipo_cambio'])
        total_fob_ars = sum(
            float(it['cantidad']) * float(it['precio_unitario_fob']) * tipo_cambio
            for it in items
        )

        if total_fob_ars <= 0:
            return False, "El total FOB es cero. Verificá las cantidades y precios."

        for it in items:
            subtotal_fob_ars = float(it['cantidad']) * float(it['precio_unitario_fob']) * tipo_cambio
            proporcion       = subtotal_fob_ars / total_fob_ars
            gastos_asignados = float(total_gastos) * proporcion
            costo_total      = subtotal_fob_ars + gastos_asignados
            cantidad         = float(it['cantidad'])
            costo_unitario   = costo_total / cantidad if cantidad > 0 else 0

            # Usar cantidad_recibida para stock si se hizo recepción parcial
            cant_recibida = float(it['cantidad_recibida'] or 0)
            cant_inventario = int(cant_recibida) if cant_recibida > 0 else int(cantidad)

            conn.execute(
                "UPDATE importacion_items SET costo_final_unitario=? WHERE id=?",
                (costo_unitario, it['id'])
            )

            if it['producto_id']:
                conn.execute(
                    "UPDATE productos SET costo=?, stock=stock+? WHERE id=?",
                    (costo_unitario, cant_inventario, it['producto_id'])
                )
            else:
                sku = f"IMP-{imp_id}-{it['id']}"
                existing = conn.execute(
                    "SELECT id FROM productos WHERE sku = ?", (sku,)
                ).fetchone()
                if not existing:
                    conn.execute(
                        """INSERT INTO productos
                           (sku, descripcion, precio, stock, costo, activo)
                           VALUES (?,?,?,?,?,1)""",
                        (sku, it['descripcion'], costo_unitario, cant_inventario, costo_unitario)
                    )
                    new_prod_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                    conn.execute(
                        "UPDATE importacion_items SET producto_id=? WHERE id=?",
                        (new_prod_id, it['id'])
                    )

        conn.execute(
            """UPDATE importaciones
               SET estado='cerrado', fecha_llegada=COALESCE(fecha_llegada, ?)
               WHERE id=?""",
            (datetime.now().strftime('%Y-%m-%d'), imp_id)
        )
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        logger.error("cerrar_importacion: %s", e)
        return False, str(e)
    finally:
        conn.close()


# ── Cambiar estado ────────────────────────────────────────────────────────────

def cambiar_estado(imp_id, nuevo_estado, fecha_llegada=None):
    estados_validos = [e[0] for e in ESTADOS_IMPORTACION]
    if nuevo_estado not in estados_validos:
        return False, "Estado inválido"
    conn = get_conn()
    try:
        if nuevo_estado in ('recibido', 'recibido_parcial') and fecha_llegada:
            conn.execute(
                "UPDATE importaciones SET estado=?, fecha_llegada=? WHERE id=?",
                (nuevo_estado, fecha_llegada, imp_id)
            )
        else:
            conn.execute(
                "UPDATE importaciones SET estado=? WHERE id=?",
                (nuevo_estado, imp_id)
            )
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


# ── Documentos adjuntos ───────────────────────────────────────────────────────

def get_importacion_documentos(imp_id):
    conn = get_conn()
    rows = conn.execute("""
        SELECT d.*, u.username AS usuario_nombre
        FROM importacion_documentos d
        LEFT JOIN usuarios u ON d.subido_por = u.id
        WHERE d.importacion_id = ?
        ORDER BY d.fecha_subida DESC
    """, (imp_id,)).fetchall()
    conn.close()
    return rows


def agregar_documento(imp_id, tipo_documento, nombre_archivo, ruta_archivo,
                      descripcion=None, usuario_id=None):
    conn = get_conn()
    try:
        fecha = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            """INSERT INTO importacion_documentos
               (importacion_id, tipo_documento, nombre_archivo, ruta_archivo,
                descripcion, subido_por, fecha_subida)
               VALUES (?,?,?,?,?,?,?)""",
            (imp_id, tipo_documento, nombre_archivo, ruta_archivo,
             descripcion, usuario_id, fecha)
        )
        imp = conn.execute(
            "SELECT numero FROM importaciones WHERE id = ?", (imp_id,)
        ).fetchone()
        conn.execute(
            """INSERT INTO audit_log (usuario_id, accion, modulo, detalle, ip, fecha)
               VALUES (?,?,?,?,?,?)""",
            (usuario_id, 'subir_documento', 'importaciones',
             f"Subió '{nombre_archivo}' a {imp['numero'] if imp else imp_id}", '', fecha)
        )
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        logger.error("agregar_documento: %s", e)
        return False, str(e)
    finally:
        conn.close()


def eliminar_documento(doc_id, usuario_id=None):
    """Devuelve (ok, error_o_None, ruta_fisica_o_None)."""
    conn = get_conn()
    try:
        doc = conn.execute(
            """SELECT d.*, i.numero AS imp_numero
               FROM importacion_documentos d
               JOIN importaciones i ON d.importacion_id = i.id
               WHERE d.id = ?""",
            (doc_id,)
        ).fetchone()
        if not doc:
            return False, "Documento no encontrado", None
        ruta = doc['ruta_archivo']
        conn.execute("DELETE FROM importacion_documentos WHERE id = ?", (doc_id,))
        fecha = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            """INSERT INTO audit_log (usuario_id, accion, modulo, detalle, ip, fecha)
               VALUES (?,?,?,?,?,?)""",
            (usuario_id, 'eliminar_documento', 'importaciones',
             f"Eliminó '{doc['nombre_archivo']}' de {doc['imp_numero']}", '', fecha)
        )
        conn.commit()
        return True, None, ruta
    except Exception as e:
        conn.rollback()
        logger.error("eliminar_documento: %s", e)
        return False, str(e), None
    finally:
        conn.close()


# ── Dashboard ─────────────────────────────────────────────────────────────────

def get_dashboard_data():
    hoy = date.today().isoformat()
    mes_actual = hoy[:7]

    conn = get_conn()

    total_mes = conn.execute(
        "SELECT COALESCE(SUM(monto_ars), 0) FROM importacion_pagos WHERE fecha_pago LIKE ?",
        (f"{mes_actual}%",)
    ).fetchone()[0]

    total_historico = conn.execute(
        "SELECT COALESCE(SUM(monto_ars), 0) FROM importacion_pagos"
    ).fetchone()[0]

    en_transito = conn.execute("""
        SELECT i.*, p.nombre AS proveedor_nombre
        FROM importaciones i
        JOIN proveedores p ON i.proveedor_id = p.id
        WHERE i.estado IN ('en_transito', 'en_aduana')
        ORDER BY CASE WHEN i.eta IS NULL THEN 1 ELSE 0 END, i.eta ASC
    """).fetchall()

    pendientes_pago = conn.execute("""
        SELECT i.*, p.nombre AS proveedor_nombre,
               COALESCE((SELECT SUM(cantidad * precio_unitario_fob)
                         FROM importacion_items WHERE importacion_id = i.id), 0) AS total_fob,
               COALESCE((SELECT SUM(monto)
                         FROM importacion_pagos WHERE importacion_id = i.id), 0) AS total_pagado
        FROM importaciones i
        JOIN proveedores p ON i.proveedor_id = p.id
        WHERE i.estado IN ('pendiente_pago', 'pago_parcial')
        ORDER BY i.fecha_pedido DESC
    """).fetchall()

    eta_vencidas = conn.execute("""
        SELECT i.*, p.nombre AS proveedor_nombre
        FROM importaciones i
        JOIN proveedores p ON i.proveedor_id = p.id
        WHERE i.estado IN ('en_transito', 'en_aduana')
          AND i.eta IS NOT NULL AND i.eta < ?
        ORDER BY i.eta ASC
    """, (hoy,)).fetchall()

    por_estado = {r[0]: r[1] for r in conn.execute(
        "SELECT estado, COUNT(*) FROM importaciones GROUP BY estado"
    ).fetchall()}

    conn.close()

    return {
        'total_mes':        total_mes,
        'total_historico':  total_historico,
        'en_transito':      en_transito,
        'pendientes_pago':  pendientes_pago,
        'eta_vencidas':     eta_vencidas,
        'por_estado':       por_estado,
        'hoy':              hoy,
        'mes_actual':       mes_actual,
    }


# ── PDF de la orden ───────────────────────────────────────────────────────────

def generar_pdf_importacion(imp_id):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle,
        Paragraph, Spacer, HRFlowable
    )

    imp = get_importacion(imp_id)
    if not imp:
        return None

    items    = get_importacion_items(imp_id)
    gastos   = get_importacion_gastos(imp_id)
    pagos    = get_importacion_pagos(imp_id)
    costos   = calcular_costos(imp_id)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            title=f"Importación {imp['numero']}",
                            rightMargin=1.8*cm, leftMargin=1.8*cm,
                            topMargin=2*cm, bottomMargin=2*cm)

    styles   = getSampleStyleSheet()
    story    = []

    PRIMARY  = colors.HexColor('#4361ee')
    LIGHT    = colors.HexColor('#f1f3f9')
    BORDER   = colors.HexColor('#dee2e6')
    ALT_ROW  = colors.HexColor('#f8f9fa')
    RED      = colors.HexColor('#dc2626')
    GREEN    = colors.HexColor('#16a34a')

    right_s  = ParagraphStyle('right',  parent=styles['Normal'], alignment=TA_RIGHT)
    center_s = ParagraphStyle('center', parent=styles['Normal'], alignment=TA_CENTER)
    small_g  = ParagraphStyle('small',  parent=styles['Normal'],
                               fontSize=8, textColor=colors.HexColor('#6c757d'))

    # ── Cabecera ──────────────────────────────────────────────────────────────
    hdr = Table([[
        Paragraph("<b><font size='16' color='#4361ee'>COMENDA DECO</font></b>",
                  styles['Normal']),
        Paragraph(
            f"<b><font size='13'>ORDEN DE IMPORTACIÓN</font></b><br/>"
            f"<font size='11'>N° {imp['numero']}</font>",
            right_s
        ),
    ]], colWidths=[10*cm, 7.4*cm])
    hdr.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story += [hdr, HRFlowable(width="100%", thickness=2, color=PRIMARY), Spacer(1, .3*cm)]

    # ── Fechas / Estado ───────────────────────────────────────────────────────
    estado_lbl = dict(ESTADOS_IMPORTACION).get(imp['estado'], imp['estado']).upper()
    tipos_gasto_map = dict(TIPOS_GASTO_IMP)

    fecha_row = Table([[
        Paragraph(f"<b>Fecha pedido:</b> {imp['fecha_pedido']}", styles['Normal']),
        Paragraph(f"<b>Estado:</b> {estado_lbl}", styles['Normal']),
        Paragraph(f"<b>Moneda:</b> {imp['moneda_origen']} × {imp['tipo_cambio']:.2f}", styles['Normal']),
    ]], colWidths=[6*cm, 5*cm, 6.4*cm])
    fecha_row.setStyle(TableStyle([('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))
    story += [fecha_row, Spacer(1, .2*cm)]

    # ── Proveedor ─────────────────────────────────────────────────────────────
    story.append(Paragraph(
        "<b>PROVEEDOR</b>",
        ParagraphStyle('hdr_sec', parent=styles['Normal'],
                       backColor=LIGHT, leftPadding=6, fontSize=10)
    ))
    story.append(Spacer(1, .15*cm))
    prov_txt = f"<b>{imp['proveedor_nombre']}</b>"
    story += [Paragraph(prov_txt, styles['Normal']), Spacer(1, .3*cm)]

    # ── Seguimiento ───────────────────────────────────────────────────────────
    has_tracking = any([imp['naviera'], imp['numero_tracking'], imp['eta'], imp['contenedor']])
    if has_tracking:
        story.append(Paragraph(
            "<b>SEGUIMIENTO DE ENVÍO</b>",
            ParagraphStyle('hdr_sec', parent=styles['Normal'],
                           backColor=LIGHT, leftPadding=6, fontSize=10)
        ))
        story.append(Spacer(1, .15*cm))
        seg_data = []
        if imp['naviera']:        seg_data.append(f"Naviera: {imp['naviera']}")
        if imp['numero_tracking']: seg_data.append(f"Tracking: {imp['numero_tracking']}")
        if imp['contenedor']:     seg_data.append(f"Contenedor: {imp['contenedor']}")
        if imp['eta']:            seg_data.append(f"ETA: {imp['eta']}")
        story += [Paragraph("  |  ".join(seg_data), styles['Normal']), Spacer(1, .3*cm)]

    # ── Tabla de ítems ────────────────────────────────────────────────────────
    story.append(Paragraph(
        "<b>PRODUCTOS DEL PEDIDO</b>",
        ParagraphStyle('hdr_sec', parent=styles['Normal'],
                       backColor=LIGHT, leftPadding=6, fontSize=10)
    ))
    story.append(Spacer(1, .15*cm))

    moneda = imp['moneda_origen']
    tc = float(imp['tipo_cambio'])
    total_fob = 0.0

    if items:
        tbl_data = [[
            Paragraph("<b>Descripción</b>", styles['Normal']),
            Paragraph("<b>Cant.</b>", right_s),
            Paragraph(f"<b>P.Unit FOB ({moneda})</b>", right_s),
            Paragraph(f"<b>Subtotal FOB</b>", right_s),
            Paragraph("<b>Subtotal ARS</b>", right_s),
        ]]
        for it in items:
            sub_fob = float(it['cantidad']) * float(it['precio_unitario_fob'])
            sub_ars = sub_fob * tc
            total_fob += sub_fob
            tbl_data.append([
                Paragraph(it['descripcion'], styles['Normal']),
                Paragraph(f"{it['cantidad']:.0f}", right_s),
                Paragraph(f"{moneda} {it['precio_unitario_fob']:.2f}", right_s),
                Paragraph(f"{moneda} {sub_fob:,.2f}", right_s),
                Paragraph(f"$ {sub_ars:,.0f}".replace(',', '.'), right_s),
            ])
        tbl_data.append([
            Paragraph("<b>TOTAL FOB</b>", right_s),
            '', '', '',
            Paragraph(f"<b>$ {total_fob * tc:,.0f}</b>".replace(',', '.'), right_s),
        ])
        t = Table(tbl_data, colWidths=[6.5*cm, 1.5*cm, 3*cm, 3*cm, 3.4*cm])
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
            ('SPAN', (0, -1), (3, -1)),
        ]))
        story += [t, Spacer(1, .4*cm)]

    # ── Gastos adicionales ────────────────────────────────────────────────────
    if gastos:
        story.append(Paragraph(
            "<b>GASTOS ADICIONALES</b>",
            ParagraphStyle('hdr_sec', parent=styles['Normal'],
                           backColor=LIGHT, leftPadding=6, fontSize=10)
        ))
        story.append(Spacer(1, .15*cm))
        total_gastos = 0.0
        g_data = [[
            Paragraph("<b>Tipo</b>", styles['Normal']),
            Paragraph("<b>Descripción</b>", styles['Normal']),
            Paragraph("<b>Monto (ARS)</b>", right_s),
        ]]
        for g in gastos:
            total_gastos += float(g['monto'])
            g_data.append([
                Paragraph(tipos_gasto_map.get(g['tipo'], g['tipo']), styles['Normal']),
                Paragraph(g['descripcion'] or '—', styles['Normal']),
                Paragraph(f"$ {float(g['monto']):,.0f}".replace(',', '.'), right_s),
            ])
        g_data.append([
            Paragraph("<b>TOTAL GASTOS</b>", right_s),
            '',
            Paragraph(f"<b>$ {total_gastos:,.0f}</b>".replace(',', '.'), right_s),
        ])
        gt = Table(g_data, colWidths=[4*cm, 9*cm, 4.4*cm])
        gt.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), PRIMARY),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, ALT_ROW]),
            ('BACKGROUND', (0, -1), (-1, -1), LIGHT),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('SPAN', (0, -1), (1, -1)),
        ]))
        story += [gt, Spacer(1, .4*cm)]
    else:
        total_gastos = 0.0

    # ── Pagos al proveedor ────────────────────────────────────────────────────
    story.append(Paragraph(
        "<b>PAGOS AL PROVEEDOR</b>",
        ParagraphStyle('hdr_sec', parent=styles['Normal'],
                       backColor=LIGHT, leftPadding=6, fontSize=10)
    ))
    story.append(Spacer(1, .15*cm))

    if pagos:
        total_pagado = sum(float(p['monto']) for p in pagos)
        saldo = float(total_fob) - total_pagado

        p_data = [[
            Paragraph("<b>Fecha</b>", styles['Normal']),
            Paragraph(f"<b>Monto ({moneda})</b>", right_s),
            Paragraph("<b>TC</b>", right_s),
            Paragraph("<b>Monto ARS</b>", right_s),
            Paragraph("<b>Método</b>", styles['Normal']),
        ]]
        for pg in pagos:
            p_data.append([
                Paragraph(pg['fecha_pago'], styles['Normal']),
                Paragraph(f"{float(pg['monto']):,.2f}", right_s),
                Paragraph(f"{float(pg['tipo_cambio']):,.2f}", right_s),
                Paragraph(f"$ {float(pg['monto_ars']):,.0f}".replace(',', '.'), right_s),
                Paragraph(pg['metodo_pago'] or '—', styles['Normal']),
            ])
        p_data.append([
            Paragraph("<b>PAGADO</b>", right_s), '',
            '',
            Paragraph(f"<b>$ {sum(float(pg['monto_ars']) for pg in pagos):,.0f}</b>".replace(',', '.'), right_s),
            '',
        ])
        pt = Table(p_data, colWidths=[3*cm, 3*cm, 2.5*cm, 4*cm, 4.9*cm])
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
            ('SPAN', (0, -1), (2, -1)),
        ]))
        story += [pt, Spacer(1, .2*cm)]

        if saldo > 0.01:
            story.append(Paragraph(
                f"<font color='#dc2626'><b>Saldo pendiente: {moneda} {saldo:,.2f}</b></font>",
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

    # ── Resumen de costos ─────────────────────────────────────────────────────
    story.append(Paragraph(
        "<b>RESUMEN DE COSTOS</b>",
        ParagraphStyle('hdr_sec', parent=styles['Normal'],
                       backColor=LIGHT, leftPadding=6, fontSize=10)
    ))
    story.append(Spacer(1, .15*cm))

    total_final = total_fob * tc + total_gastos
    total_unids = sum(float(it['cantidad']) for it in items) if items else 0
    costo_prom  = total_final / total_unids if total_unids > 0 else 0

    res_data = [
        [Paragraph(f"Total FOB ({moneda})", styles['Normal']),
         Paragraph(f"{moneda} {total_fob:,.2f}", right_s)],
        [Paragraph("Total FOB (ARS)", styles['Normal']),
         Paragraph(f"$ {total_fob * tc:,.0f}".replace(',', '.'), right_s)],
        [Paragraph("Gastos adicionales", styles['Normal']),
         Paragraph(f"$ {total_gastos:,.0f}".replace(',', '.'), right_s)],
        [Paragraph("<b>TOTAL FINAL (ARS)</b>", styles['Normal']),
         Paragraph(f"<b>$ {total_final:,.0f}</b>".replace(',', '.'), right_s)],
        [Paragraph("Costo promedio/unidad", styles['Normal']),
         Paragraph(f"$ {costo_prom:,.0f}".replace(',', '.'), right_s)],
    ]
    rt = Table(res_data, colWidths=[10*cm, 7.4*cm])
    rt.setStyle(TableStyle([
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, ALT_ROW]),
        ('BACKGROUND', (0, 3), (-1, 3), LIGHT),
        ('FONTNAME', (0, 3), (-1, 3), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story += [rt, Spacer(1, .4*cm)]

    # ── Observaciones ─────────────────────────────────────────────────────────
    if imp['observaciones']:
        story.append(Paragraph(
            "<b>OBSERVACIONES</b>",
            ParagraphStyle('hdr_sec', parent=styles['Normal'],
                           backColor=LIGHT, leftPadding=6, fontSize=10)
        ))
        story.append(Spacer(1, .15*cm))
        story.append(Paragraph(imp['observaciones'], styles['Normal']))
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
