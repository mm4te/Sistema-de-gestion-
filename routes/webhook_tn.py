# routes/webhook_tn.py

from flask import Blueprint, request, jsonify
import sqlite3
import requests
from datetime import datetime
import os
from dotenv import load_dotenv

# Load variables from .env file
load_dotenv()
wbhook_tn = Blueprint('webhook_tn', __name__)

# CONFIGURACION

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

    # solo procesamos orden pagada
    if evento != "order/paid":
        return jsonify({"ok": True})

    # obtener orden completa desde la API
    url = f"https://api.tiendanube.com/v1/{STORE_ID}/orders/{order_id}"

    headers = {
        "Authentication": f"bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "sistema-inventario"
    }

    r = requests.get(url, headers=headers)

    if r.status_code != 200:
        print("Error obteniendo orden:", r.text)
        return jsonify({"error": "no se pudo obtener la orden"}), 500

    order = r.json()

    conn = sqlite3.connect("negocio.db")
    cursor = conn.cursor()

    # Obtener cliente_id del Consumidor Final
    cursor.execute("SELECT id FROM clientes WHERE nombre = ?", ("Consumidor Final",))
    cliente_row = cursor.fetchone()
    if not cliente_row:
        conn.close()
        return jsonify({"error": "cliente no encontrado"}), 500
    cliente_id = cliente_row[0]

    # Registrar venta
    fecha = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    total = order.get("total", 0)
    metodo_pago = "Tienda Nube"

    cursor.execute("""
        INSERT INTO ventas (fecha, cliente_id, total, metodo_pago, cuotas) 
        VALUES (?, ?, ?, ?, ?)
    """, (fecha, cliente_id, total, metodo_pago, None))

    venta_id = cursor.lastrowid

    for item in order.get("products", []):

        sku = item.get("sku")
        cantidad = int(item.get("quantity", 0))  # Corregido: quantity en lugar de cantidad
        precio_unitario = float(item.get("price", 0))

        # Obtener producto_id por sku
        cursor.execute("SELECT id FROM productos WHERE sku = ?", (sku,))
        producto_row = cursor.fetchone()
        if producto_row:
            producto_id = producto_row[0]

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
    conn.close()

    return jsonify({"ok": True})

