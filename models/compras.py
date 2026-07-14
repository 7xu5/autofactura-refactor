from datetime import datetime
from app.extensions import db
from models.mixins import ModelInitMixin
from models.enums import EstadoConciliacion, OrigenDeteccion

class Gasto(ModelInitMixin, db.Model):
    __tablename__ = 'gasto'
    id = db.Column(db.Integer, primary_key=True)
    numero_factura_proveedor = db.Column(db.String(100))
    contacto_id = db.Column(db.Integer, db.ForeignKey('contacto.id'))
    referencia = db.Column(db.String(100))
    tipo_gasto = db.Column(db.String(100))
    fecha_factura = db.Column(db.Date, nullable=False)
    fecha_vencimiento = db.Column(db.Date)
    
    base_imponible = db.Column(db.Numeric(10, 2), default=0.00)
    porcentaje_iva = db.Column(db.Numeric(5, 2), default=21.00)
    importe_impuesto = db.Column(db.Numeric(10, 2), default=0.00)
    porcentaje_retencion = db.Column(db.Numeric(5, 2), default=0.00)
    importe_retencion = db.Column(db.Numeric(10, 2), default=0.00)
    total_factura = db.Column(db.Numeric(10, 2), default=0.00)
    estado_pago = db.Column(db.String(20), default='Recibida')
    ruta_adjunto_url = db.Column(db.String(512))
    
    impuestos = db.relationship('ImpuestoGasto', backref='gasto', cascade='all, delete-orphan')
    pagos = db.relationship('Pago', backref='gasto', lazy=True)

class ImpuestoGasto(ModelInitMixin, db.Model):
    __tablename__ = 'impuesto_gasto'
    id = db.Column(db.Integer, primary_key=True)
    gasto_id = db.Column(db.Integer, db.ForeignKey('gasto.id'), nullable=False)
    tipo = db.Column(db.String(50))
    base = db.Column(db.Numeric(10, 2))
    cuota = db.Column(db.Numeric(10, 2))

class ConciliacionFacturas(ModelInitMixin, db.Model):
    __tablename__ = 'conciliacion_facturas'
    id = db.Column(db.Integer, primary_key=True)
    numero_factura = db.Column(db.String(50), nullable=False)
    estado_conciliacion = db.Column(db.Enum(EstadoConciliacion), default=EstadoConciliacion.pendiente_verificar, nullable=False)
    origen_deteccion = db.Column(db.Enum(OrigenDeteccion), nullable=False)
    resuelto = db.Column(db.Boolean, default=False, nullable=False)
    fecha_deteccion = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)