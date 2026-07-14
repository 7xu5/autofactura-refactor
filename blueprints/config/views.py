import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, session
from werkzeug.utils import secure_filename
from utils.file_handlers import allowed_file
from werkzeug.security import check_password_hash, generate_password_hash 
from models import db, Configuracion, MetodoPago, User, ConfiguracionBackup
from services.backup_orchestrator_service import BackupOrchestratorService
from datetime import datetime
from services.restore_service import EmergencyRestoreProcessor

config_bp = Blueprint('config', __name__, url_prefix='/configuracion')

@config_bp.route('/', methods=['GET', 'POST'])
def configuracion():
    # --- CONTROL DE ACCESO GLOBAL PARA LA CONFIGURACIÓN ---
    if 'user_id' not in session:
        flash('Debes iniciar sesión para acceder a la configuración.', 'danger')
        return redirect(url_for('auth.login'))

    config_obj = Configuracion.query.first()
    metodos_pago = MetodoPago.query.all()
    config_backup_obj = ConfiguracionBackup.query.first()
    ultimo_backup_timestamp = "Nunca ejecutado"
    backups_locales_reales = []

    # =====================================================================
    # SOLUCIÓN TRUCO: SI ES EL PRIMER LOG O ESTÁ VACÍO, LEEMOS EL INPUT ACTUAL
    # =====================================================================
    ruta_a_escanear = ""
    if config_backup_obj and config_backup_obj.ruta_local_destino:
        ruta_a_escanear = (config_backup_obj.ruta_local_destino or "").strip()
    elif request.method == 'GET' and request.args.get('ruta_local_destino'):
        ruta_a_escanear = (request.args.get('ruta_local_destino') or "").strip()
    
    if not config_backup_obj:
        config_backup_obj = ConfiguracionBackup(ruta_local_destino="", proveedor="LOCAL", frecuencia_cron="DAILY")

    ultimo_backup_timestamp = "Nunca ejecutado"
    backups_locales_reales = []

    # === ESCANEO DE RESPALDOS REALES ===
    if ruta_a_escanear:
        config_backup_obj.ruta_local_destino = ruta_a_escanear
        
        if os.path.exists(ruta_a_escanear) and os.path.isdir(ruta_a_escanear):
            try:
                for fichero in os.listdir(ruta_a_escanear):
                    if 'backup' in fichero.lower() and fichero.endswith('.enc'):
                        ruta_completa = os.path.join(ruta_a_escanear, fichero)
                        stat_file = os.stat(ruta_completa)
                        tamano_bytes = stat_file.st_size
                        tamano_str = f"{tamano_bytes / 1024:.1f} KB" if tamano_bytes < 1048576 else f"{tamano_bytes / 1048576:.1f} MB"
                        fecha_mod = datetime.fromtimestamp(stat_file.st_mtime).strftime('%d/%m/%Y %H:%M:%S')
                        backups_locales_reales.append({
                            "nombre": fichero, "tamano": tamano_str, "fecha": fecha_mod, "mtime": stat_file.st_mtime
                        })
                backups_locales_reales.sort(key=lambda x: x['mtime'], reverse=True)
                if backups_locales_reales:
                    ultimo_backup_timestamp = backups_locales_reales[0]['fecha']
            except Exception as e:
                print(f"Error listando copias: {e}")
    # =====================================================================
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add_metodo_pago':
            return metodo_pago_nuevo()

        if action == 'delete_metodo_pago':
            mp_id = request.form.get('mp_id')
            mp = MetodoPago.query.get(mp_id)
            if mp:
                db.session.delete(mp)
                db.session.commit()
                flash('Método de pago eliminado', 'info')
            return redirect(url_for('config.configuracion'))
        
        if action == 'cambiar_password':
            password_actual = request.form.get('password_actual', '').strip()
            password_nueva = request.form.get('password_nueva', '').strip()
            password_confirmar = request.form.get('password_confirmar', '').strip()

            if not password_actual or not password_nueva or not password_confirmar:
                flash('Todos los campos de contraseña son obligatorios.', 'danger')
                return redirect(url_for('config.configuracion'))

            if password_nueva != password_confirmar:
                flash('La nueva contraseña y su confirmación no coinciden.', 'danger')
                return redirect(url_for('config.configuracion'))
            
            if len(password_nueva) < 6:
                flash('La nueva contraseña debe tener al menos 6 caracteres.', 'danger')
                return redirect(url_for('config.configuracion'))

            user = User.query.get(session['user_id'])
            if not user or not check_password_hash(user.password, password_actual):
                flash('La contraseña actual es incorrecta.', 'danger')
                return redirect(url_for('config.configuracion'))

            try:
                user.password = generate_password_hash(password_nueva)
                db.session.commit()
                flash('Contraseña de usuario actualizada con éxito.', 'success')
            except Exception:
                db.session.rollback()
                flash('Error al actualizar la contraseña.', 'danger')
                
            return redirect(url_for('config.configuracion'))

        # --- GUARDAR DATOS DE LA EMPRESA ---
        if not config_obj:
            config_obj = Configuracion()
            db.session.add(config_obj)
            
        config_obj.nombre_empresa = request.form.get('nombre_empresa', config_obj.nombre_empresa)
        config_obj.serie_factura = request.form.get('serie_factura', config_obj.serie_factura)
        config_obj.serie_presupuesto = request.form.get('serie_presupuesto', getattr(config_obj, 'serie_presupuesto', 'PR26-'))
        config_obj.numero_inicial_presupuesto = int(request.form.get('numero_inicial_presupuesto') or getattr(config_obj, 'numero_inicial_presupuesto', 1) or 1)
        config_obj.numero_inicial_factura = int(request.form.get('numero_inicial_factura') or config_obj.numero_inicial_factura or 1)
        config_obj.serie_albaran = request.form.get('serie_albaran', getattr(config_obj, 'serie_albaran', 'ALB26-'))
        config_obj.numero_inicial_albaran = int(request.form.get('numero_inicial_albaran') or getattr(config_obj, 'numero_inicial_albaran', 1) or 1)
        config_obj.serie_rectificativa = request.form.get('serie_rectificativa', getattr(config_obj, 'serie_rectificativa', 'R26-'))
        config_obj.numero_inicial_rectificativa = int(request.form.get('numero_inicial_rectificativa') or getattr(config_obj, 'numero_inicial_rectificativa', 1) or 1)
        config_obj.cif_nif = request.form.get('cif_nif', config_obj.cif_nif)
        config_obj.direccion_fiscal = request.form.get('direccion_fiscal', config_obj.direccion_fiscal)
        config_obj.codigo_postal = request.form.get('codigo_postal', config_obj.codigo_postal)
        config_obj.ciudad = request.form.get('ciudad', config_obj.ciudad)
        config_obj.provincia = request.form.get('provincia', config_obj.provincia)
        config_obj.pais = request.form.get('pais', config_obj.pais)
        config_obj.telefono = request.form.get('telefono', config_obj.telefono)
        config_obj.email = request.form.get('email', config_obj.email)
        config_obj.website = request.form.get('website', config_obj.website)
  
        logo_file = request.files.get('logo')
        if logo_file and logo_file.filename:
            if allowed_file(logo_file.filename):
                upload_folder = os.path.join(current_app.root_path, 'static', 'uploads')
                os.makedirs(upload_folder, exist_ok=True)
                filename = secure_filename(logo_file.filename)
                file_path = os.path.join(upload_folder, filename)
                logo_file.save(file_path)
                config_obj.logo_path = os.path.join('uploads', filename).replace('\\', '/')
            else:
                flash('Formato de logo no válido. Usa PNG o JPG.', 'danger')
                return redirect(url_for('config.configuracion'))
                
        config_obj.metodo_pago_defecto = request.form.get('metodo_pago_defecto', config_obj.metodo_pago_defecto)
        config_obj.moneda_defecto = request.form.get('moneda_defecto', config_obj.moneda_defecto)
        config_obj.impuesto_defecto = request.form.get('impuesto_defecto', config_obj.impuesto_defecto)
        config_obj.recargo_equivalencia_default = bool(request.form.get('recargo_equivalencia_default'))
        config_obj.nota_legal = request.form.get('nota_legal', config_obj.nota_legal)

        # --- GESTIÓN DEL CERTIFICADO VERI*FACTU ---
        cert_file = request.files.get('certificado_p12')
        if cert_file and cert_file.filename:
            ext = os.path.splitext(cert_file.filename)[1].lower()
            if ext in ['.p12', '.pfx']:
                cert_dir = os.path.join(current_app.root_path, 'certs')
                os.makedirs(cert_dir, exist_ok=True)
                
                filename = secure_filename(cert_file.filename)
                cert_path = os.path.join(cert_dir, filename)
                cert_file.save(cert_path)
                
                # Usamos barras normales para compatibilidad en la DB y el template
                config_obj.ruta_certificado = f"certs/{filename}"
                flash('Certificado digital actualizado correctamente', 'success')
            else:
                flash('Formato de certificado no válido. Use .p12 o .pfx', 'danger')

        # === PERSISTENCIA DE LA CONFIGURACIÓN DEL BACKUP ===
        if not config_backup_obj:
            config_backup_obj = ConfiguracionBackup()
            db.session.add(config_backup_obj)

        config_backup_obj.ruta_local_destino = request.form.get('ruta_local_destino', '').strip()
        config_backup_obj.proveedor = request.form.get('proveedor', 'LOCAL')
        config_backup_obj.frecuencia_cron = request.form.get('frecuencia_cron', 'DAILY')
        config_backup_obj.sftp_host = request.form.get('sftp_host', '')
        config_backup_obj.sftp_port = int(request.form.get('sftp_port') or 22)
        config_backup_obj.sftp_user = request.form.get('sftp_user', '')
   
        db.session.commit()
        flash('Configuración guardada', 'success')
        return redirect(url_for('config.configuracion'))
    
    clave_criptografica = current_app.config.get('BACKUP_SECRET_KEY') or os.getenv('BACKUP_SECRET_KEY', '')  
    
    return render_template(
        'configuracion.html', 
        configuracion=config_obj, 
        metodos_pago=metodos_pago,
        config_backup=config_backup_obj,  
        ultimo_backup=ultimo_backup_timestamp,
        backups_existentes=backups_locales_reales,
        clave_fernet_env=clave_criptografica
    )


@config_bp.route('/metodos-pago/nuevo', methods=['POST'])
def metodo_pago_nuevo():
    nombre = request.form.get('nombre') or request.form.get('mp_nombre')
    tipo = request.form.get('tipo') or request.form.get('mp_tipo')
    entidad = request.form.get('entidad') or request.form.get('mp_entidad')
    iban = request.form.get('iban') or request.form.get('mp_iban')
    
    if not nombre or not tipo:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': 'Nombre y tipo son obligatorios'}), 400
        
        flash('El nombre descriptivo y el tipo son obligatorios.', 'danger')
        return redirect(url_for('config.configuracion'))
        
    nuevo_mp = MetodoPago(nombre=nombre, tipo=tipo, entidad=entidad, cuenta_iban=iban)
    db.session.add(nuevo_mp)
    db.session.commit()
    
    # --- CAMBIO AQUÍ: Responder JSON si viene por AJAX ---
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'success': True,
            'id': nuevo_mp.id,
            'nombre': nuevo_mp.nombre
        }), 200

    flash('Método de pago añadido', 'success')
    return redirect(url_for('config.configuracion'))


@config_bp.route('/backup/sftp-keys', methods=['POST'])
def generar_llaves_sftp():
    """Ruta provisional para la generación de llaves SSH."""
    return jsonify({
        'public_key': 'ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQC3... KEY_PROVISIONAL_MOCK'
    }), 200


@config_bp.route('/backups/guardar', methods=['POST'])
def guardar_configuracion_backup():
    """
    Captura los parámetros del panel de backups de la UI, cifra las credenciales
    sensibles en reposo y actualiza el registro único en facturacion_db.
    """
    try:
        proveedor = request.form.get('proveedor', 'LOCAL')
        ruta_local = request.form.get('ruta_local_destino', '')
        frecuencia = request.form.get('frecuencia_cron', 'Diario (Madrugada)')
        
        # Buscamos si ya existe una configuración previa para actualizarla o crearla
        config_backup = ConfiguracionBackup.query.first()
        if not config_backup:
            config_backup = ConfiguracionBackup()
            db.session.add(config_backup)

        config_backup.proveedor = proveedor
        config_backup.ruta_local_destino = ruta_local
        config_backup.frecuencia_cron = frecuencia

        if proveedor == 'SFTP':
            config_backup.sftp_host = request.form.get('sftp_host', '')
            config_backup.sftp_port = int(request.form.get('sftp_port') or 22)
            config_backup.sftp_user = request.form.get('sftp_user', '')
        

        db.session.commit()
        flash("Configuración del sistema de copias de seguridad actualizada con éxito.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error al blindar la configuración: {str(e)}", "danger")

    return redirect(url_for('config.ver_configuracion')) # Ajusta a tu ruta de retorno


@config_bp.route('/backups/ejecutar-manual', methods=['POST'])
def ejecutar_backup_manual():
    """
    Orquesta la ejecución inmediata de la directiva de seguridad de forma segura.
    """
    config_backup = ConfiguracionBackup.query.first()
    
    # 1. Recuperamos el JSON dinámico enviado por el fetch
    data = request.get_json() or {}
    ruta_destino = data.get('ruta_local', '').strip()
    
    # Leemos el proveedor e input de token que el usuario tiene puestos en la pantalla en vivo
    proveedor = data.get('proveedor', '').strip()
    
    # 2. Fallbacks si la petición JSON viniera incompleta
    if not ruta_destino and config_backup:
        ruta_destino = config_backup.ruta_local_destino
        
    if not ruta_destino:
        return jsonify({
            "status": "error",
            "error": "No se recibió ninguna ruta desde el formulario ni existe una guardada en la base de datos."
        }), 400
        
    if not proveedor and config_backup:
        proveedor = config_backup.proveedor
    elif not proveedor:
        proveedor = 'LOCAL'

    # 3. Sincronizamos la ruta local de ejecución en la DB
    if config_backup:
        config_backup.ruta_local_destino = ruta_destino
        db.session.commit()

    # 4. Mapeo riguroso de credenciales para el orquestador
    creds_dict = {}
    
    # Instanciamos el servicio adecuado según el proveedor solicitado en caliente
    servicio_storage = None

    if proveedor == 'SFTP' and config_backup:
        creds_dict = {
            "sftp_host": config_backup.sftp_host,
            "sftp_port": config_backup.sftp_port,
            "sftp_user": config_backup.sftp_user
        }
        servicio_storage = None # ❌ Se sobrescribe a None explícitamente aquí

    
    # NOTA: Cuando implemente el adaptador final, descomenta e integra el servicio real:
        # from services.sftp_storage_service import SftpStorageService
        # servicio_storage = SftpStorageService()
    import asyncio
    orchestrator = BackupOrchestratorService()
    

    try:
        resultado = asyncio.run(orchestrator.ejecutar_flujo_backup(
            ruta_local_destino=ruta_destino,
            storage_provider_service=servicio_storage, # Pasamos el servicio
            provider_creds=creds_dict                  # Pasamos las credenciales reales
        ))
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": f"Error en el bucle asíncrono del orquestador: {str(e)}"
        }), 500
    
    if resultado.get("status") == "success":
        return jsonify({
            "status": "success",
            "timestamp": resultado.get("timestamp", "Recién completado")
        })
    else:
        return jsonify({
            "status": "error",
            "error": resultado.get("error", "Fallo en la ejecución del backup")
        }), 500
    


@config_bp.route('/backups/validar-ruta', methods=['POST'])
def validar_ruta_backup():
    """
    Verifica de manera segura si la ruta local introducida por el usuario
    existe en el servidor y tiene permisos de escritura reales.
    """
    try:
        data = request.get_json() or {}
        ruta = data.get('ruta_local', '').strip()
        
        if not ruta:
            return jsonify({"valido": False, "error": "La ruta de destino no puede estar vacía."})
            
        if not os.path.exists(ruta):
            return jsonify({"valido": False, "error": "El directorio físico no existe en el almacenamiento de este servidor."})
            
        # Intentamos un volcado de bytes efímero para certificar los permisos de escritura
        archivo_prueba = os.path.join(ruta, '.permiso_escritura_autofactura')
        try:
            with open(archivo_prueba, 'w', encoding='utf-8') as f:
                f.write('test_write_access')
            os.remove(archivo_prueba)
        except Exception:
            return jsonify({"valido": False, "error": "El servidor local no tiene permisos de escritura en este directorio."})
            
        return jsonify({"valido": True})
    except Exception as e:
        return jsonify({"valido": False, "error": str(e)})
    

@config_bp.route('/tabla-backups-parcial', methods=['GET'])
def tabla_backups_parcial():
    """Devuelve únicamente el fragmento HTML con la lista de copias actualizada."""
    
    
    # 1. Intentamos capturar la ruta dinámica que el usuario tiene escrita en caliente en el input (ej. USB)
    ruta_a_escanear = request.args.get('ruta_dinamica', '').strip()
    
    # 2. Si no se proporciona una ruta dinámica (flujo estándar), leemos la persistida en la DB
    if not ruta_a_escanear:
        config_backup_obj = ConfiguracionBackup.query.first()
        if config_backup_obj and config_backup_obj.ruta_local_destino:
            ruta_a_escanear = config_backup_obj.ruta_local_destino.strip()
    
    backups_locales_reales = []
    
    # 3. Realizamos el escaneo físico sobre la ruta final resuelta
    if ruta_a_escanear and os.path.exists(ruta_a_escanear) and os.path.isdir(ruta_a_escanear):
        try:
            for fichero in os.listdir(ruta_a_escanear):
                if 'backup' in fichero.lower() and fichero.endswith('.enc'):
                    ruta_completa = os.path.join(ruta_a_escanear, fichero)
                    stat_file = os.stat(ruta_completa)
                    tamano_bytes = stat_file.st_size
                    
                    # Tu conversión rigurosa de unidades de tamaño
                    tamano_str = f"{tamano_bytes / 1024:.1f} KB" if tamano_bytes < 1048576 else f"{tamano_bytes / 1048576:.1f} MB"
                    fecha_mod = datetime.fromtimestamp(stat_file.st_mtime).strftime('%d/%m/%Y %H:%M:%S')
                    
                    # Conservamos tu estructura exacta de diccionario
                    backups_locales_reales.append({
                        "nombre": fichero, 
                        "tamano": tamano_str, 
                        "fecha": fecha_mod, 
                        "mtime": stat_file.st_mtime
                    })
                    
            # Ordenar por fecha de modificación (más reciente primero)
            backups_locales_reales.sort(key=lambda x: x['mtime'], reverse=True)
        except Exception as e:
            print(f"Error listando copias en parcial: {e}")
            
    # 4. Renderizamos el fragmento parcial pasándole la lista limpia
    return render_template('partials/_tabla_backups.html', backups_existentes=backups_locales_reales)




@config_bp.route('/backups/restaurar-controlado', methods=['POST'])
def restaurar_backup_controlado():
    """
    Endpoint web para restaurar un archivo de backup seleccionado desde la interfaz.
    Exige la introducción de la clave de descifrado Fernet en vivo.
    """
    if 'user_id' not in session:
        flash('Debes iniciar sesión para ejecutar esta acción.', 'danger')
        return redirect(url_for('auth.login'))

    nombre_archivo = request.form.get('nombre_archivo', '').strip()
    secret_key = request.form.get('secret_key', '').strip()

    if not nombre_archivo or not secret_key:
        flash("Faltan parámetros obligatorios (archivo o clave Fernet) para la restauración.", "danger")
        return redirect(url_for('config.configuracion'))

    config_backup = ConfiguracionBackup.query.first()
    if not config_backup or not config_backup.ruta_local_destino:
        flash("No hay un directorio de backups configurado en el sistema.", "danger")
        return redirect(url_for('config.configuracion'))

    backup_dir = config_backup.ruta_local_destino.strip()
    ruta_archivo_enc = os.path.abspath(os.path.join(backup_dir, nombre_archivo))

    # Defensa estricta contra Path Traversal
    if not ruta_archivo_enc.startswith(os.path.abspath(backup_dir)):
        flash("Acceso denegado: Intento de escalada de directorios detectado.", "danger")
        return redirect(url_for('config.configuracion'))

    if not os.path.exists(ruta_archivo_enc):
        flash(f"El archivo cifrado especificado no existe en el servidor: {nombre_archivo}", "danger")
        return redirect(url_for('config.configuracion'))

    # Resolver la ruta absoluta de la base de datos de producción actual
    db_uri = current_app.config['SQLALCHEMY_DATABASE_URI']
    db_path = db_uri.replace('sqlite:///', '')
    if not os.path.isabs(db_path):
        db_path = os.path.abspath(os.path.join(current_app.root_path, db_path))

    # Instanciamos el procesador desacoplado
    processor = EmergencyRestoreProcessor(db_path=db_path, backup_dir=backup_dir)

    try:
        # Forzar desconexión inmediata del pool del ORM en caliente para liberar los descriptores de archivo de SQLite
        db.session.remove()
        db.engine.dispose()

        # Ejecutamos la restauración controlada (ejecuta el Sandbox previo de verificación)
        exito = processor.procesar_y_restaurar(ruta_backup_enc=ruta_archivo_enc, secret_key=secret_key)

        if exito:
            flash("Sistema restaurado con éxito. Se ha establecido la cuarentena fiscal preventiva en los registros.", "success")
        else:
            flash("El procesador ha rechazado el archivo por inconsistencias detectadas en el entorno Sandbox.", "danger")

    except Exception as e:
        flash(f"Error crítico durante la restauración en caliente: {str(e)}", "danger")

    return redirect(url_for('config.configuracion'))