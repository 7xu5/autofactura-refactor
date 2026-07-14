from abc import ABC, abstractmethod

class BackupStorageService(ABC):
    """
    Contrato abstracto (Interfaz) que deben cumplir todos los proveedores
    de almacenamiento de copias de seguridad (Local, SFTP, Google Drive, MEGA, etc.)
    """
    
    @abstractmethod
    def upload_file(self, local_file_path: str, remote_filename: str, credentials_json: dict | None = None) -> bool:
        """
        Sube un archivo cifrado al destino configurado.
        
        :param local_file_path: Ruta absoluta al fichero temporal local (.sql.gz.enc)
        :param remote_filename: Nombre que tendrá el fichero en el destino
        :param credentials_json: Diccionario desempaquetado de credenciales del proveedor
        :return: True si la transmisión fue exitosa, False en caso contrario
        """
        pass