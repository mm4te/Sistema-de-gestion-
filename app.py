# app.py
from flask import Flask
from models import init_db
from routes.auth import auth_bp
from routes.main import main_bp
from routes.inventario import inventario_bp
from routes.ventas import ventas_bp
from routes.clientes import clientes_bp
from routes.reportes import reportes_bp
from routes.ventas_historial import ventas_historial_bp  # ← Agrega esta línea
from routes.tiendanube import tiendanube_bp

def create_app():
    app = Flask(__name__)
    app.secret_key = 'clave_secreta_negocio_2025_segura'
    
    # === FILTRO JINJA PERSONALIZADO ===
    @app.template_filter('pesos')
    def formato_pesos(valor):
        try:
            return f"{float(valor):,.0f}".replace(',', '.')
        except (ValueError, TypeError):
            return str(valor)
    
    # Registrar blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(inventario_bp)
    app.register_blueprint(ventas_bp)
    app.register_blueprint(clientes_bp)
    app.register_blueprint(reportes_bp)
    app.register_blueprint(ventas_historial_bp)
    app.register_blueprint(tiendanube_bp)

    return app

if __name__ == '__main__':
    init_db()
    app = create_app()
    print("Sistema iniciado. Abre http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)