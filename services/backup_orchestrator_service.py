import os
import gzip
from datetime import datetime
import subprocess  
from typing import Optional, Any  
from utils.backup_crypto import BackupCryptoHandler

class BackupOrchestratorService:
    def __init__(self, db_path: str = "facturacion_db.sqlite"):
        self.db_path = db_path
        self.crypto = BackupCryptoHandler()

    async def ejecutar_flujo_backup(
        self,
        ruta_local_destino: Optional[str],
        storage_provider_service: Optional[Any] = None,
        provider_creds: Optional[dict] = None
    ) -> dict:
        """
        Orquesta la generación del volcado inmutable y su posterior cifrado/transmisión.
        """
        if not ruta_local_destino:
            return {"status": "error", "error": "No se ha configurado una ruta local de destino."}

        try:
            # 1. Asegurar la existencia física del directorio destino
            os.makedirs(ruta_local_destino, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            from flask import current_app
            db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')

            if db_uri.startswith('sqlite:///'):
                relative_db_path = db_uri.replace('sqlite:///', '')
                origen_db = os.path.abspath(os.path.join(current_app.root_path, relative_db_path))
                archivo_sql_temporal = os.path.join(ruta_local_destino, f"backup_raw_{timestamp}.db")
                
                import shutil
                shutil.copy2(origen_db, archivo_sql_temporal)
            else:
                archivo_sql_temporal = os.path.join(ruta_local_destino, f"backup_raw_{timestamp}.sql")
                comando = ["pg_dump", "-U", "postgres", "-h", "localhost", "-d", "facturacion_db", "-F", "c", "-f", archivo_sql_temporal]
                env = os.environ.copy()
                env["PGPASSWORD"] = "postgres"
                process = subprocess.run(comando, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
                if process.returncode != 0:
                    raise Exception(f"Error en pg_dump: {process.stderr}")

            # 2. Generación del archivo definitivo (crypto.encrypt_file para cifrarlo)
            nombre_archivo_final = f"backup_cifrado_{timestamp}.enc"
            ruta_archivo_final = os.path.join(ruta_local_destino, nombre_archivo_final)

            if os.path.exists(archivo_sql_temporal):
                self.crypto.encrypt_file(archivo_sql_temporal, ruta_archivo_final)
                os.remove(archivo_sql_temporal)
            else:
                raise Exception("El volcado de datos temporal no pudo ser localizado.")

            # =====================================================================
            # 3. TRANSMISIÓN REAL AL ALMACENAMIENTO REMOTO (SFTP)
            # =====================================================================
            subida_remota_exitosa = True
            if storage_provider_service and provider_creds:
                # Al ser operaciones i/o de red síncronas en el servicio, las corremos de forma segura
                import asyncio
                loop = asyncio.get_event_loop()
                subida_remota_exitosa = await loop.run_in_executor(
                    None, 
                    storage_provider_service.upload_file, 
                    ruta_archivo_final, 
                    nombre_archivo_final, 
                    provider_creds
                )
                
                if not subida_remota_exitosa:
                    return {
                        "status": "error", 
                        "local_archive": ruta_archivo_final,
                        "error": "La copia se guardó en local, pero falló la transmisión al almacenamiento remoto SFTP."
                    }

            return {
                "status": "success",
                "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "local_archive": ruta_archivo_final
            }

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "error", "error": str(e)}

    def _comprimir_archivo(self, source: str, dest: str) -> None:
        """Comprime el archivo leyendo y escribiendo directamente sus bytes en gzip sin usar copyfileobj"""
        with open(source, 'rb') as f_in:
            data = f_in.read()
        with gzip.open(dest, 'wb') as f_out:
            f_out.write(data)