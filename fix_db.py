from app import app
import sqlite3
import os

def fix_schema():
    with app.app_context():
        # Obtenemos la ruta del archivo sqlite desde la configuración
        db_uri = app.config['SQLALCHEMY_DATABASE_URI']
        db_path = db_uri.replace('sqlite:///', '')
        
        # Si es una ruta relativa, la hacemos absoluta basándonos en la raíz
        if not os.path.isabs(db_path):
            db_path = os.path.abspath(os.path.join(app.root_path, db_path))
            
        print(f"Actualizando base de datos en: {db_path}")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        try:
            # Añadimos las columnas que faltan
            cursor.execute("ALTER TABLE configuracion ADD COLUMN requiere_conciliacion BOOLEAN DEFAULT 0")
            cursor.execute("ALTER TABLE configuracion ADD COLUMN ultima_conciliacion_aeat DATETIME")
            cursor.execute("ALTER TABLE configuracion ADD COLUMN conciliacion_intentos_fallidos INTEGER DEFAULT 0")
            conn.commit()
            print("¡Éxito! Base de datos actualizada con las nuevas columnas.")
        except sqlite3.OperationalError as e:
            print(f"Nota: Es posible que la columna ya exista o hubo un error: {e}")
        finally:
            conn.close()

if __name__ == "__main__":
    fix_schema()