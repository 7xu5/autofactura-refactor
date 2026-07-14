from datetime import date

from flask import Flask, redirect, request, session, url_for

from models import Factura, Gasto, db, init_db

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
import os
import sys
from dotenv import load_dotenv

# Forzamos a Python a incluir la raíz del proyecto para evitar errores de modulo
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Cargar explícitamente el archivo .env del disco duro en os.environ
load_dotenv(os.path.join(BASE_DIR, '.env'))

app = Flask(__name__)

# Detectamos si estamos ejecutando tests
if os.environ.get('PYTEST_CURRENT_TEST'):
    app.config.from_object('config.TestingConfig')
else:
    app.config.from_object('config.DevelopmentConfig')

db.init_app(app)
app.jinja_env.globals['date'] = date

app.register_blueprint(auth_bp)
app.register_blueprint(contacts_bp)
app.register_blueprint(invoices_bp)
app.register_blueprint(expenses_bp)
app.register_blueprint(budgets_bp)
app.register_blueprint(products_bp)
app.register_blueprint(payments_bp)
app.register_blueprint(config_bp)
app.register_blueprint(delivery_notes_bp)


@app.route('/')
def index():
    return redirect(url_for('invoices.facturas'))


@app.route('/api/productos')
def api_productos_legacy():
    return api_productos_view()


@app.route('/gasto/guardar', methods=['POST'])
def guardar_gasto_legacy():
    return guardar_gasto_view()


@app.before_request
def require_login():
    if request.endpoint and request.endpoint != 'static' and not request.endpoint.startswith('auth.'):
        if not session.get('user_id'):
            return redirect(url_for('auth.login'))


@app.context_processor
def inject_statistics():
    # 1. Filtramos en Factura usando 'estado_contable'
    total_ingresos = sum(
        float(f.total_factura)
        for f in Factura.query.filter(Factura.estado_contable == 'Cobrada').all()
    )
    
    # 2. Corregido: Filtramos en Gasto usando 'estado_pago' y sumamos 'total_factura'
    total_gastos = sum(
        float(g.total_factura)
        for g in Gasto.query.filter(Gasto.estado_pago == 'Pagada').all()
    )
    
    return {'total_ingresos': total_ingresos, 'total_gastos': total_gastos}

import click
from services.restore_service import EmergencyRestoreProcessor

@app.cli.command('restore-emergency')
@click.option('--file', type=click.Path(exists=True), required=True, help='Ruta absoluta o relativa al archivo .sql.gz.enc')
@click.option('--key', type=click.STRING, required=False, help='Clave de descifrado (para evitar problemas de pegado)')
def restore_emergency_command(file, key):
    """
    Regla de Negocio - Escenario 7: Comando CLI de emergencia para restaurar
    la base de datos de forma independiente de la interfaz web.
    """
    click.echo("⚠️  [Alerta] Iniciando recuperación de emergencia vía CLI.")
    
    # 1. Si pasas la clave por argumento (--key), la usamos. Si no, salta el getpass oculto.
    if key:
        secret_key = key.strip()
    else:
        click.secho("🔑 Introduzca la clave maestra de descifrado Fernet: ", fg="cyan", nl=False)
        import sys
        secret_key = sys.stdin.readline().strip()
    
    if not secret_key:
        click.secho("❌ Error: La clave no puede estar vacía.", fg="red")
        return

    # 2. Obtener rutas físicas limpias basadas en la configuración cargada
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    db_path = db_uri.replace('sqlite:///', '')
    if not os.path.isabs(db_path):
        db_path = os.path.abspath(os.path.join(app.root_path, db_path))
        
    # Usamos la carpeta 'instance/temp_backups' o el directorio base para los temporales cortos
    backup_dir = app.config.get('BACKUP_DIR', os.path.join(app.root_path, 'instance', 'temp_backups'))
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)

    # 3. Invocar al procesador único sin duplicar lógica
    processor = EmergencyRestoreProcessor(db_path=db_path, backup_dir=backup_dir)
    
    try:
        # Cerramos conexiones activas del ORM antes de operar físicamente sobre el archivo SQLite
        db.session.remove()
        db.engine.dispose()
        
        exito = processor.procesar_y_restaurar(ruta_backup_enc=file, secret_key=secret_key)
        
        if exito:
            # Sincronizar el .env con la clave correcta con la que abriste el archivo antiguo
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


if __name__ == '__main__':
    with app.app_context():
        init_db(app)
    
    # Importamos y servimos con Waitress de forma nativa
    from waitress import serve
    # Un inicio visual e informativo para el terminal
    print("=" * 60)
    print("AutoFactura — Sistema de Gestión para Autónomos")
    print("=" * 60)
    print(" Acceso local:   http://127.0.0.1:5000")
    print(" Entorno:        Producción (Servidor WSGI Waitress)")
    print(" Ley Antifraude: Módulo VERI*FACTU Activo")
    print("=" * 60)
    print("Para detener el servidor, presiona Ctrl + C\n")
    
    serve(app, host='127.0.0.1', port=5000)