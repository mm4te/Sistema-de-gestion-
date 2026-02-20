import requests
from flask import Blueprint, jsonify
import sqlite3

tiendanube_bp = Blueprint("tiendanube", __name__)

TOKEN = "c2883f94ba3987c74d5246e716d89b40d35bdf30"
STORE_ID = "7324186"

@tiendanube_bp.route("/importar-productos-tiendanube")
def importar_productos():

    headers = {
        "Authentication": f"bearer {TOKEN}",
        "User-Agent": "Comenda App (mateopatatian@gmail.com)"
    }

    url = f"https://api.tiendanube.com/v1/{STORE_ID}/products"
    response = requests.get(url, headers=headers)

    productos = response.json()

    conn = sqlite3.connect("negocio.db")
    cursor = conn.cursor()

    for p in productos:

        tienda_id = p["id"]
        nombre = p["name"]["es"] if "es" in p["name"] else list(p["name"].values())[0]

        for variante in p.get("variants", []):

            variant_id = variante.get("id")
            sku = variante.get("sku")
            precio = float(variante.get("price") or 0)
            stock_raw = variante.get("stock")

            if stock_raw is None:
                stock = None  # infinito
            else:
                stock = int(stock_raw)


            cursor.execute("""
                SELECT * FROM productos_tiendanube 
                WHERE variant_id = ?
            """, (variant_id,))
            existe = cursor.fetchone()

            if not existe:
                cursor.execute("""
                    INSERT INTO productos_tiendanube 
                    (tienda_id, variant_id, nombre, sku, precio, stock)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (tienda_id, variant_id, nombre, sku, precio, stock))


    conn.commit()
    conn.close()

    return "Productos importados correctamente 🚀"
@tiendanube_bp.route("/actualizar-stock-tn/<variant_id>/<int:nuevo_stock>")
def actualizar_stock_tn(variant_id, nuevo_stock):

    import sqlite3
    import requests

    # 🔎 1) Buscar product_id en la base
    conn = sqlite3.connect("negocio.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT product_id 
        FROM productos_tiendanube 
        WHERE variant_id = ?
    """, (variant_id,))

    row = cursor.fetchone()

    if not row:
        conn.close()
        return {"error": "Variant no encontrada en base"}, 404

    product_id = row[0]
    conn.close()

    # 🔥 2) Llamar a la API correctamente
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

    print("Status:", response.status_code)
    print("Response:", response.text)

    # 🔁 3) Si salió bien, actualizar tu base local
    if response.status_code in (200, 204):

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

    else:
        return {
            "ok": False,
            "error": response.text
        }, response.status_code
