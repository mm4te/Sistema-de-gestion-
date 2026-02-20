# services/tiendanube_service.py

import requests
import sqlite3

TOKEN = "c2883f94ba3987c74d5246e716d89b40d35bdf30"
STORE_ID = "7324186"


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

    for p in productos:

        product_id = p["id"]
        nombre = p["name"]["es"] if "es" in p["name"] else list(p["name"].values())[0]

        for variante in p.get("variants", []):

            variant_id = variante.get("id")
            sku = variante.get("sku")
            precio = float(variante.get("price") or 0)
            stock_raw = variante.get("stock")

            if stock_raw is None:
                stock = None
            else:
                stock = int(stock_raw)

            cursor.execute("""
                SELECT 1 FROM productos_tiendanube 
                WHERE variant_id = ?
            """, (variant_id,))
            existe = cursor.fetchone()

            if not existe:
                cursor.execute("""
                    INSERT INTO productos_tiendanube 
                    (product_id, variant_id, nombre, sku, precio, stock)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (product_id, variant_id, nombre, sku, precio, stock))

    conn.commit()
    conn.close()

    return {"ok": True, "mensaje": "Productos importados correctamente 🚀"}


# ==========================================
# ACTUALIZAR STOCK EN TIENDANUBE
# ==========================================

def actualizar_stock_tn_service(variant_id, nuevo_stock):

    # 1️⃣ Buscar product_id en la base
    conn = sqlite3.connect("negocio.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT tienda_id 
        FROM productos_tiendanube 
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
        "User-Agent": "SistemaGestion (tuemail@email.com)",
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
        UPDATE productos_tiendanube
        SET stock = ?
        WHERE variant_id = ?
    """, (nuevo_stock, variant_id))

    conn.commit()
    conn.close()

    return {"ok": True, "mensaje": "Stock actualizado correctamente"}
