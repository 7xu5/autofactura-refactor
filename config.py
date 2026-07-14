# config.py
import os
from cryptography.fernet import Fernet

# Directorio raíz del proyecto
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
ENV_PATH = os.path.join(BASE_DIR, '.env')

def _generar_claves_por_defecto():
    """Genera claves criptográficas únicas y seguras en formato string."""
    backup_key = Fernet.generate_key().decode()
    secret_key = Fernet.generate_key().decode()
    return secret_key, backup_key


def garantizar_entorno_seguro():
    """
    Verifica si existe el archivo .env. Si no existe, lo genera
    automáticamente con claves criptográficas únicas y seguras.
    """
    if not os.path.exists(ENV_PATH):
        nueva_secret_key, nueva_backup_key = _generar_claves_por_defecto()
        
        # Escribimos el archivo .env físico en el disco
        with open(ENV_PATH, 'w', encoding='utf-8') as f:
            f.write("# Archivo de configuración de AutoFactura - Generado automáticamente\n")
            f.write(f"SECRET_KEY={nueva_secret_key}\n")
            f.write(f"BACKUP_SECRET_KEY={nueva_backup_key}\n")
            f.write("DATABASE_URL=sqlite:///facturacion_db.sqlite\n")
        
        print("✨ [AutoFactura] Archivo .env creado con éxito con claves únicas.")


# Ejecutamos la comprobación de seguridad antes de definir la configuración
garantizar_entorno_seguro()


class Config:
    """Configuración base compartida."""
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'una-clave-secreta-muy-dificil-de-adivinar'
    
    # Leemos la URL de la base de datos desde el entorno si existe, si no, usamos la ruta por defecto
    _db_url_env = os.environ.get('DATABASE_URL')
    if _db_url_env:
        # Aseguramos que si es una ruta SQLite relativa, se resuelva correctamente desde el directorio base
        if _db_url_env.startswith('sqlite:///'):
            db_file = _db_url_env.replace('sqlite:///', '')
            if not os.path.isabs(db_file):
                SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(BASE_DIR, db_file)}"
            else:
                SQLALCHEMY_DATABASE_URI = _db_url_env
        else:
            SQLALCHEMY_DATABASE_URI = _db_url_env
    else:
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(BASE_DIR, 'facturacion_db.sqlite')}"

    SQLALCHEMY_TRACK_MODIFICATIONS = False


class DevelopmentConfig(Config):
    """Configuración específica para el entorno de desarrollo local."""
    DEBUG = True


class TestingConfig(Config):
    """Configuración específica para la suite de pruebas."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'  # Base de datos ultra rápida en memoria para tests


class ProductionConfig(Config):
    """Configuración para el despliegue en entornos productivos."""
    DEBUG = False