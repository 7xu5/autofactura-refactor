import os
from cryptography.fernet import Fernet

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
ENV_PATH = os.path.join(BASE_DIR, '.env')

def garantizar_entorno_seguro():
    """
    Verifica si existe el archivo .env. Si no existe, lo genera
    automáticamente con claves criptográficas únicas y seguras.
    """
    # 1. Si ya existe, python-dotenv se encargará de cargarlo (lo gestionamos en el arranque)
    if not os.path.exists(ENV_PATH):
        # Generamos claves de alta seguridad únicas para este despliegue
        nueva_backup_key = Fernet.generate_key().decode()
        nueva_secret_key = Fernet.generate_key().decode() # O cualquier string seguro
        
        # Escribimos el archivo .env físico en el disco
        with open(ENV_PATH, 'w', encoding='utf-8') as f:
            f.write("# Archivo de configuración generado automáticamente\n")
            f.write(f"SECRET_KEY={nueva_secret_key}\n")
            f.write(f"BACKUP_SECRET_KEY={nueva_backup_key}\n")
            f.write("DATABASE_URL=sqlite:///facturacion_db.sqlite\n")
        
        # Opcional: Imprimir en consola del servidor para dar feedback al administrador
        print(f"✨ [AutoFactura] Archivo .env creado con éxito con claves únicas.")

# Ejecutamos la comprobación de seguridad ANTES de definir las clases de configuración
garantizar_entorno_seguro()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'una-clave-secreta-muy-dificil-de-adivinar'
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(BASE_DIR, 'facturacion_db.sqlite')}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

class DevelopmentConfig(Config):
    DEBUG = True
    # Puedes añadir configuraciones específicas para desarrollo aquí

class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:' # Usa una base de datos en memoria para pruebas
    # Puedes añadir configuraciones específicas para pruebas aquí

class ProductionConfig(Config):
    DEBUG = False
    # Configuración de base de datos de producción, logging, etc.
