import base64
from datetime import datetime, date
from decimal import Decimal
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, make_response, abort, current_app
from sqlalchemy.orm import joinedload
from sqlalchemy import select, func
from models import db, Contacto, Factura, FacturaLinea, Producto, MetodoPago, Configuracion, FacturaVerifactu
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
        query = query.filter(
            Factura.tipo_factura == 'Ordinaria',
            Factura.estado_contable != 'Borrador'
        )
    elif pestana == 'Rectificativa':
        query = query.filter(
            Factura.tipo_factura == 'Rectificativa',
            Factura.estado_contable != 'Borrador'
        )
    elif pestana == 'Borrador':
        query = query.filter(Factura.estado_contable == 'Borrador')
        
    elif pestana == 'Verifactu':
        # Filtramos por todas las facturas que tengan un registro de envío en Verifactu
        # y cuyo estado sea Aceptado, Rechazado o Error, asegurando que no se pierda nada.
        query = query.join(FacturaVerifactu).filter(
            FacturaVerifactu.estado_envio.in_(['Enviado_Aceptado', 'Rechazado', 'Error'])
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
        .options(joinedload(Factura.verifactu_registro))  # type: ignore[arg-type]
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
        es_borrador = bool(request.form.get('guardar_borrador'))
        pestana = 'Borrador' if es_borrador else 'Emitida'

        cliente = db.session.get(Contacto, cliente_id) if cliente_id else None
            
        if not cliente:
            num_error = request.form.get('numero_factura', '').strip()
            if not num_error:
                num_error = generate_draft_number() if es_borrador else generate_invoice_number()

            flash('Debe seleccionar un cliente válido.', 'danger')
            return render_template('factura_form.html', **ctx,
                                   numero_factura=num_error,
                                   lineas=InvoiceService.reconstruir_lineas_pantalla(request.form),
                                   selected_contacto_id=cliente_id,
                                   selected_metodo_pago_id=selected_metodo_pago_id)

        form_num = request.form.get('numero_factura', '').strip()
        if not form_num or form_num.startswith('BORR'):
            numero_factura = generate_draft_number() if es_borrador else generate_invoice_number()
        else:
            numero_factura = form_num

        if Factura.query.filter_by(numero_factura=numero_factura).first():
            flash('Ya existe una factura con ese número.', 'danger')
            return render_template('factura_form.html', **ctx,
                                   numero_factura=numero_factura, 
                                   lineas=InvoiceService.reconstruir_lineas_pantalla(request.form),
                                   selected_contacto_id=cliente_id,
                                   selected_metodo_pago_id=selected_metodo_pago_id)

        # 1. Invocamos al servicio capturando el diccionario de totales unificado
        instancias_lineas, totales, error = InvoiceService.procesar_lineas_form(
            request.form, cliente, pestana, tipo_factura='Ordinaria'
        )
        if error:
            flash(error, 'danger')
            return render_template('factura_form.html', **ctx,
                                   numero_factura=numero_factura, 
                                   lineas=InvoiceService.reconstruir_lineas_pantalla(request.form),
                                   selected_contacto_id=cliente_id,
                                   selected_metodo_pago_id=selected_metodo_pago_id)
        
        # 2. Capturamos e inyectamos la retención de IRPF al cálculo matemático de la factura
        porcentaje_irpf = Decimal(request.form.get('porcentaje_irpf', '0')).quantize(Decimal('0.01'))
        
        # Recalculamos totales globales aplicando el IRPF
        from utils.tax_calculations import calculate_invoice_totals
        lineas_para_totales = [
            {
                'cantidad': l.unidades,
                'precio_unitario': l.precio_unitario,
                'descuento': l.descuento_porcentaje,
                'iva_porcentaje': l.porcentaje_iva
            } for l in instancias_lineas
        ]
        totales = calculate_invoice_totals(
            lineas=lineas_para_totales,
            recargo=cliente.recargo_equivalencia,
            porcentaje_retencion=porcentaje_irpf
        )

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
            total_base_imponible=totales['base_imponible'],
            total_cuota_iva=totales['iva_total'],
            total_recargo_equivalencia=totales['recargo_total'],
            porcentaje_irpf=porcentaje_irpf,
            total_retencion_irpf=totales['retencion_total'],
            total_factura=totales['total'],
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

    return render_template('factura_form.html', **ctx,
                           numero_factura=generate_draft_number(), lineas=[])


@invoices_bp.route('/<int:factura_id>/editar', methods=['GET', 'POST'])
def factura_editar(factura_id):
    factura = db.get_or_404(Factura, factura_id)

    if factura.verifactu_estado == 'Aceptado':
        flash('No se puede editar una factura ya enviada a la AEAT.', 'danger')
        return redirect(url_for('invoices.facturas'))

    ctx = _get_form_context()

    # Corrección de tipo para iterar de manera segura las relaciones mapeadas
    lineas_relacion: list[FacturaLinea] = factura.lineas  # type: ignore[assignment]
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
        for l in lineas_relacion
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
                                   lineas=lineas_en_pantalla,
                                   selected_contacto_id=factura.contacto_id,
                                   selected_metodo_pago_id=selected_metodo_pago_id)

        numero_factura = request.form.get('numero_factura', '').strip()
        era_borrador = factura.estado_ui == 'Borrador'

        if not numero_factura or numero_factura.startswith('BORR') or numero_factura.startswith('B-'):
            if pestana == 'Emitida':
                if factura.tipo_factura == 'Rectificativa':
                    from utils.sequence_generators import generate_rectificative_number
                    numero_factura = generate_rectificative_number()
                else:
                    numero_factura = generate_invoice_number()
            else:
                numero_factura = factura.numero_factura or numero_factura

        if Factura.query.filter(Factura.numero_factura == numero_factura, Factura.id != factura.id).first():
            flash('Ya existe una factura con ese número.', 'danger')
            return render_template('factura_form.html', **ctx, edit_mode=True,
                                   factura=factura,
                                   lineas=lineas_en_pantalla,
                                   selected_contacto_id=factura.contacto_id,
                                   selected_metodo_pago_id=selected_metodo_pago_id)

        # 1. Invocamos al servicio y recalculamos usando el motor unificado de cálculo
        instancias_lineas, totales, error = InvoiceService.procesar_lineas_form(
            request.form, cliente, pestana, tipo_factura=factura.tipo_factura
        )
        if error:
            flash(error, 'danger')
            return render_template('factura_form.html', **ctx, edit_mode=True,
                                   factura=factura,
                                   lineas=lineas_en_pantalla,
                                   selected_contacto_id=factura.contacto_id,
                                   selected_metodo_pago_id=selected_metodo_pago_id)

        porcentaje_irpf = Decimal(request.form.get('porcentaje_irpf', '0')).quantize(Decimal('0.01'))
        
        from utils.tax_calculations import calculate_invoice_totals
        lineas_para_totales = [
            {
                'cantidad': l.unidades,
                'precio_unitario': l.precio_unitario,
                'descuento': l.descuento_porcentaje,
                'iva_porcentaje': l.porcentaje_iva
            } for l in instancias_lineas
        ]
        totales = calculate_invoice_totals(
            lineas=lineas_para_totales,
            recargo=cliente.recargo_equivalencia,
            porcentaje_retencion=porcentaje_irpf
        )

        fecha_factura = request.form.get('fecha_factura')
        fecha_vencimiento = request.form.get('fecha_vencimiento')

        factura.lineas.clear()
        for linea in instancias_lineas:
            factura.lineas.append(linea)

        factura.numero_factura = numero_factura
        factura.tipo_pestana = pestana
        factura.estado_ui = pestana
        factura.estado_contable = 'Emitida' if pestana != 'Borrador' else 'Borrador'
        factura.contacto_id = cliente.id
        factura.referencia = request.form.get('referencia', '').strip()

        if era_borrador and pestana == 'Emitida':
            factura.fecha_factura = date.today()
        else:
            factura.fecha_factura = datetime.strptime(fecha_factura, '%Y-%m-%d').date() if fecha_factura else date.today()

        factura.fecha_vencimiento = datetime.strptime(fecha_vencimiento, '%Y-%m-%d').date() if fecha_vencimiento else None
        
        # Guardamos en base de datos con los resultados exactos del motor Decimal
        factura.total_base_imponible = totales['base_imponible']
        factura.total_cuota_iva = totales['iva_total']
        factura.total_recargo_equivalencia = totales['recargo_total']
        factura.porcentaje_irpf = porcentaje_irpf
        factura.total_retencion_irpf = totales['retencion_total']
        factura.total_factura = totales['total']
        factura.metodo_pago_id = selected_metodo_pago_id

        db.session.flush()

        if pestana == 'Emitida':
            cert_pass = request.form.get('cert_password')
            if cert_pass:
                _intentar_envio_verifactu(factura.id, cert_pass, flash_exito=False)

        db.session.commit()
        flash('Factura actualizada con éxito.', 'success')
        return redirect(url_for('invoices.facturas'))

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

    lineas_relacion: list[FacturaLinea] = original.lineas  # type: ignore[assignment]
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
        for l in lineas_relacion
    ]

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
    # Corregido: 'joinedload' estático apuntando directamente a Factura.lineas para evitar quejas de Pylance
    factura = db.session.get(Factura, id, options=[joinedload(Factura.lineas)])  # type: ignore[arg-type]
    if not factura:
        abort(404)

    config = db.session.scalars(select(Configuracion)).first()
    cliente = db.session.get(Contacto, factura.contacto_id)
    logo_base64 = _get_logo_base64_shared(config)

    metodo_pago = None
    if hasattr(factura, 'metodo_pago_id') and factura.metodo_pago_id:
        metodo_pago = db.session.get(MetodoPago, factura.metodo_pago_id)
    elif hasattr(factura, 'metodo_pago') and factura.metodo_pago:
        metodo_pago = factura.metodo_pago

    lineas_relacion: list[FacturaLinea] = factura.lineas  # type: ignore[assignment]
    if lineas_relacion:
        lineas_pdf, texto_iva = InvoiceService.preparar_lineas_para_pdf(lineas_relacion)
    else:
        lineas_pdf, texto_iva = [], "Impuestos"

    # NORMALIZACIÓN A DECIMAL PARA EVITAR TYPEERRORS EN JINJA2
    for item in lineas_pdf:
        for campo in ['precio', 'total', 'cuota_iva']:
            val = item.get(campo)
            if val is not None:
                if isinstance(val, str):
                    item[campo] = Decimal(val)
                elif isinstance(val, (int, float)):
                    item[campo] = Decimal(str(val))

    qr_base64 = InvoiceService.generar_qr_verifactu(factura, config)

    porcentaje_irpf_seguro = factura.porcentaje_irpf if factura.porcentaje_irpf is not None else Decimal('0.00')
    total_retencion_seguro = factura.total_retencion_irpf if factura.total_retencion_irpf is not None else Decimal('0.00')

    context = {
        'factura': factura,
        'config': config,
        'cliente': cliente,
        'logo_base64': logo_base64,
        'metodo_pago': metodo_pago,
        'lineas': lineas_pdf,
        'texto_iva_totales': texto_iva,
        'qr_base64': qr_base64,
    }
    context['factura'].porcentaje_irpf = porcentaje_irpf_seguro
    context['factura'].total_retencion_irpf = total_retencion_seguro

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

    # 1. Invocamos al servicio de líneas
    lineas, totales, error = InvoiceService.procesar_lineas_form(request.form, cliente, 'Borrador')
    if error:
        return error, 400
    
    # 2. Recalculamos usando el motor unificado inyectando el IRPF
    porcentaje_irpf = Decimal(request.form.get('porcentaje_irpf', '0')).quantize(Decimal('0.01'))
    
    from utils.tax_calculations import calculate_invoice_totals
    lineas_para_totales = [
        {
            'cantidad': l.unidades,
            'precio_unitario': l.precio_unitario,
            'descuento': l.descuento_porcentaje,
            'iva_porcentaje': l.porcentaje_iva
        } for l in lineas
    ]
    totales = calculate_invoice_totals(
        lineas=lineas_para_totales,
        recargo=cliente.recargo_equivalencia,
        porcentaje_retencion=porcentaje_irpf
    )

    logo_base64 = _get_logo_base64_shared(config)

    f_emision = request.form.get('fecha_factura')
    class FacturaSimulada:
        def __init__(self):
            self.numero_factura = request.form.get('numero_factura') or "BORRADOR"
            self.tipo_factura = request.form.get('tipo_factura', 'Ordinaria')
            self.fecha_factura = datetime.strptime(f_emision, '%Y-%m-%d').date() if f_emision else date.today()
            self.total_base_imponible = totales['base_imponible']
            self.total_cuota_iva = totales['iva_total']
            self.total_recargo_equivalencia = totales['recargo_total']
            self.porcentaje_irpf = porcentaje_irpf
            self.total_retencion_irpf = totales['retencion_total']
            self.total_factura = totales['total']

    f_sim = FacturaSimulada()
    
    lineas_datos, texto_iva = InvoiceService.preparar_lineas_para_pdf(lineas)
    # Asegurar que los valores numéricos de las líneas para el PDF mantengan precisión Decimal
    for item in lineas_datos:
        # Normalizar precio
        precio_val = item.get('precio')
        if isinstance(precio_val, str):
            item['precio'] = Decimal(precio_val)
        elif isinstance(precio_val, (int, float)):
            item['precio'] = Decimal(str(precio_val))

        # Normalizar total de línea
        total_val = item.get('total')
        if isinstance(total_val, str):
            item['total'] = Decimal(total_val)
        elif isinstance(total_val, (int, float)):
            item['total'] = Decimal(str(total_val))

        # Normalizar cuota_iva (¡Aquí estaba el error!)
        cuota_iva_val = item.get('cuota_iva')
        if isinstance(cuota_iva_val, str):
            item['cuota_iva'] = Decimal(cuota_iva_val)
        elif isinstance(cuota_iva_val, (int, float)):
            item['cuota_iva'] = Decimal(str(cuota_iva_val))

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

    pdf_bytes = PDFGenerator.render_to_pdf('pdf_templates/invoice_pdf.html', context)
    
    # Validamos que pdf_bytes sea de tipo bytes y no None para satisfacer a Pylance
    if not pdf_bytes:
        return jsonify({
            'success': False,
            'message': 'No se pudo generar el documento PDF.'
        }), 500

    # Codificamos el PDF en Base64 de forma segura
    pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')
    
    # Obtenemos datos para el nombre del archivo de forma segura usando las variables validadas
    numero_factura = f_sim.numero_factura
    nombre_cliente = cliente.nombre_fiscal

    return jsonify({
        'success': True,
        'pdf_data': f"data:application/pdf;base64,{pdf_base64}",
        'numero_factura': numero_factura,
        'nombre_cliente': nombre_cliente
    })


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
        lineas_relacion: list[FacturaLinea] = original.lineas  # type: ignore[assignment]
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
            for l in lineas_relacion
        ]

        stmt = select(func.count(Factura.id)).filter_by(estado_ui='Borrador')
        conteo_borradores = (db.session.scalar(stmt) or 0) + 1
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
            
            total_base_imponible=original.total_base_imponible * Decimal('-1'),
            total_cuota_iva=original.total_cuota_iva * Decimal('-1'),
            total_recargo_equivalencia=original.total_recargo_equivalencia * Decimal('-1'),
            total_factura=original.total_factura * Decimal('-1'),
            
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