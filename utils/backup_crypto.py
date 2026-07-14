import os
from cryptography.fernet import Fernet

class BackupCryptoHandler:
    def __init__(self, secret_key: str | None = None):
        """
        Inicializa el motor criptográfico con una clave maestra en formato Fernet (Base64).
        """
        # 1. Recuperamos la clave (prioridad al argumento explícito, luego al entorno)
        env_key = secret_key or os.environ.get('BACKUP_SECRET_KEY')
        
        # 2. Defensa estricta: Si no hay clave, el sistema se niega a operar
        if not env_key:
            raise ValueError(
                "CRÍTICO: No se proporcionó ninguna clave ni existe la variable "
                "de entorno 'BACKUP_SECRET_KEY'. Operación criptográfica abortada."
            )
        
        # 3. Normalizamos a bytes para Fernet
        if isinstance(env_key, str):
            self.key = env_key.encode()
        else:
            self.key = env_key
            
        self.cipher = Fernet(self.key)

    def encrypt_file(self, source_path: str, dest_path: str):
        """Lee un archivo comprimido y guarda su versión cifrada con AES-256"""
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Fichero de origen no encontrado: {source_path}")

        with open(source_path, 'rb') as f:
            data = f.read()
            
        encrypted_data = self.cipher.encrypt(data)
        
        with open(dest_path, 'wb') as f:
            f.write(encrypted_data)

    def decrypt_file(self, source_path: str, dest_path: str):
        """Descifra un archivo .enc y lo devuelve a su estado original comprimido"""
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Criptograma no encontrado: {source_path}")

        with open(source_path, 'rb') as f:
            encrypted_data = f.read()
            
        dec_data = self.cipher.decrypt(encrypted_data)
        
        with open(dest_path, 'wb') as f:
            f.write(dec_data)