import os
import sqlite3
import gzip
import shutil
from utils.backup_crypto import BackupCryptoHandler 

class EmergencyRestoreProcessor:
    def __init__(self, db_path: str, backup_dir: str):
        """
        db_path: Ruta al archivo físico de producción (ej: 'facturacion_db.sqlite')
        backup_dir: Directorio donde se almacenan los temporales y los backups
        """
        self.db_path = db_path
        self.backup_dir = backup_dir

    def _ejecutar_sandbox(self, sql_script: str = "", db_file_path: str = "") -> bool:
        """
        Regla de Negocio - Escenario 2: Sandbox de Validación.
        Valida la integridad estructural directamente o mediante un entorno efímero en memoria.
        """
        try:
            # Si nos pasan una base de datos física, la abrimos directamente para verificarla
            if db_file_path and os.path.exists(db_file_path):
                sandbox_conn = sqlite3.connect(db_file_path)
            else:
                # Si es un script de texto, montamos el entorno efímero original
                sandbox_conn = sqlite3.connect(":memory:")
                sandbox_conn.executescript(sql_script)
                
            cursor = sandbox_conn.cursor()
            
            # Verificación estructural básica: que la tabla de configuración responda
            cursor.execute("SELECT * FROM configuracion LIMIT 1;")
            cursor.fetchone()
            
            sandbox_conn.close()
            return True
        except Exception as e:
            print(f"❌ [Sandbox Error] Falló la comprobación de integridad estructural: {e}")
            return False

    def procesar_y_restaurar(self, ruta_backup_enc: str, secret_key: str) -> bool:
        """
        Orquesta el flujo inverso completo: Descifrado -> Validación -> Reemplazo Atómico
        """
        if not os.path.exists(ruta_backup_enc):
            raise FileNotFoundError(f"El archivo de backup no existe: {ruta_backup_enc}")

        ruta_tmp_gz = os.path.join(self.backup_dir, "restore_tmp.sql.gz")
        ruta_tmp_sql = os.path.join(self.backup_dir, "restore_tmp.sql")
        ruta_tmp_db = os.path.join(self.backup_dir, "restore_tmp.sqlite")

        try:
            # 1. Descifrado criptográfico Fernet
            crypto = BackupCryptoHandler(secret_key=secret_key)
            crypto.decrypt_file(ruta_backup_enc, ruta_tmp_gz)

            # 2. Detección de formato e inspección de cabecera
            with open(ruta_tmp_gz, "rb") as f:
                primeros_bytes = f.read(16)

            es_binario_sqlite = primeros_bytes.startswith(b'SQ')

            if es_binario_sqlite:
                print("📦 [Detección] El backup es una base de datos binaria directa de SQLite.")
                if os.path.exists(ruta_tmp_db):
                    os.unlink(ruta_tmp_db)
                shutil.copy2(ruta_tmp_gz, ruta_tmp_db)
                
                # 3. Lanzamos el simulacro de Sandbox validando el archivo físico directamente
                if not self._ejecutar_sandbox(db_file_path=ruta_tmp_db):
                    raise ValueError("El simulacro de Sandbox ha rechazado el archivo de base de datos por estructura inválida.")
            else:
                print("📄 [Detección] El backup es un script SQL plano (comprimido o texto).")
                try:
                    with gzip.open(ruta_tmp_gz, 'rb') as f_in:
                        with open(ruta_tmp_sql, 'wb') as f_out:
                            shutil.copyfileobj(f_in, f_out)
                except Exception:
                    shutil.copy2(ruta_tmp_gz, ruta_tmp_sql)

                with open(ruta_tmp_sql, 'r', encoding='utf-8') as f:
                    sql_content = f.read()

                if os.path.exists(ruta_tmp_db):
                    os.unlink(ruta_tmp_db)
                    
                tmp_conn = sqlite3.connect(ruta_tmp_db)
                tmp_conn.executescript(sql_content)
                tmp_conn.close()

                # Lanzamos el simulacro de Sandbox clásico para scripts
                if not self._ejecutar_sandbox(sql_script=sql_content):
                    raise ValueError("El simulacro de Sandbox ha rechazado el script por errores estructurales.")

            # 5. Reemplazo Atómico seguro en producción
            if os.path.exists(self.db_path):
                shutil.copy2(self.db_path, f"{self.db_path}.bak")
            
            shutil.copy2(ruta_tmp_db, self.db_path)
            
            if os.path.exists(f"{self.db_path}.bak"):
                os.unlink(f"{self.db_path}.bak")

            print("💪 [Restore Success] Base de datos restaurada con éxito.")
            return True

        except Exception as e:
            print(f"💥 [Critical Restore Failure] Proceso de restauración abortado: {e}")
            raise e

        finally:
            for tmp_file in [ruta_tmp_gz, ruta_tmp_sql, ruta_tmp_db]:
                if os.path.exists(tmp_file):
                    try:
                        os.unlink(tmp_file)
                    except Exception:
                        pass