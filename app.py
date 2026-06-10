# app.py
import os
import logging
from flask import Flask
from flask_wtf.csrf import CSRFProtect
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
from routes.presupuestos import presupuestos_bp
from routes.remitos import remitos_bp
from routes.usuarios import usuarios_bp
from routes.gastos import gastos_bp
from routes.resumen import resumen_bp

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s'
)

csrf = CSRFProtect()


def create_app():
    app = Flask(__name__)

    secret_key = os.getenv("SECRET_KEY", "clave_dev_cambiar_en_produccion")
    if secret_key == "clave_dev_cambiar_en_produccion":
        logging.warning(
            "SECRET_KEY por defecto en uso. Configura una clave segura en .env"
        )
    app.secret_key = secret_key
    app.config['WTF_CSRF_TIME_LIMIT'] = 3600

    upload_folder = os.path.join(BASE_DIR, 'uploads', 'gastos')
    os.makedirs(upload_folder, exist_ok=True)
    app.config['UPLOAD_FOLDER_GASTOS'] = upload_folder
    app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5 MB

    csrf.init_app(app)

    @app.before_request
    def _load_user():
        from flask import g, session
        g.user_id       = session.get('user_id')
        g.username      = session.get('username', '')
        g.rol_nivel     = session.get('rol_nivel', 99)
        g.rol_nombre    = session.get('rol_nombre', '')
        g.es_superadmin = (session.get('rol_nivel') == 1)
        raw_perms = session.get('permisos', [])
        g.permisos = {tuple(p) for p in raw_perms}

    app.jinja_env.globals['enumerate'] = enumerate

    @app.template_global()
    def tiene_permiso(modulo, accion):
        from flask import g
        if g.get('es_superadmin'):
            return True
        return (modulo, accion) in g.get('permisos', set())

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
    app.register_blueprint(presupuestos_bp)
    app.register_blueprint(remitos_bp)
    app.register_blueprint(usuarios_bp)
    app.register_blueprint(gastos_bp)
    app.register_blueprint(resumen_bp)

    csrf.exempt(wbhook_tn)

    return app


if __name__ == '__main__':
    init_db()
    app = create_app()
    debug = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    print("Sistema iniciado. Abre http://localhost:5000")
    app.run(debug=debug, host='0.0.0.0', port=5000)
