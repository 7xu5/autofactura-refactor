import pytest
from unittest.mock import MagicMock
from services.backup_config_service import BackupConfigService

# Clase espejo que simula el comportamiento por defecto de tu modelo físico de SQLAlchemy
class FakeConfiguracionBackup:
    def __init__(self):
        self.id = 1
        self.proveedor = 'LOCAL'
        self.ruta_local_destino = ''
        self.sftp_host = ''
        self.sftp_port = 22
        self.sftp_user = ''
        self.frecuencia_cron = 'DAILY'

@pytest.fixture
def mock_db_session():
    """Fixture de aislamiento térmico para evitar escrituras reales en sqlite."""
    session = MagicMock()
    fake_config = FakeConfiguracionBackup()
    session.query.return_value.first.return_value = fake_config
    return session, fake_config

def test_guardar_configuracion_sftp_correctamente(mock_db_session):
    """
    Valida que los parámetros del servidor SFTP se guarden de forma consistente
    en la base de datos relacional facturacion_db.
    """
    session, fake_config = mock_db_session
    service = BackupConfigService(db_session=session)
    
    service.guardar_configuracion_cloud(
        proveedor="SFTP",
        ruta_local="C:\\BackupsLocal",
        frecuencia_cron="WEEKLY",
        sftp_host="192.168.1.100",
        sftp_port=22,
        sftp_user="backup_user"
    )
    
    assert fake_config.proveedor == "SFTP"
    assert fake_config.sftp_host == "192.168.1.100"
    assert fake_config.sftp_port == 22
    assert fake_config.sftp_user == "backup_user"
    session.commit.assert_called_once()