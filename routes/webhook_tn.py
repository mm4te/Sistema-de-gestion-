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

    logger.info("Webhook recibido: evento=%s, order_id=%s", evento, order_id)

    if evento != "order/paid":
        return jsonify({"ok": True})

    if not STORE_ID or not ACCESS_TOKEN:
        logger.error("Variables de entorno TN_STORE_ID / TN_ACCESS_TOKEN no configuradas")
        return jsonify({"error": "configuracion incompleta"}), 500

    url = f"https://api.tiendanube.com/v1/{STORE_ID}/orders/{order_id}"
    headers = {
        "Authentication": f"bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "Comenda App (mateopatatian@gmail.com)"
    }

    try:
        r = requests.get(url, headers=headers, timeout=10)
    except requests.RequestException as e:
        logger.error("Error conectando con TiendaNube: %s", e)
        return jsonify({"error": "conexion fallida"}), 500

    if r.status_code != 200:
        logger.error("Error obteniendo orden %s: %s", order_id, r.text)
        return jsonify({"error": "no se pudo obtener la orden"}), 500

    order = r.json()

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

        conn.commit()
        conn.close()
        logger.info("Orden %s procesada correctamente", order_id)

    except Exception as e:
        logger.exception("Error procesando webhook para orden %s", order_id)
        return jsonify({"error": "error interno"}), 500

    return jsonify({"ok": True})
