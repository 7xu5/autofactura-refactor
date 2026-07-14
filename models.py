import enum
from datetime import datetime

# Importamos la instancia única de db desde nuestro archivo de extensiones
from app.extensions import db

class EstadoConciliacion(enum.Enum):
    ok = 'ok'
    fantasma_alta = 'fantasma_alta'
    anulada_en_aeat_no_reflejada = 'anulada_en_aeat_no_reflejada'
    pendiente_verificar = 'pendiente_verificar'

class OrigenDeteccion(enum.Enum):
    post_restauracion = 'post_restauracion'
    manual = 'manual'



class ModelInitMixin:
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

class User(ModelInitMixin, db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)

class Configuracion(ModelInitMixin, db.Model):
    __tablename__ = 'configuracion'
    id = db.Column(db.Integer, primary_key=True)
    nombre_empresa = db.Column(db.String(255), default='Mi Empresa')
    serie_factura = db.Column(db.String(50), default='F26-')
    numero_inicial_factura = db.Column(db.Integer, default=1)
    serie_rectificativa = db.Column(db.String(50), default='R26-')
    numero_inicial_rectificativa = db.Column(db.Integer, default=1)
    serie_presupuesto = db.Column(db.String(50), default='PR26-')
    numero_inicial_presupuesto = db.Column(db.Integer, default=1)
    logo_path = db.Column(db.String(255), default='')
    cif_nif = db.Column(db.String(50), default='')
    direccion_fiscal = db.Column(db.String(255), default='')
    codigo_postal = db.Column(db.String(15), default='')
    ciudad = db.Column(db.String(100), default='')
    provincia = db.Column(db.String(100), default='')
    pais = db.Column(db.String(100), default='España')
    telefono = db.Column(db.String(30), default='')
    email = db.Column(db.String(120), default='')
    website = db.Column(db.String(150), default='')
    metodo_pago_defecto = db.Column(db.String(100), default='Transferencia bancaria')
    moneda_defecto = db.Column(db.String(20), default='Euro (€)')
    impuesto_defecto = db.Column(db.String(20), default='21% IVA')
    recargo_equivalencia_default = db.Column(db.Boolean, default=False)
    nota_legal = db.Column(db.Text)
    ruta_certificado = db.Column(db.String(255))
    serie_albaran = db.Column(db.String(50), default='ALB26-')
    numero_inicial_albaran = db.Column(db.Integer, default=1)
    # --- CAPA PREVENTIVA CERO RIESGO FISCAL ---
    requiere_conciliacion = db.Column(db.Boolean, default=False, nullable=False)
    ultima_conciliacion_aeat = db.Column(db.DateTime, nullable=True)
    conciliacion_intentos_fallidos = db.Column(db.Integer, default=0, nullable=False)

class MetodoPago(ModelInitMixin, db.Model):
    __tablename__ = 'metodo_pago'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    tipo = db.Column(db.String(50)) # Transferencia, Contado, etc.
    entidad = db.Column(db.String(100))
    cuenta_iban = db.Column(db.String(100))
    defecto = db.Column(db.Boolean, default=False)

class Contacto(ModelInitMixin, db.Model):
    __tablename__ = 'contacto'
    id = db.Column(db.Integer, primary_key=True)
    nombre_fiscal = db.Column(db.String(255), nullable=False)
    tipo_documento = db.Column(db.String(20))
    numero_documento = db.Column(db.String(50), unique=True, nullable=False)
    tipo_contacto = db.Column(db.String(20), default='Cliente') # 'Cliente', 'Proveedor', 'Ambas'
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

    facturas = db.relationship('Factura', backref='contacto', lazy=True)
    gastos = db.relationship('Gasto', backref='contacto', lazy=True)
    presupuestos = db.relationship('Presupuesto', backref='contacto', lazy=True)
    albaranes = db.relationship('Albaran', backref='contacto', lazy=True)

class Producto(ModelInitMixin, db.Model):
    __tablename__ = 'producto'
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True)
    nombre = db.Column(db.String(255), nullable=False)
    descripcion = db.Column(db.Text)
    descripcion_adicional = db.Column(db.Text) 
    precio_unitario_base = db.Column(db.Numeric(10, 2), nullable=False)
    impuesto_defecto = db.Column(db.String(20), default='21% IVA')


# ==========================================
# DOMINIO DE FACTURACIÓN (VENTAS)
# ==========================================

class Factura(ModelInitMixin, db.Model):
    __tablename__ = 'factura'
    id = db.Column(db.Integer, primary_key=True)
    numero_factura = db.Column(db.String(50), unique=True, nullable=False)
    tipo_factura = db.Column(db.String(20), default='Ordinaria') # 'Ordinaria', 'Rectificativa'
    factura_rectificada_id = db.Column(db.Integer, db.ForeignKey('factura.id'), nullable=True)
    motivo_rectificacion = db.Column(db.String(255), nullable=True)
    # --- RELACIÓN AUTOREFERENCIAL ---
    factura_original = db.relationship('Factura', remote_side=[id], backref='rectificativas', lazy=True)

    # Restaurado: Control de organización visual de la interfaz de usuario
    tipo_pestana = db.Column(db.String(20), default='Emitida')
    
    # Separación limpia de Dominios y Estados
    estado_ui = db.Column(db.String(20), default='Borrador')      # 'Borrador', 'Emitida'
    estado_contable = db.Column(db.String(20), default='Pendiente') # 'Pendiente', 'Cobrada', 'Vencida'
    
    contacto_id = db.Column(db.Integer, db.ForeignKey('contacto.id'), nullable=False)
    metodo_pago_id = db.Column(db.Integer, db.ForeignKey('metodo_pago.id'), nullable=True)
    referencia = db.Column(db.String(100), nullable=True)
    referencia_presupuesto = db.Column(db.String(100), nullable=True)
    
    fecha_factura = db.Column(db.Date, nullable=False)
    fecha_vencimiento = db.Column(db.Date, nullable=True)
    
    # Totales acumulados calculados dinámicamente desde sus líneas
    total_base_imponible = db.Column(db.Numeric(10, 2), default=0.00)
    total_cuota_iva = db.Column(db.Numeric(10, 2), default=0.00)
    total_recargo_equivalencia = db.Column(db.Numeric(10, 2), default=0.00)
    total_factura = db.Column(db.Numeric(10, 2), default=0.00)

    # Relaciones relacionales estrictas
    lineas = db.relationship('FacturaLinea', backref='factura', cascade='all, delete-orphan', lazy=True)
    pagos = db.relationship('Pago', backref='factura', lazy=True)
    verifactu_registro = db.relationship('FacturaVerifactu', backref='factura', uselist=False, cascade='all, delete-orphan')
    verifactu_enviada = db.Column(db.Boolean, default=False)
    verifactu_estado = db.Column(db.String(20), default='Pendiente') # 'Aceptado', 'Rechazado'
    verifactu_csv = db.Column(db.String(100), nullable=True)

    # === campos para la retención de IRPF ===
    porcentaje_irpf = db.Column(db.Numeric(5, 2), nullable=False, default=0.0, server_default="0.0")
    total_retencion_irpf = db.Column(db.Numeric(10, 2), nullable=False, default=0.0, server_default="0.0")

    def lineas_json(self):
        """Convierte las líneas relacionales a la lista de diccionarios que las vistas y formularios esperan."""
        resultado = []
        lineas_relacion: list = self.lineas  # type: ignore[assignment]
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
    
    # Atributos fiscales explícitos por cada línea
    impuesto_tipo = db.Column(db.String(20), default='21% IVA') # '21% IVA', '7% IGIC', 'Exento', etc.
    porcentaje_iva = db.Column(db.Numeric(5, 2), default=0.00)
    porcentaje_recargo = db.Column(db.Numeric(5, 2), default=0.00)
    
    subtotal_linea = db.Column(db.Numeric(10, 2), nullable=False) # (unidades * precio) - descuento


# ==========================================
# CAPA EXCLUSIVA VERI*FACTU & AUDITORÍA
# ==========================================

class FacturaVerifactu(ModelInitMixin, db.Model):
    """
    Entidad satélite inmutable acoplada a la factura una vez es consolidada/emitida.
    Garantiza que operaciones ordinarias (marcar cobro) no alteren los metadatos fiscales de la AEAT.
    """
    __tablename__ = 'factura_verifactu'
    id = db.Column(db.Integer, primary_key=True)
    factura_id = db.Column(db.Integer, db.ForeignKey('factura.id'), unique=True, nullable=False)

    # Datos Criptográficos y de Encadenamiento (Hash Chain)
    fecha_hora_alta = db.Column(db.DateTime, nullable=False) # Precisión de segundos exigida legalmente
    hash_actual = db.Column(db.String(64), unique=True, nullable=False)  # SHA-256 normalizado del registro
    hash_anterior = db.Column(db.String(64), nullable=True)              # Enlace al bloque anterior

    # Almacenamiento del XML firmado para auditoría
    xml_firmado = db.Column(db.Text, nullable=False)
    
    # Estado de la pasarela con la AEAT
    estado_envio = db.Column(db.String(30), default='Pendiente')  # 'Pendiente', 'Enviado_Aceptado', 'Rechazado'
    csv_aeat = db.Column(db.String(100), nullable=True)            # Código Seguro de Verificación devuelto por Hacienda
    error_glosa = db.Column(db.Text, nullable=True)                # Traza informativa en caso de rechazo por el validador XSD

class RegistroEventos(ModelInitMixin, db.Model):
    """Log de Seguridad de Auditoría inalterable solicitado por la Ley Antifraude"""
    __tablename__ = 'registro_eventos'
    id = db.Column(db.Integer, primary_key=True)
    fecha_hora = db.Column(db.DateTime, nullable=False)
    tipo_evento = db.Column(db.String(50), nullable=False) # 'Alta_Factura', 'Anulacion_Factura', 'Acceso_Sistema', 'Error_Critico'
    descripcion = db.Column(db.Text, nullable=False)
    propiedades_adicionales = db.Column(db.Text) # Almacenamiento JSON con metadatos contextuales





# ==========================================
# DOMINIO DE COMPRAS, PRESUPUESTOS Y CAJA
# ==========================================

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
    estado_pago = db.Column(db.String(20), default='Recibida') # 'Recibida', 'Pagada', 'A revisar'
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
    estado = db.Column(db.String(20), default='Borrador') # 'Borrador', 'Enviado', 'Aceptado', 'Rechazado'
    notas = db.Column(db.Text)

    lineas = db.relationship('PresupuestoLinea', backref='presupuesto', cascade='all, delete-orphan', lazy=True)

    def lineas_json(self):
        """Convierte las líneas relacionales a la lista de diccionarios que las vistas y PDFs esperan."""
        resultado = []
        lineas_relacion: list = self.lineas  # type: ignore[assignment]
        for l in lineas_relacion:
            resultado.append({
                'tipo': 'linea',
                'id': l.id,
                'articulo_id': l.producto_id or '',
                'concepto': l.concepto,
                'informacion': l.informacion or '', # <-- CORREGIDO (Antes estaba duro '')
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

class Pago(ModelInitMixin, db.Model):
    __tablename__ = 'pago'
    id = db.Column(db.Integer, primary_key=True)
    fecha_pago = db.Column(db.Date, nullable=False)
    tipo_movimiento = db.Column(db.String(20), nullable=False) # 'Ingreso', 'Egreso'
    factura_id = db.Column(db.Integer, db.ForeignKey('factura.id'), nullable=True)
    gasto_id = db.Column(db.Integer, db.ForeignKey('gasto.id'), nullable=True)
    metodo_pago = db.Column(db.String(50))
    importe = db.Column(db.Numeric(10, 2), nullable=False)
    cuenta_bancaria_destino = db.Column(db.String(100))
    estado = db.Column(db.String(20), default='Conciliado') # 'Conciliado', 'Pendiente'


# ==========================================
# DOMINIO DE ALBARANES (LOGÍSTICA / ENTREGAS)
# ==========================================

class Albaran(ModelInitMixin, db.Model):
    __tablename__ = 'albaran'
    id = db.Column(db.Integer, primary_key=True)
    numero_albaran = db.Column(db.String(50), unique=True, nullable=False)
    contacto_id = db.Column(db.Integer, db.ForeignKey('contacto.id'), nullable=False)
    metodo_pago_id = db.Column(db.Integer, db.ForeignKey('metodo_pago.id'), nullable=True)
    
    referencia = db.Column(db.String(100), nullable=True)
    referencia_presupuesto = db.Column(db.String(100), nullable=True)
    referencia_factura = db.Column(db.String(100), nullable=True) # Para saber en qué factura acabó este albarán
    
    fecha_emision = db.Column(db.Date, nullable=False)
    fecha_entrega = db.Column(db.Date, nullable=True)
    
    # Totales acumulados (Siguiendo tu patrón contable)
    total_base_imponible = db.Column(db.Numeric(10, 2), default=0.00)
    total_impuestos = db.Column(db.Numeric(10, 2), default=0.00)
    total_albaran = db.Column(db.Numeric(10, 2), default=0.00)
    
    # Estados del albarán: 'Borrador', 'Emitido', 'Facturado', 'Anulado'
    estado = db.Column(db.String(20), default='Borrador') 
    notas = db.Column(db.Text)

    lineas = db.relationship('AlbaranLinea', backref='albaran', cascade='all, delete-orphan', lazy=True)

    def lineas_json(self):
        """Convierte las líneas relacionales al formato de diccionario esperado por las vistas."""
        resultado = []
        lineas_relacion: list = self.lineas  # type: ignore[assignment]
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


# ==========================================
# CAPA DE SEGURIDAD Y BACKUPS AUTOMÁTICOS
# ==========================================

class ConfiguracionBackup(ModelInitMixin, db.Model):
    __tablename__ = 'configuracion_backup'
    
    id = db.Column(db.Integer, primary_key=True)
    proveedor = db.Column(db.String(50), nullable=False, default='LOCAL') # 'LOCAL', 'GOOGLE_DRIVE', 'MEGA', 'SFTP'
    ruta_local_destino = db.Column(db.String(255), nullable=True, default='')
    
    # Campos dinámicos para credenciales aisladas o tokens de proveedores
    mega_token = db.Column(db.Text, nullable=True, default='')
    sftp_host = db.Column(db.String(255), nullable=True, default='')
    sftp_port = db.Column(db.Integer, nullable=False, default=22)
    sftp_user = db.Column(db.String(100), nullable=True, default='')
    
    frecuencia_cron = db.Column(db.String(50), nullable=False, default='DAILY') # 'HOURLY', 'DAILY', 'WEEKLY'
    actualizado_en = db.Column(db.DateTime, default=db.func.current_timestamp(), onupdate=db.func.current_timestamp())


# ==========================================
# CAPA DE CONCIALIACIÓN DE FACTURAS (CERO RIESGO FISCAL)
# ==========================================

class ConciliacionFacturas(ModelInitMixin, db.Model):
    __tablename__ = 'conciliacion_facturas'

    id = db.Column(db.Integer, primary_key=True)
    numero_factura = db.Column(db.String(50), nullable=False)
    estado_conciliacion = db.Column(db.Enum(EstadoConciliacion), default=EstadoConciliacion.pendiente_verificar, nullable=False)
    origen_deteccion = db.Column(db.Enum(OrigenDeteccion), nullable=False)
    resuelto = db.Column(db.Boolean, default=False, nullable=False)
    fecha_deteccion = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


# ==========================================
# INICIALIZADOR Y GESTOR DE MIGRACIONES AUTOMÁTICAS
# ==========================================

def init_db(app):
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