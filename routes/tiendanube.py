# routes/tiendanube.py
from flask import Blueprint, jsonify
from services.tiendanube_service import importar_productos_tn, actualizar_stock_tn_service
from routes import login_required

tiendanube_bp = Blueprint("tiendanube", __name__)

@tiendanube_bp.route("/importar-productos-tiendanube")
@login_required
def importar_productos():
    resultado = importar_productos_tn()
    return jsonify(resultado)

@tiendanube_bp.route("/actualizar-stock-tn/<variant_id>/<int:nuevo_stock>")
@login_required
def actualizar_stock_tn(variant_id, nuevo_stock):
    resultado = actualizar_stock_tn_service(variant_id, nuevo_stock)
    if not resultado.get("ok"):
        return jsonify(resultado), 400
    return jsonify(resultado)
