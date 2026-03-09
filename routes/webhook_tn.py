# routes/webhook_tn.py

from flask import Blueprint, request, jsonify
import sqlite3
import requests
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

wbhook_tn = Blueprint('webhook_tn', __name__)

STORE_ID = os.getenv("TN_STORE_ID")
ACCESS_TOKEN = os.getenv("TN_ACCESS_TOKEN")

@wbhook_tn.route("/webhook/tiendanube", methods=["POST"])
def webhook_tiendanube():


    data = request.json

    if not data:
        return jsonify({"error": "no data"}), 400

    print("WEBHOOK RECIBIDO:", data)

    evento = data.get("event")
    order_id = data.get("id")

    # Solo procesar orden pagada
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
        "User-Agent": "sistema-inventario"
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
        with sqlite3.connect("negocio.db") as conn:

            cursor = conn.cursor()

            # Evitar duplicados
            cursor.execute(
                "SELECT id FROM ventas WHERE order_id = ?",
                (order_id,)
            )
            if cursor.fetchone():
                print("Orden ya procesada:", order_id)
                return jsonify({"ok": True})

            # Obtener cliente consumidor final
            cursor.execute(
                "SELECT id FROM clientes WHERE nombre = ?",
                ("Consumidor Final",)
            )
            cliente_row = cursor.fetchone()

            if not cliente_row:
                print("Cliente 'Consumidor Final' no existe")
                return jsonify({"error": "cliente no encontrado"}), 500

            cliente_id = cliente_row[0]

            fecha = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            total = float(order.get("total", 0))
            metodo_pago = "Tienda Nube"

            cursor.execute("""
                INSERT INTO ventas 
                (fecha, cliente_id, total, metodo_pago, cuotas, order_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (fecha, cliente_id, total, metodo_pago, None, order_id))

            venta_id = cursor.lastrowid

            for item in order.get("products", []):

                sku = item.get("sku")
                cantidad = int(item.get("cantidad", 0))
                precio_unitario = float(item.get("precio", 0))

                if not sku:
                    print("Producto sin SKU en la orden")
                    continue

                cursor.execute(
                    "SELECT id, stock FROM productos WHERE sku = ?",
                    (sku,)
                )

                producto_row = cursor.fetchone()

                if not producto_row:
                    print(f"Producto no encontrado en DB: {sku}")
                    continue

                producto_id, stock_actual = producto_row

                # Evitar stock negativo
                if stock_actual is not None and stock_actual < cantidad:
                    print(f"Stock insuficiente para SKU {sku}")
                    continue

                # Insertar detalle
                cursor.execute("""
                    INSERT INTO detalle_venta 
                    (venta_id, producto_id, cantidad, precio_unitario)
                    VALUES (?, ?, ?, ?)
                """, (venta_id, producto_id, cantidad, precio_unitario))

                # Actualizar stock
                cursor.execute("""
                    UPDATE productos
                    SET stock = stock - ?
                    WHERE sku = ?
                """, (cantidad, sku))

            conn.commit()

    except Exception as e:
        print("Error procesando webhook:", e)
        return jsonify({"error": "error interno"}), 500

    return jsonify({"ok": True})

