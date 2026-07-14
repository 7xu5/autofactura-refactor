from app.extensions import db
from models.mixins import ModelInitMixin

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

class ConfiguracionBackup(ModelInitMixin, db.Model):
    __tablename__ = 'configuracion_backup'
    id = db.Column(db.Integer, primary_key=True)
    proveedor = db.Column(db.String(50), nullable=False, default='LOCAL')
    ruta_local_destino = db.Column(db.String(255), nullable=True, default='')
    mega_token = db.Column(db.Text, nullable=True, default='')
    sftp_host = db.Column(db.String(255), nullable=True, default='')
    sftp_port = db.Column(db.Integer, nullable=False, default=22)
    sftp_user = db.Column(db.String(100), nullable=True, default='')
    frecuencia_cron = db.Column(db.String(50), nullable=False, default='DAILY')
    actualizado_en = db.Column(db.DateTime, default=db.func.current_timestamp(), onupdate=db.func.current_timestamp())

class RegistroEventos(ModelInitMixin, db.Model):
    __tablename__ = 'registro_eventos'
    id = db.Column(db.Integer, primary_key=True)
    fecha_hora = db.Column(db.DateTime, nullable=False)
    tipo_evento = db.Column(db.String(50), nullable=False)
    descripcion = db.Column(db.Text, nullable=False)
    propiedades_adicionales = db.Column(db.Text)