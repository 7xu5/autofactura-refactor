# test_crypto_manual.py
from cryptography.fernet import Fernet

# 1. Simula tu clave secreta de entorno
KEY = Fernet.generate_key() 
fernet = Fernet(KEY)

texto_original = b"SELECT * FROM facturacion_db; -- Datos Fiscales Sensibles"

# 2. Cifrado
texto_cifrado = fernet.encrypt(texto_original)
print("--- ARCHIVO CIFRADO (Vistazo) ---")
print(texto_cifrado[:50], b"...") 

# 3. Descifrado
texto_descifrado = fernet.decrypt(texto_cifrado)
print("\n--- ARCHIVO DESCIFRADO ---")
print(texto_descifrado.decode('utf-8'))

assert texto_original == texto_descifrado, "Error: El descifrado no coincide"
print("\n✅ ¡Prueba de Cifrado Exitosa! Los datos son inmutables.")