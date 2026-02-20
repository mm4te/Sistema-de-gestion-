# routes/tiendanube.py

from flask import Blueprint, jsonify
from services.tiendanube_service import (
    importar_productos_tn,
    actualizar_stock_tn_service
)

tiendanube_bp = Blueprint("tiendanube", __name__)


# ==========================================
# ROUTE IMPORTAR PRODUCTOS
# ==========================================

@tiendanube_bp.route("/importar-productos-tiendanube")
def importar_productos():
    resultado = importar_productos_tn()
    return jsonify(resultado)


# ==========================================
# ROUTE ACTUALIZAR STOCK
# ==========================================

@tiendanube_bp.route("/actualizar-stock-tn/<variant_id>/<int:nuevo_stock>")
def actualizar_stock_tn(variant_id, nuevo_stock):
    resultado = actualizar_stock_tn_service(variant_id, nuevo_stock)

    if not resultado.get("ok"):
        return jsonify(resultado), 400

    return jsonify(resultado)
