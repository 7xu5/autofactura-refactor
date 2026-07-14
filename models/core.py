from app.extensions import db
from models.mixins import ModelInitMixin

class MetodoPago(ModelInitMixin, db.Model):
    __tablename__ = 'metodo_pago'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    tipo = db.Column(db.String(50))
    entidad = db.Column(db.String(100))
    cuenta_iban = db.Column(db.String(100))
    defecto = db.Column(db.Boolean, default=False)

class Producto(ModelInitMixin, db.Model):
    __tablename__ = 'producto'
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True)
    nombre = db.Column(db.String(255), nullable=False)
    descripcion = db.Column(db.Text)
    descripcion_adicional = db.Column(db.Text)
    precio_unitario_base = db.Column(db.Numeric(10, 2), nullable=False)
    impuesto_defecto = db.Column(db.String(20), default='21% IVA')

class Contacto(ModelInitMixin, db.Model):
    __tablename__ = 'contacto'
    id = db.Column(db.Integer, primary_key=True)
    nombre_fiscal = db.Column(db.String(255), nullable=False)
    tipo_documento = db.Column(db.String(20))
    numero_documento = db.Column(db.String(50), unique=True, nullable=False)
    tipo_contacto = db.Column(db.String(20), default='Cliente')
    email_principal = db.Column(db.String(120))
    emails_adicionales = db.Column(db.Text)
    telefono = db.Column(db.String(30))
    direccion_fiscal = db.Column(db.String(255))
    codigo_postal = db.Column(db.String(15))
    ciudad = db.Column(db.String(100))
    provincia = db.Column(db.String(100))
    pais = db.Column(db.String(100), default='España')
    impuesto_defecto = db.Column(db.String(20), default='21% IVA')
    recargo_equivalencia = db.Column(db.Boolean, default=False)
    notas = db.Column(db.Text)

    # Relaciones declaradas con strings para evitar dependencias circulares directas en importaciones
    facturas = db.relationship('Factura', backref='contacto', lazy=True)
    gastos = db.relationship('Gasto', backref='contacto', lazy=True)
    presupuestos = db.relationship('Presupuesto', backref='contacto', lazy=True)
    albaranes = db.relationship('Albaran', backref='contacto', lazy=True)

class Pago(ModelInitMixin, db.Model):
    __tablename__ = 'pago'
    id = db.Column(db.Integer, primary_key=True)
    fecha_pago = db.Column(db.Date, nullable=False)
    tipo_movimiento = db.Column(db.String(20), nullable=False)
    factura_id = db.Column(db.Integer, db.ForeignKey('factura.id'), nullable=True)
    gasto_id = db.Column(db.Integer, db.ForeignKey('gasto.id'), nullable=True)
    metodo_pago = db.Column(db.String(50))
    importe = db.Column(db.Numeric(10, 2), nullable=False)
    cuenta_bancaria_destino = db.Column(db.String(100))
    estado = db.Column(db.String(20), default='Conciliado')