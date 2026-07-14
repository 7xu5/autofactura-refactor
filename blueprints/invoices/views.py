import base64
from datetime import datetime, date
from decimal import Decimal
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, make_response, abort, current_app
from sqlalchemy.orm import joinedload
from sqlalchemy import select, func
from models import db, Contacto, Factura, FacturaLinea, Producto, MetodoPago, Configuracion
from utils.sequence_generators import generate_invoice_number, generate_draft_number
import os
from services.verifactu_service import VerifactuOrchestrator
from services.invoice_service import InvoiceService
from utils.pdf_generator import PDFGenerator

invoices_bp = Blueprint('invoices', __name__, url_prefix='/facturas')


# ---------------------------------------------------------------------------
# Helpers privados
# ---------------------------------------------------------------------------

def _get_productos_lista():
    """Devuelve la lista de productos serializada como diccionarios para el frontend."""
    return [
        {
            'nombre': p.nombre,
            'precio_unitario_base': float(p.precio_unitario_base),
            'impuesto_defecto': p.impuesto_defecto,
            'descripcion_adicional': p.descripcion_adicional,
        }
        for p in Producto.query.order_by(Producto.nombre).all()
    ]


def _get_form_context():
    """Devuelve los recursos comunes que necesitan los formularios de factura."""
    return {
        'contactos': Contacto.query.filter(Contacto.tipo_contacto.in_(['Cliente', 'Ambas'])).order_by(Contacto.nombre_fiscal).all(),
        'productos': _get_productos_lista(),
        'metodos_pago': MetodoPago.query.all(),
        'configuracion': Configuracion.query.first(),
    }

def _get_logo_base64_shared(config):
    """Busca el logotipo corporativo en el disco y lo devuelve convertido en una URI Base64."""
    logo_base64 = ""
    logo_path = config.logo_path if config and config.logo_path else ""
    if logo_path:
        filename = os.path.basename(logo_path)
        posible_path = os.path.join(current_app.root_path, 'static', 'uploads', filename)
        if os.path.exists(posible_path):
            logo_path = posible_path
        else:
            logo_path = os.path.join(current_app.root_path, 'static', filename)
    else:
        logo_path = os.path.join(current_app.root_path, 'static', 'logo.png')

    if os.path.exists(logo_path) and os.path.isfile(logo_path):
        try:
            with open(logo_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                ext = os.path.splitext(logo_path)[1].lower().replace('.', '')
                if ext not in ['png', 'jpg', 'jpeg']: ext = 'png'
                logo_base64 = f"data:image/{ext};base64,{encoded_string}"
        except Exception:
            logo_base64 = ""
    return logo_base64

def _calcular_totales(cliente, pestana, total_base, total_iva, porcentaje_irpf=Decimal('0.00')):
    """Calcula el recargo de equivalencia y el total final de la factura."""
    recargo = cliente.recargo_equivalencia and pestana != 'Borrador'
    recargo_total = (
        (total_base * Decimal('5.20') / Decimal('100')).quantize(Decimal('0.01'))
        if recargo else Decimal('0.00')
    )
    # NUEVO: Calcular la retención de IRPF sobre la Base Imponible
    total_retencion_irpf = (total_base * (porcentaje_irpf / Decimal('100'))).quantize(Decimal('0.01'))
    
    # NUEVO: El IRPF resta del total definitivo
    total_factura = (total_base + total_iva + recargo_total - total_retencion_irpf).quantize(Decimal('0.01'))
    return recargo_total, total_retencion_irpf, total_factura


def _intentar_envio_verifactu(factura_id, cert_pass, flash_exito=True):
    """
    Intenta firmar y enviar una factura a la AEAT.
    Emite mensajes flash según el resultado.
    Devuelve True si tuvo éxito, False en caso contrario.
    """
    config = Configuracion.query.first()
    if not config or not config.ruta_certificado:
        flash('Certificado no configurado en el sistema.', 'warning')
        return False

    ruta_cert = os.path.join(current_app.root_path, config.ruta_certificado)
    try:
        exito, mensaje = VerifactuOrchestrator.emitir_y_enviar_factura(factura_id, ruta_cert, cert_pass)
        if exito:
            if flash_exito:
                flash('Factura emitida y enviada a la AEAT.', 'success')
        else:
            flash(f'Factura guardada pero no enviada: {mensaje}', 'warning')
        return exito
    except Exception as e:
        flash(f'Factura guardada, pero error en envío: {str(e)}', 'warning')
        return False


# ---------------------------------------------------------------------------
# Vistas
# ---------------------------------------------------------------------------

@invoices_bp.route('/')
def facturas():
    pestana = request.args.get('pestana', 'Emitida')
    query = Factura.query
    
    # --- NUEVA LÓGICA EXCLUSIVA DE FILTRADO POR PESTAÑA ---
    if pestana == 'Emitida':
        # SOLO facturas normales asentadas/emitidas (Excluimos borradores y rectificativas)
        query = query.filter(
            Factura.tipo_factura == 'Ordinaria',
            Factura.estado_contable != 'Borrador'
        )
    elif pestana == 'Rectificativa':
        # SOLO facturas rectificativas oficiales (Excluimos borradores)
        query = query.filter(
            Factura.tipo_factura == 'Rectificativa',
            Factura.estado_contable != 'Borrador'
        )
    elif pestana == 'Borrador':
        # AQUÍ VAN TODOS LOS BORRADORES (sean ordinarios o rectificativos)
        query = query.filter(Factura.estado_contable == 'Borrador')
        
    elif pestana == 'Verifactu':
        # Mantener tu estándar dinámico usando getattr para la relación de Verifactu
        relacion_verifactu = getattr(Factura, 'verifactu_registro')
        query = query.join(relacion_verifactu)
        
        # Filtramos inspeccionando la clase del modelo relacionado
        modelo_verifactu = relacion_verifactu.property.mapper.class_

        # Mostramos las aceptadas Y las rechazadas/con error
        query = query.filter(
            modelo_verifactu.estado_envio.in_(['Enviado_Aceptado', 'Rechazado', 'Error'])
        )

    # --- SISTEMA DE BÚSQUEDA ---
    search = request.args.get('q', '').strip()
    if search:
        query = query.join(Contacto).filter(
            (Factura.numero_factura.ilike(f'%{search}%')) |
            (Contacto.nombre_fiscal.ilike(f'%{search}%')) |
            (Factura.referencia.ilike(f'%{search}%'))
        )

    facturas_lista = (
        query
        .options(joinedload(getattr(Factura, 'verifactu_registro')))
        .order_by(Factura.fecha_factura.desc(), Factura.numero_factura.desc())
        .all()
    )
    return render_template('facturas.html', facturas=facturas_lista, pestana=pestana, search=search)

@invoices_bp.route('/crear', methods=['GET', 'POST'])
def factura_crear():
    ctx = _get_form_context()

    if request.method == 'POST':
        cliente_id = request.form.get('contacto_id')
        cliente_id = int(cliente_id) if cliente_id and cliente_id.isdigit() else None
        metodo_pago_id = request.form.get('metodo_pago_id')
        selected_metodo_pago_id = int(metodo_pago_id) if metodo_pago_id and metodo_pago_id.isdigit() else None
        pestana = 'Borrador' if request.form.get('guardar_borrador') else 'Emitida'

        # Detectamos la pestaña/intención del usuario
        es_borrador = bool(request.form.get('guardar_borrador'))
        pestana = 'Borrador' if es_borrador else 'Emitida'

        if cliente_id:
            cliente = db.session.get(Contacto, cliente_id)
        else:
            cliente = None
            
        if not cliente:
            # Si falla el cliente, regeneramos el número según el tipo seleccionado
            num_error = request.form.get('numero_factura', '').strip()
            if not num_error:
                num_error = generate_draft_number() if es_borrador else generate_invoice_number()

            flash('Debe seleccionar un cliente válido.', 'danger')
            return render_template('factura_form.html', **ctx,
                                   numero_factura=num_error,
                                   lineas=InvoiceService.reconstruir_lineas_pantalla(request.form),
                                   selected_contacto_id=cliente_id,
                                   selected_metodo_pago_id=selected_metodo_pago_id)

        # ASIGNACIÓN CORRECTA: Priorizamos la acción del botón pulsado sobre el input visual
        # Si el input está vacío o si traía un prefijo automático previo, lo recalculamos en servidor
        form_num = request.form.get('numero_factura', '').strip()
        
        if not form_num or form_num.startswith('BORR'):
            # Si pulsó guardar borrador -> Serie BORR. Si pulsó emitir -> Serie F oficial
            numero_factura = generate_draft_number() if es_borrador else generate_invoice_number()
        else:
            # Si el usuario escribió un número personalizado de forma explícita
            numero_factura = form_num

        if Factura.query.filter_by(numero_factura=numero_factura).first():
            flash('Ya existe una factura con ese número.', 'danger')
            return render_template('factura_form.html', **ctx,
                                   numero_factura=numero_factura, 
                                   lineas=InvoiceService.reconstruir_lineas_pantalla(request.form),
                                   selected_contacto_id=cliente_id,
                                   selected_metodo_pago_id=selected_metodo_pago_id)

        instancias_lineas, total_base, total_iva, error = InvoiceService.procesar_lineas_form(request.form, cliente, pestana, tipo_factura='Ordinaria')
        if error:
            flash(error, 'danger')
            return render_template('factura_form.html', **ctx,
                                   numero_factura=numero_factura, 
                                   lineas=InvoiceService.reconstruir_lineas_pantalla(request.form),
                                   selected_contacto_id=cliente_id,
                                   selected_metodo_pago_id=selected_metodo_pago_id)
        
        porcentaje_irpf = Decimal(request.form.get('porcentaje_irpf', '0')).quantize(Decimal('0.01'))


        recargo_total, total_retencion_irpf, total_factura = _calcular_totales(cliente, pestana, total_base, total_iva, porcentaje_irpf)

        fecha_factura = request.form.get('fecha_factura')
        fecha_vencimiento = request.form.get('fecha_vencimiento')

        factura = Factura(
            numero_factura=numero_factura,
            tipo_factura='Ordinaria',
            tipo_pestana=pestana,
            estado_ui=pestana,
            estado_contable='Emitida' if pestana != 'Borrador' else 'Borrador',
            contacto_id=cliente.id,
            referencia=request.form.get('referencia', '').strip(),
            fecha_factura=datetime.strptime(fecha_factura, '%Y-%m-%d').date() if fecha_factura else date.today(),
            fecha_vencimiento=datetime.strptime(fecha_vencimiento, '%Y-%m-%d').date() if fecha_vencimiento else None,
            total_base_imponible=total_base,
            total_cuota_iva=total_iva,
            total_recargo_equivalencia=recargo_total,
            porcentaje_irpf=porcentaje_irpf,
            total_retencion_irpf=total_retencion_irpf,
            total_factura=total_factura,
            metodo_pago_id=selected_metodo_pago_id,
            lineas=instancias_lineas,
        )
        db.session.add(factura)
        db.session.flush()

        if pestana == 'Emitida':
            cert_pass = request.form.get('cert_password')
            if cert_pass:
                _intentar_envio_verifactu(factura.id, cert_pass)
            else:
                flash('Factura guardada localmente. Use "Enviar Verifactu" en la lista para reportar a la AEAT.', 'info')

        db.session.commit()
        return redirect(url_for('invoices.facturas'))

    # CAMBIO: Por defecto, al entrar en limpio sugerimos un número de borrador
    return render_template('factura_form.html', **ctx,
                           numero_factura=generate_draft_number(), lineas=[])


@invoices_bp.route('/<int:factura_id>/editar', methods=['GET', 'POST'])
def factura_editar(factura_id):
    factura = db.get_or_404(Factura, factura_id)

    if factura.verifactu_estado == 'Aceptado':
        flash('No se puede editar una factura ya enviada a la AEAT.', 'danger')
        return redirect(url_for('invoices.facturas'))

    ctx = _get_form_context()

    
    # Mapeo inicial para la carga en GET
    lineas_mapeadas_html = [
        {
            'concepto': l.concepto,
            'unidades': float(l.unidades),
            'precio': float(l.precio_unitario),
            'impuesto': l.impuesto_tipo,
            'descuento': float(l.descuento_porcentaje) if l.descuento_porcentaje else 0.0,
            'total': float(l.subtotal_linea),
            'informacion': l.informacion or '',
        }
        for l in factura.lineas  # type: ignore
    ]

    if request.method == 'POST':
        cliente_id = request.form.get('contacto_id')
        cliente_id = int(cliente_id) if cliente_id and cliente_id.isdigit() else None
        metodo_pago_id = request.form.get('metodo_pago_id')
        selected_metodo_pago_id = int(metodo_pago_id) if metodo_pago_id and metodo_pago_id.isdigit() else None
        pestana = 'Borrador' if request.form.get('guardar_borrador') else 'Emitida'

        lineas_en_pantalla = InvoiceService.reconstruir_lineas_pantalla(request.form)

        cliente = db.session.get(Contacto, cliente_id) if cliente_id else None
        if not cliente:
            flash('Debe seleccionar un cliente válido.', 'danger')
            return render_template('factura_form.html', **ctx, edit_mode=True,
                                   factura=factura,
                                   lineas=lineas_en_pantalla,  # <-- CAMBIADO: Usamos los datos actuales
                                   selected_contacto_id=factura.contacto_id,
                                   selected_metodo_pago_id=selected_metodo_pago_id)

        # --- GESTIÓN AUTOMÁTICA DE NUMERACIÓN OFICIAL ---
        numero_factura = request.form.get('numero_factura', '').strip()

        # Guardamos el estado previo para saber si cambia de Borrador a Emitida
        era_borrador = factura.estado_ui == 'Borrador'

        # CORRECCIÓN: Comprobamos si empieza por el prefijo correcto 'BORR' o 'B-' de rectificativas provisionales
        if not numero_factura or numero_factura.startswith('BORR') or numero_factura.startswith('B-'):
            if pestana == 'Emitida':
                if factura.tipo_factura == 'Rectificativa':
                    from utils.sequence_generators import generate_rectificative_number
                    numero_factura = generate_rectificative_number()
                else:
                    numero_factura = generate_invoice_number()
            else:
                # Si se mantiene en borrador, conservamos el número que ya tenía asignado el borrador
                numero_factura = factura.numero_factura or numero_factura

        if Factura.query.filter(Factura.numero_factura == numero_factura, Factura.id != factura.id).first():
            flash('Ya existe una factura con ese número.', 'danger')
            return render_template('factura_form.html', **ctx, edit_mode=True,
                                   factura=factura,
                                   lineas=lineas_en_pantalla,  # <-- CAMBIADO: Usamos los datos actuales
                                   selected_contacto_id=factura.contacto_id,
                                   selected_metodo_pago_id=selected_metodo_pago_id)

        instancias_lineas, total_base, total_iva, error = InvoiceService.procesar_lineas_form(
            request.form, cliente, pestana, tipo_factura=factura.tipo_factura
        )
        if error:
            flash(error, 'danger')
            return render_template('factura_form.html', **ctx, edit_mode=True,
                                   factura=factura,
                                   lineas=lineas_en_pantalla,  # <-- CAMBIADO: Usamos los datos actuales
                                   selected_contacto_id=factura.contacto_id,
                                   selected_metodo_pago_id=selected_metodo_pago_id)

        porcentaje_irpf = Decimal(request.form.get('porcentaje_irpf', '0')).quantize(Decimal('0.01'))
        recargo_total, total_retencion_irpf, total_factura = _calcular_totales(cliente, pestana, total_base, total_iva, porcentaje_irpf)


        fecha_factura = request.form.get('fecha_factura')
        fecha_vencimiento = request.form.get('fecha_vencimiento')

        factura.lineas.clear()
        for linea in instancias_lineas:
            factura.lineas.append(linea)

        factura.numero_factura = numero_factura
        factura.tipo_pestana = pestana
        factura.estado_ui = pestana

        # Ajuste de estado contable consecuente
        factura.estado_contable = 'Emitida' if pestana != 'Borrador' else 'Borrador'

        factura.contacto_id = cliente.id
        factura.referencia = request.form.get('referencia', '').strip()

        # LÓGICA DE CONTROL TEMPORAL: Si era borrador y se emite ahora, la fecha de expedición legal es HOY
        if era_borrador and pestana == 'Emitida':
            factura.fecha_factura = date.today()
        else:
            factura.fecha_factura = datetime.strptime(fecha_factura, '%Y-%m-%d').date() if fecha_factura else date.today()

        factura.fecha_vencimiento = datetime.strptime(fecha_vencimiento, '%Y-%m-%d').date() if fecha_vencimiento else None
        factura.total_base_imponible = total_base
        factura.total_cuota_iva = total_iva
        factura.total_recargo_equivalencia = recargo_total
        factura.porcentaje_irpf = porcentaje_irpf
        factura.total_retencion_irpf = total_retencion_irpf
        factura.total_factura = total_factura
        factura.metodo_pago_id = selected_metodo_pago_id

        db.session.flush()

        if pestana == 'Emitida':
            cert_pass = request.form.get('cert_password')
            if cert_pass:
                _intentar_envio_verifactu(factura.id, cert_pass, flash_exito=False)

        db.session.commit()
        flash('Factura actualizada con éxito.', 'success')
        return redirect(url_for('invoices.facturas'))

    # GET — generamos QR si la factura ya fue aceptada por la AEAT
    qr_base64 = InvoiceService.generar_qr_verifactu(factura, ctx.get('configuracion'))

    return render_template(
        'factura_form.html',
        **ctx,
        factura=factura,
        numero_factura=factura.numero_factura,
        referencia=factura.referencia,
        fecha_factura=factura.fecha_factura.isoformat() if factura.fecha_factura else '',
        fecha_vencimiento=factura.fecha_vencimiento.isoformat() if factura.fecha_vencimiento else '',
        selected_contacto_id=factura.contacto_id,
        selected_metodo_pago_id=factura.metodo_pago_id,
        lineas=lineas_mapeadas_html,
        qr_base64=qr_base64,
        edit_mode=True,
    )


@invoices_bp.route('/<int:factura_id>/enviar_verifactu', methods=['POST'])
def factura_enviar_verifactu(factura_id):
    cert_pass = request.form.get('cert_password')
    if not cert_pass:
        return jsonify({'message': 'Contraseña del certificado requerida'}), 400

    config = Configuracion.query.first()
    if not config or not config.ruta_certificado:
        return jsonify({'message': 'Certificado no configurado en el sistema'}), 400

    ruta_cert = os.path.join(current_app.root_path, config.ruta_certificado)
    try:
        exito, mensaje = VerifactuOrchestrator.emitir_y_enviar_factura(factura_id, ruta_cert, cert_pass)
        if exito:
            return jsonify({'message': mensaje})
        return jsonify({'message': mensaje}), 500
    except Exception as e:
        return jsonify({'message': f'Error crítico: {str(e)}'}), 500


@invoices_bp.route('/<int:factura_id>/duplicar', methods=['POST'])
def factura_duplicar(factura_id):
    original = db.get_or_404(Factura, factura_id)

    nuevas_lineas = [
        FacturaLinea(
            concepto=l.concepto,
            informacion=l.informacion,
            unidades=l.unidades,
            precio_unitario=l.precio_unitario,
            descuento_porcentaje=l.descuento_porcentaje,
            impuesto_tipo=l.impuesto_tipo,
            porcentaje_iva=l.porcentaje_iva,
            porcentaje_recargo=l.porcentaje_recargo,
            subtotal_linea=l.subtotal_linea,
        )
        for l in original.lineas  # type: ignore
    ]

    # 1. Generamos el número correlativo real utilizando tu función oficial
    numero_oficial = generate_invoice_number()

    nueva = Factura(
        numero_factura=numero_oficial,
        tipo_pestana='Borrador',
        estado_ui='Borrador',
        estado_contable='Borrador',
        contacto_id=original.contacto_id,
        referencia=original.referencia,
        fecha_factura=date.today(),
        fecha_vencimiento=original.fecha_vencimiento,
        total_base_imponible=original.total_base_imponible,
        total_cuota_iva=original.total_cuota_iva,
        total_recargo_equivalencia=original.total_recargo_equivalencia,
        porcentaje_irpf=original.porcentaje_irpf,
        total_retencion_irpf=original.total_retencion_irpf,
        total_factura=original.total_factura,
        metodo_pago_id=original.metodo_pago_id,
        lineas=nuevas_lineas,
    )

    try:
        db.session.add(nueva)
        db.session.commit()
        return jsonify({'new_id': nueva.id, 'new_numero': nueva.numero_factura})
        
    except Exception as e:
        db.session.rollback()
        
        # 2. Si vuelve a fallar por UNIQUE, significa que generate_invoice_number() 
        # leyó el contador en caché. Forzamos una nueva lectura limpia.
        db.session.expire_all() 
        nueva.numero_factura = generate_invoice_number()
        
        try:
            db.session.add(nueva)
            db.session.commit()
            return jsonify({'new_id': nueva.id, 'new_numero': nueva.numero_factura})
        except Exception as e_final:
            db.session.rollback()
            return jsonify({'error': f'Error de duplicidad persistente: {str(e_final)}'}), 500


@invoices_bp.route('/<int:factura_id>/cobrar', methods=['POST'])
def factura_cobrar(factura_id):
    factura = db.get_or_404(Factura, factura_id)
    factura.estado_contable = 'Cobrada'
    db.session.commit()
    return jsonify({'status': 'ok', 'estado_pago': factura.estado_contable})


@invoices_bp.route('/<int:id>/descargar')
def factura_descargar(id):
    # 1. Carga de datos
    factura = db.session.get(Factura, id, options=[joinedload(Factura.lineas)]) # type: ignore
    if not factura:
        abort(404)

    config = db.session.scalars(select(Configuracion)).first()
    cliente = db.session.get(Contacto, factura.contacto_id)
    
    # Obtener Logo
    logo_base64 = _get_logo_base64_shared(config)

    # Obtener Metodo de Pago
    metodo_pago = None
    if hasattr(factura, 'metodo_pago_id') and factura.metodo_pago_id:
        metodo_pago = db.session.get(MetodoPago, factura.metodo_pago_id)
    elif hasattr(factura, 'metodo_pago') and factura.metodo_pago:
        metodo_pago = factura.metodo_pago

    # 2. Preparación de datos limpios mediante el Servicio
    # Ya no construimos HTML aquí, solo pasamos la lista de objetos o diccionarios
    if factura.lineas:
        lineas_pdf, texto_iva = InvoiceService.preparar_lineas_para_pdf(factura.lineas) if factura.lineas else []
    else:
        lineas_pdf, texto_iva = [], "Impuestos"

    # 3. Generación de QR (Logica de negocio, se mantiene)
    qr_base64 = InvoiceService.generar_qr_verifactu(factura, config)

    # Forzar el formato a Decimal('0.00') SOLO si el campo en la base de datos vino como None 
    # (Evitamos mutar directamente el objeto de la sesión de SQLAlchemy)
    porcentaje_irpf_seguro = factura.porcentaje_irpf if factura.porcentaje_irpf is not None else Decimal('0.00')
    total_retencion_seguro = factura.total_retencion_irpf if factura.total_retencion_irpf is not None else Decimal('0.00')

    # 4. Contexto para el template
    context = {
        'factura': factura,
        'config': config,
        'cliente': cliente,
        'logo_base64': logo_base64,
        'metodo_pago': metodo_pago,
        'lineas': lineas_pdf,  # <--- Pasamos la lista limpia
        'texto_iva_totales': texto_iva,
        'qr_base64': qr_base64,
    }
    # Inyectamos de forma segura los valores corregidos por si en base de datos eran NULL/None
    context['factura'].porcentaje_irpf = porcentaje_irpf_seguro
    context['factura'].total_retencion_irpf = total_retencion_seguro

    # 5. Generación del PDF
    pdf_bytes = PDFGenerator.render_to_pdf('pdf_templates/invoice_pdf.html', context)

    response = make_response(pdf_bytes)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=Factura_{factura.numero_factura}.pdf'
    return response


@invoices_bp.route('/previsualizar', methods=['POST'])
def factura_previsualizar():
    cliente_id = request.form.get('contacto_id')
    cliente = db.session.get(Contacto, int(cliente_id)) if cliente_id and cliente_id.isdigit() else None
    metodo_pago_id = request.form.get('metodo_pago_id')
    metodo_pago = db.session.get(MetodoPago, int(metodo_pago_id)) if metodo_pago_id and metodo_pago_id.isdigit() else None
    config = Configuracion.query.first()

    if not cliente:
        return 'Seleccione un cliente primero', 400

    # 1. Obtenemos las instancias de linea calculadas por el servicio
    lineas, total_base, total_iva, error = InvoiceService.procesar_lineas_form(request.form, cliente, 'Borrador')
    
    if error:
        return error, 400
    
    # NUEVO: Capturar el porcentaje de IRPF del formulario y calcular usando el helper oficial
    porcentaje_irpf = Decimal(request.form.get('porcentaje_irpf', '0')).quantize(Decimal('0.01'))
    recargo_total, total_retencion_irpf, total_factura = _calcular_totales(
        cliente, 'Borrador', total_base, total_iva, porcentaje_irpf
    )

    # 2. Obtenemos el logo
    logo_base64 = _get_logo_base64_shared(config)

    # 3. Objeto simulado para el template
    f_emision = request.form.get('fecha_factura')
    class FacturaSimulada:
        def __init__(self):
            self.numero_factura = request.form.get('numero_factura') or "BORRADOR"
            self.tipo_factura = request.form.get('tipo_factura', 'Ordinaria')
            self.fecha_factura = datetime.strptime(f_emision, '%Y-%m-%d').date() if f_emision else date.today()
            self.total_base_imponible = total_base
            self.total_cuota_iva = total_iva
            self.total_recargo_equivalencia = recargo_total
            self.porcentaje_irpf = porcentaje_irpf
            self.total_retencion_irpf = total_retencion_irpf
            self.total_factura = total_factura

    f_sim = FacturaSimulada()
    
    # 4. Desempaquetar la tupla (lista, string) que devuelve el servicio
    lineas_datos, texto_iva = InvoiceService.preparar_lineas_para_pdf(lineas)

    # 5. Renderizado enviando las variables limpias al template
    context = {
        'factura': f_sim,
        'config': config,
        'cliente': cliente,
        'metodo_pago': metodo_pago,
        'lineas': lineas_datos,
        'texto_iva_totales': texto_iva,
        'logo_base64': logo_base64,
        'qr_base64': "", 
        'es_previsualizacion': True
    }

    # generador unificado sin usar io ni pisa aquí
    pdf_bytes = PDFGenerator.render_to_pdf('pdf_templates/invoice_pdf.html', context)
    
    response = make_response(pdf_bytes)
    response.headers['Content-Type'] = 'application/pdf'
    return response

@invoices_bp.route('/<int:factura_id>/eliminar', methods=['POST'])
def factura_eliminar(factura_id):
    factura = db.get_or_404(Factura, factura_id)
    db.session.delete(factura)
    db.session.commit()
    return jsonify({'status': 'ok'})

@invoices_bp.route('/<int:factura_id>/rectificar', methods=['POST'])
def factura_rectificar(factura_id):
    """Genera un borrador en negativo de una factura emitida para subsanación o abono."""
    original = db.get_or_404(Factura, factura_id)
    
    if original.estado_ui == 'Borrador':
        return jsonify({'error': 'No se puede rectificar un borrador.'}), 400

    motivo = request.form.get('motivo_rectificacion', 'Error material / Subsanación de datos').strip()
    
    try:
        # Duplicar las líneas invirtiendo el signo de las unidades y el subtotal
        nuevas_lineas = [
            FacturaLinea(
                producto_id=l.producto_id,
                concepto=f"Rectificación {original.numero_factura}: {l.concepto}",
                unidades=l.unidades * Decimal('-1'),
                precio_unitario=l.precio_unitario,
                descuento_porcentaje=l.descuento_porcentaje,
                impuesto_tipo=l.impuesto_tipo,
                porcentaje_iva=l.porcentaje_iva,
                porcentaje_recargo=l.porcentaje_recargo,
                subtotal_linea=l.subtotal_linea * Decimal('-1')
            )
            for l in original.lineas # type: ignore
        ]

        # Generamos un identificador temporal para que el borrador no colisione numéricamente
        stmt = select(func.count(Factura.id)).filter_by(estado_ui='Borrador')
        conteo_borradores = (db.session.scalar(stmt) or 0) + 1
        # año con dos últimas cifras 
        anio_corto = str(date.today().year)[2:]
        num_provisional = f"B-R{anio_corto}-{conteo_borradores:03d}"

        rectificativa = Factura(
            numero_factura=num_provisional,
            tipo_factura='Rectificativa',
            tipo_pestana='Borrador',
            estado_ui='Borrador',
            estado_contable='Borrador',
            contacto_id=original.contacto_id,
            metodo_pago_id=original.metodo_pago_id,
            referencia=f"Abono de {original.numero_factura}",
            referencia_presupuesto=original.referencia_presupuesto,
            fecha_factura=date.today(),
            fecha_vencimiento=date.today(),
            
            # Totales en negativo
            total_base_imponible=original.total_base_imponible * Decimal('-1'),
            total_cuota_iva=original.total_cuota_iva * Decimal('-1'),
            total_recargo_equivalencia=original.total_recargo_equivalencia * Decimal('-1'),
            total_factura=original.total_factura * Decimal('-1'),
            
            # Enlaces de auditoría para Veri*Factu
            factura_rectificada_id=original.id,
            motivo_rectificacion=motivo,
            lineas=nuevas_lineas
        )

        db.session.add(rectificativa)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'new_id': rectificativa.id
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'No se pudo generar la rectificativa: {str(e)}'}), 500