# routes/webhook_tn.py
import os
import requests
from datetime import datetime
from flask import Blueprint, request, jsonify
from dotenv import load_dotenv
from models import get_conn

load_dotenv()

wbhook_tn = Blueprint('webhook_tn', __name__)

STORE_ID     = os.getenv("TN_STORE_ID")
ACCESS_TOKEN = os.getenv("TN_ACCESS_TOKEN")


def obtener_o_crear_cliente(cursor, order):
    """
    Busca el cliente por DNI o email.
    Si no existe, lo crea como minorista con los datos de TiendaNube.
    Devuelve el cliente_id.
    Estructura real de TN: order.customer.name, .identification, .phone, .email
    """
    customer = order.get("customer") or {}
    print("ORDER COMPLETA:", order)
    if not isinstance(customer, dict):
        customer = {}

    # Campos reales según doc de TiendaNube
    nombre   = str(customer.get("name") or "").strip()
    email    = str(customer.get("email") or order.get("contact_email") or "").strip()
    telefono = str(customer.get("phone") or order.get("contact_phone") or "").strip()
    dni      = str(customer.get("identification") or "").strip()

    if not nombre:
        nombre = "Consumidor Final (TN)"

    print(f"Comprador: {nombre} | DNI: {dni} | Email: {email} | Tel: {telefono}")

    # Buscar por DNI primero, luego por email
    cliente_row = None
    if dni:
        cursor.execute("SELECT id FROM clientes WHERE dni = ?", (dni,))
        cliente_row = cursor.fetchone()
    if not cliente_row and email:
        cursor.execute("SELECT id FROM clientes WHERE email = ?", (email,))
        cliente_row = cursor.fetchone()

    if cliente_row:
        print(f"Cliente existente encontrado: id={cliente_row['id']}")
        return cliente_row["id"]

    # Crear nuevo cliente minorista
    cursor.execute("""
        INSERT INTO clientes (nombre, telefono, dni, email, tipo)
        VALUES (?, ?, ?, ?, 0)
    """, (nombre, telefono, dni or None, email or None))

    nuevo_id = cursor.lastrowid
    print(f"Nuevo cliente creado: id={nuevo_id}, nombre={nombre}")
    return nuevo_id


@wbhook_tn.route("/webhook/tiendanube", methods=["POST"])
def webhook_tiendanube():
    data = request.json
    if not data:
        return jsonify({"error": "no data"}), 400

    print("WEBHOOK RECIBIDO:", data)

    evento   = data.get("event")
    order_id = data.get("id")

    if evento != "order/paid":
        return jsonify({"ok": True})

    if not STORE_ID or not ACCESS_TOKEN:
        print("ERROR: variables de entorno no configuradas")
        return jsonify({"error": "configuracion incompleta"}), 500

    # Obtener orden completa desde la API
    url = f"https://api.tiendanube.com/v1/{STORE_ID}/orders/{order_id}"
    headers = {
        "Authentication": f"bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "Comenda App (mateopatatian@gmail.com)"
    }

    try:
        r = requests.get(url, headers=headers)
    except Exception as e:
        print("Error conectando con Tiendanube:", e)
        return jsonify({"error": "conexion fallida"}), 500

    if r.status_code != 200:
        print("Error obteniendo orden:", r.text)
        return jsonify({"error": "no se pudo obtener la orden"}), 500

    order = r.json()

    try:
        conn   = get_conn()
        cursor = conn.cursor()

        # Evitar duplicados
        cursor.execute("SELECT id FROM ventas WHERE order_id = ?", (str(order_id),))
        if cursor.fetchone():
            print("Orden ya procesada:", order_id)
            conn.close()
            return jsonify({"ok": True})

        # Obtener o crear cliente con los datos del comprador
        cliente_id = obtener_o_crear_cliente(cursor, order)

        fecha = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        total = float(order.get("total", 0))

        cursor.execute("""
            INSERT INTO ventas (fecha, cliente_id, total, metodo_pago, cuotas, order_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (fecha, cliente_id, total, "Tienda Nube", None, str(order_id)))

        venta_id = cursor.lastrowid

        for item in order.get("products", []):
            sku             = item.get("sku")
            cantidad        = int(item.get("quantity") or 0)
            precio_unitario = float(item.get("price") or 0)

            if not sku or cantidad == 0:
                print(f"Producto sin SKU o cantidad 0, se omite: {item}")
                continue

            cursor.execute("SELECT id, stock FROM productos WHERE sku = ?", (sku,))
            producto_row = cursor.fetchone()

            if not producto_row:
                print(f"Producto no encontrado en DB: {sku}")
                continue

            producto_id  = producto_row["id"]
            stock_actual = producto_row["stock"]

            if stock_actual is not None and stock_actual < cantidad:
                print(f"Stock insuficiente para SKU {sku} (tiene {stock_actual}, necesita {cantidad})")
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

    except Exception as e:
        print("Error procesando webhook:", e)
        return jsonify({"error": "error interno"}), 500

    return jsonify({"ok": True})