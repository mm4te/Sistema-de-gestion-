# services/stock_sync.py

import sqlite3
from services.tiendanube_service import actualizar_stock_tn_service


def sincronizar_stock_por_venta(variant_id, cantidad_vendida):
    """
    Se ejecuta después de registrar una venta.
    Descuenta stock local y lo sincroniza con Tiendanube.
    """

    conn = sqlite3.connect("negocio.db")
    cursor = conn.cursor()

    # 1️⃣ Obtener stock actual
    cursor.execute("""
        SELECT stock 
        FROM productos
        WHERE variant_id = ?
    """, (variant_id,))

    row = cursor.fetchone()

    if not row:
        conn.close()
        return {"ok": False, "error": "Producto no encontrado"}

    stock_actual = row[0]

    if stock_actual is None:
        # stock infinito, no sincronizamos
        conn.close()
        return {"ok": True, "mensaje": "Stock infinito, no requiere sync"}

    nuevo_stock = stock_actual - cantidad_vendida

    if nuevo_stock < 0:
        nuevo_stock = 0

    # 2️⃣ Actualizar stock local
    cursor.execute("""
        UPDATE productos
        SET stock = ?
        WHERE variant_id = ?
    """, (nuevo_stock, variant_id))

    conn.commit()
    conn.close()

    # 3️⃣ Sincronizar con Tiendanube
    resultado = actualizar_stock_tn_service(variant_id, nuevo_stock)

    return resultado
