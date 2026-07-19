from app.extensions import db
from models.mixins import ModelInitMixin
from decimal import Decimal

class Factura(ModelInitMixin, db.Model):
    __tablename__ = 'factura'
    id = db.Column(db.Integer, primary_key=True)
    numero_factura = db.Column(db.String(50), unique=True, nullable=False)
    tipo_factura = db.Column(db.String(20), default='Ordinaria')
    factura_rectificada_id = db.Column(db.Integer, db.ForeignKey('factura.id'), nullable=True)
    motivo_rectificacion = db.Column(db.String(255), nullable=True)
    
    factura_original = db.relationship('Factura', remote_side=[id], backref='rectificativas', lazy=True)
    tipo_pestana = db.Column(db.String(20), default='Emitida')
    estado_ui = db.Column(db.String(20), default='Borrador')
    estado_contable = db.Column(db.String(20), default='Pendiente')
    
    contacto_id = db.Column(db.Integer, db.ForeignKey('contacto.id'), nullable=False)
    metodo_pago_id = db.Column(db.Integer, db.ForeignKey('metodo_pago.id'), nullable=True)
    referencia = db.Column(db.String(100), nullable=True)
    referencia_presupuesto = db.Column(db.String(100), nullable=True)
    
    fecha_factura = db.Column(db.Date, nullable=False)
    fecha_vencimiento = db.Column(db.Date, nullable=True)
    
    total_base_imponible = db.Column(db.Numeric(10, 2), default=0.00)
    total_cuota_iva = db.Column(db.Numeric(10, 2), default=0.00)
    total_recargo_equivalencia = db.Column(db.Numeric(10, 2), default=0.00)
    total_factura = db.Column(db.Numeric(10, 2), default=0.00)

    lineas = db.relationship('FacturaLinea', backref='factura', cascade='all, delete-orphan', lazy=True)
    pagos = db.relationship('Pago', backref='factura', lazy=True)
    verifactu_registro = db.relationship('FacturaVerifactu', backref='factura', uselist=False, cascade='all, delete-orphan')
    verifactu_enviada = db.Column(db.Boolean, default=False)
    verifactu_estado = db.Column(db.String(20), default='Pendiente')
    verifactu_csv = db.Column(db.String(100), nullable=True)

    porcentaje_irpf = db.Column(db.Numeric(5, 2), nullable=False, default=0.0, server_default="0.0")
    total_retencion_irpf = db.Column(db.Numeric(10, 2), nullable=False, default=0.0, server_default="0.0")

    def lineas_json(self):
        resultado = []
        lineas_relacion: list = self.lineas # type: ignore[assignment]
        for l in lineas_relacion:
            resultado.append({
                'id': l.id,
                'articulo_id': l.producto_id or '',
                'concepto': l.concepto,
                'informacion': l.informacion or '',
                'unidades': str(l.unidades),
                'precio': str(l.precio_unitario),
                'descuento': str(l.descuento_porcentaje),
                'impuesto': l.impuesto_tipo,
                'total': str(l.subtotal_linea)
            })
        return resultado
    
    def validate(self):
        """Valida los datos de la factura."""
        if not self.contacto_id:
            raise ValueError("El cliente es obligatorio.")
        if not self.lineas:
            raise ValueError("La factura debe tener al menos una línea.")
        
    def validar_integridad(self, total_esperado):
        # El modelo no calcula, solo VERIFICA si lo que le dan es correcto
        if abs(self.total_factura - total_esperado) > Decimal('0.01'):
            raise ValueError("El total no coincide.")

class FacturaLinea(ModelInitMixin, db.Model):
    __tablename__ = 'factura_linea'
    id = db.Column(db.Integer, primary_key=True)
    factura_id = db.Column(db.Integer, db.ForeignKey('factura.id'), nullable=False)
    producto_id = db.Column(db.Integer, db.ForeignKey('producto.id'), nullable=True)
    concepto = db.Column(db.String(255), nullable=False)
    informacion = db.Column(db.Text, nullable=True)
    unidades = db.Column(db.Numeric(10, 2), nullable=False, default=1.00)
    precio_unitario = db.Column(db.Numeric(10, 2), nullable=False)
    descuento_porcentaje = db.Column(db.Numeric(5, 2), default=0.00)
    impuesto_tipo = db.Column(db.String(20), default='21% IVA')
    porcentaje_iva = db.Column(db.Numeric(5, 2), default=0.00)
    porcentaje_recargo = db.Column(db.Numeric(5, 2), default=0.00)
    subtotal_linea = db.Column(db.Numeric(10, 2), nullable=False)

class FacturaVerifactu(ModelInitMixin, db.Model):
    __tablename__ = 'factura_verifactu'
    id = db.Column(db.Integer, primary_key=True)
    factura_id = db.Column(db.Integer, db.ForeignKey('factura.id'), unique=True, nullable=False)
    fecha_hora_alta = db.Column(db.DateTime, nullable=False)
    hash_actual = db.Column(db.String(64), unique=True, nullable=False)
    hash_anterior = db.Column(db.String(64), nullable=True)
    xml_firmado = db.Column(db.Text, nullable=False)
    estado_envio = db.Column(db.String(30), default='Pendiente')
    csv_aeat = db.Column(db.String(100), nullable=True)
    error_glosa = db.Column(db.Text, nullable=True)

class Presupuesto(ModelInitMixin, db.Model):
    __tablename__ = 'presupuesto'
    id = db.Column(db.Integer, primary_key=True)
    numero_presupuesto = db.Column(db.String(50), unique=True, nullable=False)
    contacto_id = db.Column(db.Integer, db.ForeignKey('contacto.id'), nullable=False)
    metodo_pago_id = db.Column(db.Integer, db.ForeignKey('metodo_pago.id'), nullable=True)
    referencia = db.Column(db.String(100))
    fecha_emision = db.Column(db.Date, nullable=False)
    fecha_validez = db.Column(db.Date, nullable=False)
    total_base_imponible = db.Column(db.Numeric(10, 2), default=0.00)
    total_impuestos = db.Column(db.Numeric(10, 2), default=0.00)
    total_presupuesto = db.Column(db.Numeric(10, 2), default=0.00)
    estado = db.Column(db.String(20), default='Borrador')
    notas = db.Column(db.Text)

    lineas = db.relationship('PresupuestoLinea', backref='presupuesto', cascade='all, delete-orphan', lazy=True)

    def lineas_json(self):
        resultado = []
        lineas_relacion: list = self.lineas # type: ignore[assignment]
        for l in lineas_relacion:
            resultado.append({
                'tipo': 'linea',
                'id': l.id,
                'articulo_id': l.producto_id or '',
                'concepto': l.concepto,
                'informacion': l.informacion or '',
                'unidades': str(l.unidades),
                'precio': str(l.precio_unitario),
                'descuento': str(l.descuento_porcentaje),
                'impuesto': l.impuesto_tipo,
                'total': str(l.subtotal_linea)
            })
        return resultado

class PresupuestoLinea(ModelInitMixin, db.Model):
    __tablename__ = 'presupuesto_linea'
    id = db.Column(db.Integer, primary_key=True)
    presupuesto_id = db.Column(db.Integer, db.ForeignKey('presupuesto.id'), nullable=False)
    producto_id = db.Column(db.Integer, db.ForeignKey('producto.id'), nullable=True)
    concepto = db.Column(db.String(255), nullable=False)
    informacion = db.Column(db.Text, nullable=True)
    unidades = db.Column(db.Numeric(10, 2), default=1.00)
    precio_unitario = db.Column(db.Numeric(10, 2), nullable=False)
    descuento_porcentaje = db.Column(db.Numeric(5, 2), default=0.00)
    impuesto_tipo = db.Column(db.String(20), default='21% IVA')
    subtotal_linea = db.Column(db.Numeric(10, 2), nullable=False)

class Albaran(ModelInitMixin, db.Model):
    __tablename__ = 'albaran'
    id = db.Column(db.Integer, primary_key=True)
    numero_albaran = db.Column(db.String(50), unique=True, nullable=False)
    contacto_id = db.Column(db.Integer, db.ForeignKey('contacto.id'), nullable=False)
    metodo_pago_id = db.Column(db.Integer, db.ForeignKey('metodo_pago.id'), nullable=True)
    referencia = db.Column(db.String(100), nullable=True)
    referencia_presupuesto = db.Column(db.String(100), nullable=True)
    referencia_factura = db.Column(db.String(100), nullable=True)
    fecha_emision = db.Column(db.Date, nullable=False)
    fecha_entrega = db.Column(db.Date, nullable=True)
    total_base_imponible = db.Column(db.Numeric(10, 2), default=0.00)
    total_impuestos = db.Column(db.Numeric(10, 2), default=0.00)
    total_albaran = db.Column(db.Numeric(10, 2), default=0.00)
    estado = db.Column(db.String(20), default='Borrador')
    notas = db.Column(db.Text)

    lineas = db.relationship('AlbaranLinea', backref='albaran', cascade='all, delete-orphan', lazy=True)

    def lineas_json(self):
        resultado = []
        lineas_relacion: list = self.lineas # type: ignore[assignment]
        for l in lineas_relacion:
            resultado.append({
                'tipo': 'linea',
                'id': l.id,
                'articulo_id': l.producto_id or '',
                'concepto': l.concepto,
                'informacion': l.informacion or '',
                'unidades': str(l.unidades),
                'precio': str(l.precio_unitario),
                'descuento': str(l.descuento_porcentaje),
                'impuesto': l.impuesto_tipo,
                'total': str(l.subtotal_linea)
            })
        return resultado

class AlbaranLinea(ModelInitMixin, db.Model):
    __tablename__ = 'albaran_linea'
    id = db.Column(db.Integer, primary_key=True)
    albaran_id = db.Column(db.Integer, db.ForeignKey('albaran.id'), nullable=False)
    producto_id = db.Column(db.Integer, db.ForeignKey('producto.id'), nullable=True)
    concepto = db.Column(db.String(255), nullable=False)
    informacion = db.Column(db.Text, nullable=True)
    unidades = db.Column(db.Numeric(10, 2), default=1.00)
    precio_unitario = db.Column(db.Numeric(10, 2), nullable=False)
    descuento_porcentaje = db.Column(db.Numeric(5, 2), default=0.00)
    impuesto_tipo = db.Column(db.String(20), default='21% IVA')
    subtotal_linea = db.Column(db.Numeric(10, 2), nullable=False)