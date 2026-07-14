# app/factory.py
import os
import sys
from datetime import date
from flask import Flask, redirect, request, session, url_for

# Aseguramos que la raíz esté en el PATH por si acaso
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, '.env'))

# Importamos el objeto db de nuestra nueva ubicación y las vistas/Blueprints
from app.extensions import db
from models import Factura, Gasto

from blueprints.auth.views import auth_bp
from blueprints.budgets.views import budgets_bp
from blueprints.config.views import config_bp
from blueprints.contacts.views import contacts_bp
from blueprints.expenses.views import expenses_bp, guardar_gasto as guardar_gasto_view
from blueprints.invoices.views import invoices_bp
from blueprints.payments.views import payments_bp
from blueprints.products.views import api_productos as api_productos_view
from blueprints.products.views import products_bp
from blueprints.delivery_notes.views import delivery_notes_bp

def create_app():
    """
    Factoría de la aplicación Flask.
    Configura, registra extensiones, blueprints y filtros globales de manera limpia.
    """
    app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'), static_folder=os.path.join(BASE_DIR, 'static'))

    # Detectamos si estamos ejecutando tests
    if os.environ.get('PYTEST_CURRENT_TEST'):
        app.config.from_object('config.TestingConfig')
    else:
        app.config.from_object('config.DevelopmentConfig')

    # Inicializamos la base de datos vinculándola a esta instancia de app
    db.init_app(app)
    
    # Configuraciones globales de Jinja
    app.jinja_env.globals['date'] = date

    # Registro de Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(contacts_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(expenses_bp)
    app.register_blueprint(budgets_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(delivery_notes_bp)

    # Rutas Globales / Legacy (Sin alterar nombres ni comportamientos)
    @app.route('/')
    def index():
        return redirect(url_for('invoices.facturas'))

    @app.route('/api/productos')
    def api_productos_legacy():
        return api_productos_view()

    @app.route('/gasto/guardar', methods=['POST'])
    def guardar_gasto_legacy():
        return guardar_gasto_view()

    # Seguridad: require_login obligatorio
    @app.before_request
    def require_login():
        if request.endpoint and request.endpoint != 'static' and not request.endpoint.startswith('auth.'):
            if not session.get('user_id'):
                return redirect(url_for('auth.login'))

    # Estadísticas Globales para la UI
    @app.context_processor
    def inject_statistics():
        total_ingresos = sum(
            float(f.total_factura)
            for f in Factura.query.filter(Factura.estado_contable == 'Cobrada').all()
        )
        total_gastos = sum(
            float(g.total_factura)
            for g in Gasto.query.filter(Gasto.estado_pago == 'Pagada').all()
        )
        return {'total_ingresos': total_ingresos, 'total_gastos': total_gastos}

    # Registro de Comandos CLI (Regla de Negocio - Escenario 7)
    register_cli_commands(app)

    return app


def register_cli_commands(app):
    """Encapsulación de los comandos de consola personalizados."""
    import click
    from services.restore_service import EmergencyRestoreProcessor

    @app.cli.command('restore-emergency')
    @click.option('--file', type=click.Path(exists=True), required=True, help='Ruta absoluta o relativa al archivo .sql.gz.enc')
    @click.option('--key', type=click.STRING, required=False, help='Clave de descifrado (para evitar problemas de pegado)')
    def restore_emergency_command(file, key):
        click.echo("⚠️  [Alerta] Iniciando recuperación de emergencia vía CLI.")
        
        if key:
            secret_key = key.strip()
        else:
            click.secho("🔑 Introduzca la clave maestra de descifrado Fernet: ", fg="cyan", nl=False)
            import sys
            secret_key = sys.stdin.readline().strip()
        
        if not secret_key:
            click.secho("❌ Error: La clave no puede estar vacía.", fg="red")
            return

        db_uri = app.config['SQLALCHEMY_DATABASE_URI']
        db_path = db_uri.replace('sqlite:///', '')
        if not os.path.isabs(db_path):
            db_path = os.path.abspath(os.path.join(app.root_path, db_path))
            
        backup_dir = app.config.get('BACKUP_DIR', os.path.join(app.root_path, 'instance', 'temp_backups'))
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)

        processor = EmergencyRestoreProcessor(db_path=db_path, backup_dir=backup_dir)
        
        try:
            db.session.remove()
            db.engine.dispose()
            
            exito = processor.procesar_y_restaurar(ruta_backup_enc=file, secret_key=secret_key)
            
            if exito:
                env_path = os.path.join(app.root_path, '.env')
                if os.path.exists(env_path):
                    with open(env_path, 'r', encoding='utf-8') as f:
                        lineas = f.readlines()
                    
                    with open(env_path, 'w', encoding='utf-8') as f:
                        for linea in lineas:
                            if linea.startswith('BACKUP_SECRET_KEY='):
                                f.write(f"BACKUP_SECRET_KEY={secret_key}\n")
                            else:
                                f.write(linea)
                                
                click.secho("✨ [ÉXITO] Base de datos restaurada. El sistema está en cuarentena fiscal.", fg="green")
                click.secho("ℹ️ El archivo .env ha sido actualizado con la clave utilizada.", fg="cyan")
                
        except Exception as e:
            import traceback
            click.secho("💥 [CRÍTICO] Falló la restauración por consola.", fg="red")
            traceback.print_exc()