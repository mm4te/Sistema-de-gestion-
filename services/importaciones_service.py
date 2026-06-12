# services/importaciones_service.py
import logging
from datetime import datetime

from models import get_conn
from services.caja_service import registrar_movimiento_en_conn

logger = logging.getLogger(__name__)

ESTADOS_IMPORTACION = [
    ('pendiente_pago',      'Pendiente de pago'),
    ('pagado',              'Pagado'),
    ('en_transito',         'En tránsito'),
    ('en_aduana',           'En aduana'),
    ('recibido',            'Recibido'),
    ('cerrado',             'Cerrado'),
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

def listar_proveedores():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM proveedores ORDER BY nombre ASC").fetchall()
    conn.close()
    return rows


def get_proveedor(proveedor_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM proveedores WHERE id = ?", (proveedor_id,)).fetchone()
    conn.close()
    return row


def crear_proveedor(nombre, pais=None, contacto=None, telefono=None, email=None, notas=None):
    if not nombre:
        return False, "El nombre es requerido"
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO proveedores (nombre, pais, contacto, telefono, email, notas) VALUES (?,?,?,?,?,?)",
            (nombre, pais, contacto, telefono, email, notas)
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
                          telefono=None, email=None, notas=None):
    if not nombre:
        return False, "El nombre es requerido"
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE proveedores SET nombre=?, pais=?, contacto=?, telefono=?, email=?, notas=? WHERE id=?",
            (nombre, pais, contacto, telefono, email, notas, proveedor_id)
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
    tiene = conn.execute(
        "SELECT COUNT(*) FROM importaciones WHERE proveedor_id = ?", (proveedor_id,)
    ).fetchone()[0]
    conn.close()
    if tiene > 0:
        return False, "El proveedor tiene importaciones asociadas y no puede eliminarse"
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


# ── Registrar pago al proveedor ───────────────────────────────────────────────

def registrar_pago(imp_id, tipo_cambio, fecha_pago=None,
                    metodo_pago=None, usuario_id=None):
    conn = get_conn()
    try:
        imp = conn.execute(
            "SELECT * FROM importaciones WHERE id = ?", (imp_id,)
        ).fetchone()
        if not imp:
            return False, "Importación no encontrada"
        if imp['estado'] != 'pendiente_pago':
            return False, "Solo se puede registrar el pago en estado 'pendiente_pago'"

        total_fob_moneda = conn.execute(
            """SELECT COALESCE(SUM(cantidad * precio_unitario_fob), 0)
               FROM importacion_items WHERE importacion_id = ?""",
            (imp_id,)
        ).fetchone()[0]

        if total_fob_moneda <= 0:
            return False, "La importación no tiene productos. Agregá items antes de registrar el pago."

        if not fecha_pago:
            fecha_pago = datetime.now().strftime('%Y-%m-%d')

        total_ars = float(total_fob_moneda) * float(tipo_cambio)

        conn.execute(
            "UPDATE importaciones SET estado='pagado', tipo_cambio=?, fecha_pago=? WHERE id=?",
            (tipo_cambio, fecha_pago, imp_id)
        )
        registrar_movimiento_en_conn(
            conn, 'egreso', 'importacion', imp_id,
            f"Pago proveedor {imp['numero']} ({imp['moneda_origen']} {total_fob_moneda:,.2f} × {tipo_cambio})",
            total_ars, metodo_pago, usuario_id
        )
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        logger.error("registrar_pago: %s", e)
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
            'id':                  it['id'],
            'producto_id':         it['producto_id'],
            'descripcion':         it['descripcion'],
            'cantidad':            cantidad,
            'precio_unitario_fob': float(it['precio_unitario_fob']),
            'subtotal_fob_ars':    subtotal_fob_ars,
            'proporcion':          proporcion,
            'gastos_asignados':    gastos_asignados,
            'costo_total':         costo_total,
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

            conn.execute(
                "UPDATE importacion_items SET costo_final_unitario=? WHERE id=?",
                (costo_unitario, it['id'])
            )

            if it['producto_id']:
                conn.execute(
                    "UPDATE productos SET costo=?, stock=stock+? WHERE id=?",
                    (costo_unitario, int(cantidad), it['producto_id'])
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
                        (sku, it['descripcion'], costo_unitario, int(cantidad), costo_unitario)
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


def cambiar_estado(imp_id, nuevo_estado, fecha_llegada=None):
    estados_validos = [e[0] for e in ESTADOS_IMPORTACION]
    if nuevo_estado not in estados_validos:
        return False, "Estado inválido"
    conn = get_conn()
    try:
        if nuevo_estado == 'recibido' and fecha_llegada:
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
