# app.py
import os
from flask import Flask
from dotenv import load_dotenv
from models import init_db
from routes.auth import auth_bp
from routes.main import main_bp
from routes.inventario import inventario_bp
from routes.ventas import ventas_bp
from routes.clientes import clientes_bp
from routes.reportes import reportes_bp
from routes.ventas_historial import ventas_historial_bp
from routes.tiendanube import tiendanube_bp
from routes.webhook_tn import wbhook_tn

# Flask
SECRET_KEY=cambia_esto_por_una_clave_segura_y_larga

# Tienda Nube
TN_ACCESS_TOKEN=c2883f94ba3987c74d5246e716d89b40d35bdf30
TN_STORE_ID=7324186

load_dotenv()

def create_app():
    app = Flask(__name__)
    app.secret_key = os.getenv("SECRET_KEY", "clave_dev_cambiar_en_produccion")

    @app.template_filter('pesos')
    def formato_pesos(valor):
        try:
            return f"{float(valor):,.0f}".replace(',', '.')
        except (ValueError, TypeError):
            return str(valor)

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(inventario_bp)
    app.register_blueprint(ventas_bp)
    app.register_blueprint(clientes_bp)
    app.register_blueprint(reportes_bp)
    app.register_blueprint(ventas_historial_bp)
    app.register_blueprint(tiendanube_bp)
    app.register_blueprint(wbhook_tn)
    return app

if __name__ == '__main__':
    init_db()
    app = create_app()
    print("Sistema iniciado. Abre http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)
