# models/__init__.py
from app.extensions import db

# 1. Importaciones internas y exposición pública de Enums y Mixins
from models.enums import EstadoConciliacion, OrigenDeteccion
from models.mixins import ModelInitMixin

# 2. Importamos y exponemos todas las clases de los submódulos para que sean accesibles desde fuera
from models.auth import User

from models.config_models import (
    Configuracion, 
    ConfiguracionBackup, 
    RegistroEventos
)

from models.core import (
    MetodoPago, 
    Producto, 
    Contacto, 
    Pago
)

from models.ventas import (
    Factura, 
    FacturaLinea, 
    FacturaVerifactu, 
    Presupuesto, 
    PresupuestoLinea, 
    Albaran, 
    AlbaranLinea
)

from models.compras import (
    Gasto, 
    ImpuestoGasto, 
    ConciliacionFacturas
)

# Esto define qué se expone cuando alguien hace "from models import *"
__all__ = [
    'db',
    'EstadoConciliacion',
    'OrigenDeteccion',
    'ModelInitMixin',
    'User',
    'Configuracion',
    'ConfiguracionBackup',
    'RegistroEventos',
    'MetodoPago',
    'Producto',
    'Contacto',
    'Pago',
    'Factura',
    'FacturaLinea',
    'FacturaVerifactu',
    'Presupuesto',
    'PresupuestoLinea',
    'Albaran',
    'AlbaranLinea',
    'Gasto',
    'ImpuestoGasto',
    'ConciliacionFacturas',
    'init_db'
]

def init_db(app):
    """Inicializa la estructura física de la base de datos y crea los registros por defecto."""
    with app.app_context():
        db.create_all()
         
        if not Configuracion.query.first():
            configuracion = Configuracion(
                nombre_empresa='Mi Empresa',
                serie_factura='F26-',
                serie_rectificativa='R26-',
                numero_inicial_rectificativa=1,
                serie_presupuesto='PR26-',
                numero_inicial_presupuesto=1,
                numero_inicial_factura=1,
                pais='España',
                metodo_pago_defecto='Transferencia bancaria',
                moneda_defecto='Euro (€)',
                impuesto_defecto='21% IVA',
                recargo_equivalencia_default=False,
                serie_albaran='ALB26-',
                numero_inicial_albaran=1,
            )
            db.session.add(configuracion)
            db.session.commit()

        if not ConfiguracionBackup.query.first():
            config_backup = ConfiguracionBackup(
                proveedor='LOCAL',
                ruta_local_destino='',
                mega_token='',
                sftp_host='',
                sftp_port=22,
                sftp_user='',
                frecuencia_cron='DAILY'
            )
            db.session.add(config_backup)
            db.session.commit()