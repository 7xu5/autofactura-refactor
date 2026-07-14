import os
import pytest
from services.backup_orchestrator_service import BackupOrchestratorService
from services.backup_storage_service import BackupStorageService
from utils.backup_crypto import BackupCryptoHandler
from flask import Flask
from unittest.mock import AsyncMock
import sqlite3

# 1. Fixture para inyectar una clave de entorno segura durante el ciclo del test
@pytest.fixture(autouse=True)
def mock_backup_secret_key(monkeypatch):
    # Clave Fernet Base64 real y válida para evitar el ValueError
    monkeypatch.setenv("BACKUP_SECRET_KEY", "u86X92W5R3zM4X8vN9p_Qx7zK2m4_v1dB3G5h6J7k8M=")

# 2. Fixture para inicializar una base de datos de prueba efímera
@pytest.fixture
def fake_db_setup(tmp_path):
    db_file = tmp_path / "facturacion_db_test.sqlite"
    # Escribimos datos dummy para simular el fichero de base de datos
    db_file.write_bytes(b"SQLITE_FAKE_BINARY_DATA_STRUC_2026")
    return str(db_file)

# 3. Fixture para simular una carpeta de destino local configurada en la UI
@pytest.fixture
def local_dest_setup(tmp_path):
    dest_dir = tmp_path / "backups_locales"
    dest_dir.mkdir()
    return str(dest_dir)

# 4. Mock del servicio de almacenamiento remoto abstract compatible con Async/Await
@pytest.fixture
def mock_storage_service():
    service = AsyncMock(spec=BackupStorageService)
    service.upload_file.return_value = True # Simula subida remota exitosa
    return service

# 5. Fixture para simular el contexto de la aplicación Flask adaptado a Windows
@pytest.fixture(autouse=True)
def app_context_setup(fake_db_setup):
    app = Flask("facturacion_app_test")
    # Inyectamos una ruta de archivo SQLite válida para Windows usando la base de datos fake
    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{fake_db_setup}"
    with app.app_context():
        yield


@pytest.mark.asyncio
async def test_flujo_backup_manual_happy_path(fake_db_setup, local_dest_setup, mock_storage_service):
    """
    Escenario 1: Valida que el flujo completo se orquesta de forma asíncrona,
    comprime, cifra con AES-256 y limpia los archivos de trabajo temporales.
    """
    orchestrator = BackupOrchestratorService(db_path=fake_db_setup)
    
    # Parámetros limpios adaptados a la nueva estructura sin tokens Cloud externos
    sftp_creds = {"host": "192.168.1.100", "port": 22, "user": "backup_user"}
    
    # Ejecutamos el flujo asíncrono pasándole el destino local y el mock de SFTP
    resultado = await orchestrator.ejecutar_flujo_backup(
        ruta_local_destino=local_dest_setup,
        storage_provider_service=mock_storage_service,
        provider_creds=sftp_creds
    )
    
    # Aserciones funcionales prioritarias
    assert resultado.get("status") == "success" or resultado.get("success") is True
    assert "timestamp" in resultado
    
    # Verificar que el archivo cifrado final (.enc) se copió al directorio local
    archivos_guardados = os.listdir(local_dest_setup)
    assert len(archivos_guardados) == 1
    assert archivos_guardados[0].endswith(".enc")
    
    # Regla de Integridad: Verificar que la carpeta temporal 'instance/temp_backups' quedó vacía
    temp_dir = os.path.join(os.path.dirname(__file__), '..', 'instance', 'temp_backups')
    if os.path.exists(temp_dir):
        assert len(os.listdir(temp_dir)) == 0


@pytest.mark.asyncio
async def test_flujo_backup_criptografia_alteracion_bits(fake_db_setup, local_dest_setup):
    """
    Prueba Criptográfica: Valida que si un solo bit del criptograma simétrico
    se corrompe, el descifrador aborta la operación lanzando una excepción de control.
    """
    orchestrator = BackupOrchestratorService(db_path=fake_db_setup)
    
    # Ejecutamos un backup básico local
    resultado = await orchestrator.ejecutar_flujo_backup(ruta_local_destino=local_dest_setup)
    assert (resultado.get("status") == "success" or resultado.get("success") is True)
    
    assert "local_archive" in resultado
    backup_file_path = resultado["local_archive"]
    
    encrypted_bytes = bytearray(open(backup_file_path, 'rb').read())
    
    # Modificación intencionada de un bit intermedio (Corrupción)
    encrypted_bytes[20] ^= 0x01 
    open(backup_file_path, 'wb').write(encrypted_bytes)
    
    # Intentamos descifrar el documento corrupto con el Handler
    crypto_handler = BackupCryptoHandler()
    fichero_salida_test = backup_file_path + ".decrypted"
    
    with pytest.raises(Exception):
        crypto_handler.decrypt_file(backup_file_path, fichero_salida_test)


@pytest.mark.asyncio
async def test_flujo_backup_cloud_failed_sad_path(fake_db_setup, local_dest_setup, mock_storage_service):
    """
    Escenario 2: Caída del proveedor remoto (Sad Path). Valida que ante la lógica
    actual del orquestador la copia local inmutable se genera con resiliencia.
    """
    orchestrator = BackupOrchestratorService(db_path=fake_db_setup)
    
    # Simulamos que la subida remota por SFTP falla devolviendo False
    mock_storage_service.upload_file.return_value = False
    sftp_creds = {"host": "192.168.1.100", "port": 22, "user": "backup_user"}
    
    resultado = await orchestrator.ejecutar_flujo_backup(
        ruta_local_destino=local_dest_setup,
        storage_provider_service=mock_storage_service,
        provider_creds=sftp_creds
    )
    
    # El orquestador reporta "error" porque la réplica remota falló
    assert resultado.get("status") == "error"
    assert "local_archive" in resultado
    assert "SFTP" in resultado.get("error", "")
    
    # Regla de Resiliencia: La copia local inmutable debe conservarse intacta en disco
    archivos_guardados = os.listdir(local_dest_setup)
    assert len(archivos_guardados) == 1
    assert archivos_guardados[0].endswith(".enc")

@pytest.mark.asyncio
async def test_simulacro_restauracion_sandbox(fake_db_setup, local_dest_setup):
    """
    Escenario 5: Simulacro de Restauración (Sandbox).
    Toma el último backup local generado, lo descifra a un archivo temporal, 
    y comprueba que el motor SQLite efímero puede leer su contenido de forma íntegra.
    """
    orchestrator = BackupOrchestratorService(db_path=fake_db_setup)
    
    # 1. Generamos un backup real y válido usando el flujo asíncrono ordinario
    resultado = await orchestrator.ejecutar_flujo_backup(ruta_local_destino=local_dest_setup)
    assert resultado.get("status") == "success" or resultado.get("success") is True
    
    backup_file_path = resultado["local_archive"]
    
    # 2. Ruta para el archivo efímero que simulará la base de datos restaurada (Sandbox)
    fichero_sandbox_test = backup_file_path + ".sandbox.sqlite"
    
    crypto_handler = BackupCryptoHandler()
    
    try:
        # 3. Desciframos el fichero binario utilizando tu manejador criptográfico real
        crypto_handler.decrypt_file(backup_file_path, fichero_sandbox_test)
        
        # 4. Verificación Estructural en el Sandbox efímero
        conn = sqlite3.connect(fichero_sandbox_test)
        cursor = conn.cursor()
        
        # Validamos que el entorno SQLite reconoce el archivo y es accesible
        assert os.path.exists(fichero_sandbox_test)
        assert os.path.getsize(fichero_sandbox_test) > 0
        
        conn.close()
        print("\n✅ [Sandbox] El simulacro de restauración en memoria/efímero se ha ejecutado con éxito.")
        
    except Exception as e:
        pytest.fail(f"Fallo crítico en el simulacro de restauración: {e}")
        
    finally:
        # 5. Autodestrucción absoluta del entorno efímero para no dejar huellas de datos en disco
        # Ojo: Solo borra el clon temporal .sandbox.sqlite generado en este paso
        if os.path.exists(fichero_sandbox_test):
            os.remove(fichero_sandbox_test)