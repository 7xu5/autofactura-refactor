from typing import Optional, Any
from utils.backup_crypto import BackupCryptoHandler

class BackupConfigService:
    def __init__(self, db_session: Any):
        """
        Inyecta la sesión de SQLAlchemy para operar de manera limpia
        y desacoplada de Flask.
        """
        self.db = db_session
        self.crypto = BackupCryptoHandler()

    def guardar_configuracion_cloud(
        self, 
        proveedor: str, 
        ruta_local: Optional[str], 
        frecuencia_cron: str, 
        sftp_host: Optional[str] = None,
        sftp_port: int = 22,
        sftp_user: Optional[str] = None
    ) -> Any:
        """
        Modifica los parámetros de configuración persistiendo las variables de entorno
        y de red necesarias para SFTP y Local de forma limpia.
        """
        from models import ConfiguracionBackup
        
        # Recuperamos la configuración única registrada por defecto
        config = self.db.query(ConfiguracionBackup).first()
        if not config:
            config = ConfiguracionBackup()
            self.db.add(config)

        config.proveedor = proveedor
        config.ruta_local_destino = ruta_local or ""
        config.frecuencia_cron = frecuencia_cron
        
        # Mapeo directo de red para SFTP
        config.sftp_host = sftp_host or ""
        config.sftp_port = sftp_port
        config.sftp_user = sftp_user or ""

        
        self.db.commit()
        return config

