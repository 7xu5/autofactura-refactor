# models.py (Raíz del proyecto)
# Este archivo actúa como puente de compatibilidad hacia el paquete modular 'models/'.

from models import (
    db,
    EstadoConciliacion,
    OrigenDeteccion,
    ModelInitMixin,
    User,
    Configuracion,
    ConfiguracionBackup,
    RegistroEventos,
    MetodoPago,
    Producto,
    Contacto,
    Pago,
    Factura,
    FacturaLinea,
    FacturaVerifactu,
    Presupuesto,
    PresupuestoLinea,
    Albaran,
    AlbaranLinea,
    Gasto,
    ImpuestoGasto,
    ConciliacionFacturas,
    init_db
)

# Mantener la exposición por si se importa usando 'from models import *'
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