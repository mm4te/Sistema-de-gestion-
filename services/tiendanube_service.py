# services/tiendanube_service.py

import requests
import sqlite3
import os
from dotenv import load_dotenv

# Load variables from .env file
load_dotenv()
TOKEN = os.getenv("TN_ACCESS_TOKEN")
STORE_ID = os.getenv("TN_STORE_ID")


# ==========================================
# IMPORTAR PRODUCTOS DESDE TIENDANUBE
# ==========================================

def importar_productos_tn():

    headers = {
        "Authentication": f"bearer {TOKEN}",
        "User-Agent": "Comenda App (mateopatatian@gmail.com)"
    }

    url = f"https://api.tiendanube.com/v1/{STORE_ID}/products"
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        return {"ok": False, "error": response.text}

    productos = response.json()

    conn = sqlite3.connect("negocio.db")
    cursor = conn.cursor()

    count = 0
    for p in productos:

        nombre = p["name"].get("es") or list(p["name"].values())[0]

        for variante in p.get("variants", []):

            variant_id = str(variante.get("id"))
            sku = variante.get("sku") or f"TN_{variant_id}"
            precio = float(variante.get("price") or 0)
            stock_raw = variante.get("stock")

            # Si viene None lo dejamos en 0 (no podés guardar NULL porque stock es NOT NULL)
            stock = int(stock_raw) if stock_raw is not None else 0

            cursor.execute("""
                INSERT INTO productos 
                (sku, descripcion, precio, stock, variant_id)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(sku) DO UPDATE SET
                    descripcion = excluded.descripcion,
                    precio = excluded.precio,
                    stock = excluded.stock,
                    variant_id = excluded.variant_id
            """, (sku, nombre, precio, stock, variant_id))

            count += 1

    conn.commit()
    conn.close()


    return {"ok": True, "mensaje": f"{count} productos sincronizados correctamente 🚀"}
# ==========================================
# ACTUALIZAR STOCK EN TIENDANUBE
# ==========================================

def actualizar_stock_tn_service(variant_id, nuevo_stock):
    print("Enviando a Tiendanube:")
    print("Variant ID:", variant_id)
    print("Nuevo stock:", nuevo_stock)
    # 1️⃣ Buscar product_id en la base
    conn = sqlite3.connect("negocio.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT product_id 
        FROM productos
        WHERE variant_id = ?
    """, (variant_id,))

    row = cursor.fetchone()

    if not row:
        conn.close()
        return {"ok": False, "error": "Variant no encontrada en base"}

    product_id = row[0]
    conn.close()

    # 2️⃣ Llamar a la API
    url = f"https://api.tiendanube.com/2025-03/{STORE_ID}/products/stock-price"

    headers = {
        "Authentication": f"bearer {TOKEN}",
        "User-Agent": "Comenda App (mateopatatian@gmail.com)",
        "Content-Type": "application/json"
    }

    data = [
        {
            "id": int(product_id),
            "variants": [
                {
                    "id": int(variant_id),
                    "inventory_levels": [
                        {
                            "stock": nuevo_stock
                        }
                    ]
                }
            ]
        }
    ]

    response = requests.patch(url, json=data, headers=headers)

    if response.status_code not in (200, 204):
        return {"ok": False, "error": response.text}

    # 3️⃣ Actualizar base local
    conn = sqlite3.connect("negocio.db")
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE productos
        SET stock = ?
        WHERE variant_id = ?
    """, (nuevo_stock, variant_id))

    conn.commit()
    conn.close()

    return {"ok": True, "mensaje": "Stock actualizado correctamente"}
