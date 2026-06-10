# services/tiendanube_service.py
import logging
import os
import sqlite3

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

TOKEN = os.getenv("TN_ACCESS_TOKEN")
STORE_ID = os.getenv("TN_STORE_ID")

# Ruta absoluta a la DB (services/ está un nivel dentro del proyecto)
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB_PATH = os.path.join(_BASE_DIR, 'negocio.db')


def _get_conn():
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


_HEADERS = {
    "Authentication": f"bearer {TOKEN}",
    "User-Agent": "Comenda App (mateopatatian@gmail.com)",
    "Content-Type": "application/json",
}


# ==========================================
# IMPORTAR PRODUCTOS DESDE TIENDANUBE
# ==========================================

def importar_productos_tn():
    headers = {
        "Authentication": f"bearer {TOKEN}",
        "User-Agent": "Comenda App (mateopatatian@gmail.com)",
    }

    url = f"https://api.tiendanube.com/v1/{STORE_ID}/products"
    try:
        response = requests.get(url, headers=headers, timeout=15)
    except requests.RequestException as e:
        logger.error("Error conectando con TiendaNube: %s", e)
        return {"ok": False, "error": str(e)}

    if response.status_code != 200:
        logger.error("TiendaNube respondió %s: %s", response.status_code, response.text)
        return {"ok": False, "error": response.text}

    productos = response.json()
    conn = _get_conn()
    cursor = conn.cursor()
    count = 0

    for p in productos:
        nombre = p["name"].get("es") or list(p["name"].values())[0]
        imagen_url = None
        if p.get("images"):
            for img in p["images"]:
                if str(img.get("product_id")) == str(p.get("id")):
                    imagen_url = img.get("src")
                    break

        for variante in p.get("variants", []):
            variant_id = str(variante.get("id"))
            sku = variante.get("sku") or f"TN_{variant_id}"
            precio = float(variante.get("price") or 0)
            stock_raw = variante.get("stock")
            product_id = str(variante.get("product_id"))
            p_price = variante.get("promotional_price")
            promotional_price = float(p_price) if p_price is not None else None
            barcode = variante.get("barcode") or ""
            stock = int(stock_raw) if stock_raw is not None else None

            cursor.execute("""
                INSERT INTO productos
                (sku, descripcion, precio, stock, variant_id, product_id,
                 promotional_price, barcode, imagen_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sku) DO UPDATE SET
                    descripcion       = excluded.descripcion,
                    precio            = excluded.precio,
                    stock             = excluded.stock,
                    variant_id        = excluded.variant_id,
                    product_id        = excluded.product_id,
                    promotional_price = excluded.promotional_price,
                    barcode           = excluded.barcode,
                    imagen_url        = excluded.imagen_url
            """, (sku, nombre, precio, stock, variant_id, product_id,
                  promotional_price, barcode, imagen_url))
            count += 1

    conn.commit()
    conn.close()
    logger.info("Importación completada: %d productos sincronizados", count)
    return {"ok": True, "mensaje": f"{count} productos sincronizados correctamente 🚀"}


# ==========================================
# ACTUALIZAR STOCK EN TIENDANUBE
# ==========================================

def actualizar_stock_tn_service(variant_id, nuevo_stock):
    conn = _get_conn()
    row = conn.execute(
        "SELECT product_id FROM productos WHERE variant_id = ?", (variant_id,)
    ).fetchone()
    conn.close()

    if not row:
        logger.warning("actualizar_stock: variant_id %s no encontrado en DB", variant_id)
        return {"ok": False, "error": "Variant no encontrada en base"}

    product_id = row["product_id"]

    url = f"https://api.tiendanube.com/2025-03/{STORE_ID}/products/stock-price"
    data = [{
        "id": int(product_id),
        "variants": [{
            "id": int(variant_id),
            "inventory_levels": [{"stock": nuevo_stock}]
        }]
    }]

    try:
        response = requests.patch(url, json=data, headers=_HEADERS, timeout=10)
    except requests.RequestException as e:
        logger.error("Error actualizando stock en TN: %s", e)
        return {"ok": False, "error": str(e)}

    if response.status_code not in (200, 204):
        logger.error("Error actualizando stock en TN: %s", response.text)
        return {"ok": False, "error": response.text}

    conn = _get_conn()
    conn.execute(
        "UPDATE productos SET stock = ? WHERE variant_id = ?", (nuevo_stock, variant_id)
    )
    conn.commit()
    conn.close()

    logger.info("Stock actualizado: variant_id=%s, stock=%s", variant_id, nuevo_stock)
    return {"ok": True, "mensaje": "Stock actualizado correctamente"}


# ==========================================
# ACTUALIZAR PRECIO EN TIENDANUBE
# ==========================================

def actualizar_precio_tn_service(variant_id, product_id, nuevo_precio):
    url = f"https://api.tiendanube.com/2025-03/{STORE_ID}/products/stock-price"
    data = [{
        "id": int(product_id),
        "variants": [{
            "id": int(variant_id),
            "price": str(nuevo_precio)
        }]
    }]

    try:
        response = requests.patch(url, json=data, headers=_HEADERS, timeout=10)
    except requests.RequestException as e:
        logger.error("Error actualizando precio en TN: %s", e)
        return {"ok": False, "error": str(e)}

    if response.status_code not in (200, 204):
        logger.error("Error actualizando precio en TN: %s", response.text)
        return {"ok": False, "error": response.text}

    logger.info("Precio actualizado: variant_id=%s, precio=%s", variant_id, nuevo_precio)
    return {"ok": True, "mensaje": "Precio actualizado en TiendaNube"}
