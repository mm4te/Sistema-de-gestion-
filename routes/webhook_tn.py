# routes/webhook_tn.py
import os
import logging
import requests
from datetime import datetime
from flask import Blueprint, request, jsonify
from dotenv import load_dotenv
from models import get_conn

load_dotenv()

logger = logging.getLogger(__name__)

wbhook_tn = Blueprint('webhook_tn', __name__)

STORE_ID = os.getenv("TN_STORE_ID")
ACCESS_TOKEN = os.getenv("TN_ACCESS_TOKEN")
WEBHOOK_SECRET = os.getenv("TN_WEBHOOK_SECRET")


def _cancelar_venta_por_orden(order_id):
    """Cancela la venta local correspondiente a una orden de Tiendanube.

    Mismo flujo que la cancelación manual: estado → stock → caja → auditoría,
    todo en un único commit. Si la venta no existe o ya está cancelada, no hace nada.
    """
    conn = get_conn()
    try:
        venta = conn.execute(
            "SELECT id, total, estado, metodo_pago FROM ventas WHERE order_id = ?",
            (str(order_id),)
        ).fetchone()

        if not venta:
            logger.info("Cancelación TN: orden %s no existe en el sistema, ignorando", order_id)
            return

        if venta['estado'] == 'cancelada':
            logger.info("Cancelación TN: venta #%s (orden %s) ya está cancelada, ignorando",
                        venta['id'], order_id)
            return

        venta_id = venta['id']

        items = conn.execute(
            "SELECT producto_id, cantidad FROM detalle_venta WHERE venta_id = ?",
            (venta_id,)
        ).fetchall()

        conn.execute(
            "UPDATE ventas SET estado = 'cancelada', motivo_cancelacion = ? WHERE id = ?",
            ("Cancelación automática por Tiendanube", venta_id)
        )
        for item in items:
            conn.execute(
                "UPDATE productos SET stock = stock + ? WHERE id = ?",
                (item['cantidad'], item['producto_id'])
            )

        from services.caja_service import registrar_movimiento_en_conn
        registrar_movimiento_en_conn(
            conn, 'egreso', 'cancelacion', venta_id,
            f"Cancelación automática Tienda Nube #{order_id}",
            venta['total'], venta['metodo_pago']
        )

        conn.commit()
        logger.info("Venta #%s (orden TN %s) cancelada automáticamente, stock revertido", venta_id, order_id)

        try:
            from services.usuarios_service import registrar_auditoria
            registrar_auditoria(
                None, 'tiendanube',
                'cancelar_venta', 'ventas',
                detalle=f"Venta #{venta_id} cancelada automáticamente por Tiendanube. "
                        f"Orden TN: {order_id}. Total: ${venta['total']:.2f}."
            )
        except Exception:
            pass

    except Exception:
        conn.rollback()
        logger.exception("Error cancelando venta por orden TN %s", order_id)
    finally:
        conn.close()


def _fetch_order(order_id):
    """Obtiene la orden desde la API de Tiendanube. Devuelve el dict o None."""
    if not STORE_ID or not ACCESS_TOKEN:
        logger.error("Variables de entorno TN_STORE_ID / TN_ACCESS_TOKEN no configuradas")
        return None
    url = f"https://api.tiendanube.com/v1/{STORE_ID}/orders/{order_id}"
    headers = {
        "Authentication": f"bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "Comenda App (mateopatatian@gmail.com)"
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
    except requests.RequestException as e:
        logger.error("Error conectando con TiendaNube para orden %s: %s", order_id, e)
        return None
    if r.status_code != 200:
        logger.error("Error obteniendo orden %s: status %s - %s", order_id, r.status_code, r.text)
        return None
    return r.json()


def obtener_o_crear_cliente(cursor, order):
    customer = order.get("customer") or {}
    if not isinstance(customer, dict):
        customer = {}

    nombre = str(customer.get("name") or "").strip()
    email = str(customer.get("email") or order.get("contact_email") or "").strip()
    telefono = str(customer.get("phone") or order.get("contact_phone") or "").strip()
    dni = str(customer.get("identification") or "").strip()

    if not nombre:
        nombre = "Consumidor Final (TN)"

    logger.info("Comprador: %s | DNI: %s | Email: %s", nombre, dni, email)

    cliente_row = None
    if dni:
        cursor.execute("SELECT id FROM clientes WHERE dni = ?", (dni,))
        cliente_row = cursor.fetchone()
    if not cliente_row and email:
        cursor.execute("SELECT id FROM clientes WHERE email = ?", (email,))
        cliente_row = cursor.fetchone()

    if cliente_row:
        logger.info("Cliente existente: id=%s", cliente_row['id'])
        return cliente_row["id"]

    cursor.execute("""
        INSERT INTO clientes (nombre, telefono, dni, email, tipo)
        VALUES (?, ?, ?, ?, 0)
    """, (nombre, telefono, dni or None, email or None))
    nuevo_id = cursor.lastrowid
    logger.info("Nuevo cliente creado: id=%s, nombre=%s", nuevo_id, nombre)
    return nuevo_id


@wbhook_tn.route("/webhook/tiendanube", methods=["POST"])
def webhook_tiendanube():
    # Validar secreto del webhook si está configurado
    if WEBHOOK_SECRET:
        token = request.headers.get('X-Linkedstore-Token', '')
        if token != WEBHOOK_SECRET:
            logger.warning("Webhook recibido con token inválido")
            return jsonify({"error": "unauthorized"}), 401

    data = request.json
    if not data:
        return jsonify({"error": "no data"}), 400

    evento = data.get("event")
    order_id = data.get("id")

    logger.info("Webhook Tiendanube recibido: %s - orden %s", evento, order_id)

    # ── Cancelación directa ───────────────────────────────────────────────────
    if evento == "order/cancelled":
        _cancelar_venta_por_orden(order_id)
        return jsonify({"ok": True})

    # ── Actualización: verificar si la orden quedó cancelada ──────────────────
    if evento == "order/updated":
        order = _fetch_order(order_id)
        if order:
            status         = order.get("status", "")
            payment_status = order.get("payment_status", "")
            if status == "cancelled" or payment_status in ("refunded", "voided"):
                logger.info(
                    "Orden %s figura cancelada en TN (status=%s, payment=%s), procesando",
                    order_id, status, payment_status
                )
                _cancelar_venta_por_orden(order_id)
        return jsonify({"ok": True})

    # ── Orden pagada: registrar venta ─────────────────────────────────────────
    if evento != "order/paid":
        return jsonify({"ok": True})

    if not STORE_ID or not ACCESS_TOKEN:
        logger.error("Variables de entorno TN_STORE_ID / TN_ACCESS_TOKEN no configuradas")
        return jsonify({"error": "configuracion incompleta"}), 500

    order = _fetch_order(order_id)
    if not order:
        return jsonify({"error": "no se pudo obtener la orden"}), 500

    try:
        conn = get_conn()
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM ventas WHERE order_id = ?", (str(order_id),))
        if cursor.fetchone():
            logger.info("Orden ya procesada: %s", order_id)
            conn.close()
            return jsonify({"ok": True})

        cliente_id = obtener_o_crear_cliente(cursor, order)

        fecha = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        total = float(order.get("total", 0))

        cursor.execute("""
            INSERT INTO ventas (fecha, cliente_id, total, metodo_pago, cuotas, order_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (fecha, cliente_id, total, "Tienda Nube", None, str(order_id)))

        venta_id = cursor.lastrowid

        for item in order.get("products", []):
            sku = item.get("sku")
            cantidad = int(item.get("quantity") or 0)
            precio_unitario = float(item.get("price") or 0)

            if not sku or cantidad == 0:
                logger.warning("Producto sin SKU o cantidad 0 en orden %s, omitido", order_id)
                continue

            cursor.execute("SELECT id, stock FROM productos WHERE sku = ?", (sku,))
            producto_row = cursor.fetchone()

            if not producto_row:
                logger.warning("SKU %s no encontrado en DB (orden %s)", sku, order_id)
                continue

            producto_id = producto_row["id"]
            stock_actual = producto_row["stock"]

            if stock_actual is not None and stock_actual < cantidad:
                logger.warning(
                    "Stock insuficiente para SKU %s: tiene %s, necesita %s",
                    sku, stock_actual, cantidad
                )
                continue

            cursor.execute("""
                INSERT INTO detalle_venta (venta_id, producto_id, cantidad, precio_unitario)
                VALUES (?, ?, ?, ?)
            """, (venta_id, producto_id, cantidad, precio_unitario))

            cursor.execute(
                "UPDATE productos SET stock = stock - ? WHERE sku = ?",
                (cantidad, sku)
            )

        # Registrar ingreso en caja (misma transacción)
        from services.caja_service import registrar_movimiento_en_conn
        registrar_movimiento_en_conn(
            conn, 'ingreso', 'venta', venta_id,
            f"Venta Tienda Nube #{order_id}",
            total, 'Tienda Nube'
        )

        conn.commit()
        conn.close()
        logger.info("Orden %s procesada correctamente", order_id)

    except Exception:
        logger.exception("Error procesando webhook para orden %s", order_id)
        return jsonify({"error": "error interno"}), 500

    return jsonify({"ok": True})
