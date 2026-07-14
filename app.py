# app.py (Punto de entrada de la aplicación)
import os
import sys

# Forzamos a Python a incluir la raíz del proyecto para evitar errores de módulo
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app.factory import create_app
from models import init_db

# Creamos la instancia de la aplicación usando nuestra nueva factoría
app = create_app()

if __name__ == '__main__':
    # Inicializamos la base de datos física usando la configuración de la app
    init_db(app)
    
    # Importamos y servimos con Waitress de forma nativa en producción
    from waitress import serve
    
    print("=" * 60)
    print("AutoFactura — Sistema de Gestión para Autónomos")
    print("=" * 60)
    print(" Acceso local:   http://127.0.0.1:5000")
    print(" Entorno:        Producción (Servidor WSGI Waitress)")
    print(" Ley Antifraude: Módulo VERI*FACTU Activo")
    print("=" * 60)
    print("Para detener el servidor, presiona Ctrl + C\n")
    
    serve(app, host='127.0.0.1', port=5000)