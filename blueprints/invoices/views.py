from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file
import io
from sqlalchemy.orm import joinedload
from models import db, Factura, Contacto, MetodoPago, FacturaVerifactu
import base64

# Importación de los nuevos servicios desacoplados[cite: 1]
from services.invoices.invoice_management_service import InvoiceManagementService
from services.invoices.invoice_form_service import InvoiceFormService
from services.invoices.invoice_pdf_service import InvoicePdfService
from services.invoices.invoice_submission_service import InvoiceSubmissionService

invoices_bp = Blueprint('invoices', __name__)

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
    if request.method == 'POST':
        factura, ctx_error, error = InvoiceFormService.procesar_guardado_factura(request.form)
        if error and ctx_error:
            flash(error, 'danger')
            # CORRECCIÓN: Nombre de plantilla correcto
            return render_template('factura_form.html', **ctx_error)
        
        db.session.commit()
        flash('Factura creada correctamente.', 'success')
        return redirect(url_for('invoices.factura_editar', id=factura.id) if factura else url_for('invoices.facturas'))

    # GET: Renderizar el formulario con el contexto limpio
    ctx = InvoiceFormService.get_form_context()
    # Generamos el número inicial reglamentario para que no aparezca vacío
    from utils.sequence_generators import generate_invoice_number
    numero_inicial = generate_invoice_number()
    # CORRECCIÓN: Nombre de plantilla correcto
    return render_template('factura_form.html', **ctx, numero_factura=numero_inicial, edit_mode=False)


@invoices_bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@invoices_bp.route('/editar/id/<int:factura_id>', methods=['GET', 'POST'])
def factura_editar(id=None, factura_id=None):
    # Usar el ID que venga de cualquiera de las dos firmas de ruta
    actual_id = id if id is not None else factura_id
    
    factura = db.session.get(Factura, actual_id)
    if not factura:
        flash('Factura no encontrada.', 'danger')
        return redirect(url_for('invoices.facturas'))

    if request.method == 'POST':
        _, ctx_error, error = InvoiceFormService.procesar_guardado_factura(request.form, factura_existente=factura)
        if error and ctx_error:
            flash(error, 'danger')
            return render_template('factura_form.html', **ctx_error)
            
        db.session.commit()
        flash('Factura actualizada correctamente.', 'success')
        return redirect(url_for('invoices.factura_editar', id=factura.id) if id is not None else url_for('invoices.factura_editar', factura_id=factura.id))

    # Reconstruimos las líneas de base de datos mapeadas a los campos editables de la interfaz
    lineas_pantalla = []
    for linea in factura.lineas: # type: ignore[attr-defined]
        lineas_pantalla.append({
            'concepto': linea.concepto,
            'informacion': linea.informacion or '',
            'unidades': float(linea.unidades),
            'precio': float(linea.precio_unitario),
            'impuesto': linea.impuesto_tipo,
            'descuento': float(linea.descuento_porcentaje),
            'total': float(linea.subtotal_linea)
        })

    ctx = InvoiceFormService.get_form_context()
    
    # Pasamos primero **ctx y después las variables fijas para asegurar que el objeto factura real y sus datos manden
    return render_template(
        'factura_form.html',
        **ctx,
        edit_mode=True,
        factura=factura,
        numero_factura=factura.numero_factura,
        lineas=lineas_pantalla,
        selected_contacto_id=factura.contacto_id,
        selected_metodo_pago_id=factura.metodo_pago_id
    )


@invoices_bp.route('/duplicar/<int:id>', methods=['POST'])
def factura_duplicar(id):
    resultado, error = InvoiceManagementService.duplicar_factura(id)
    if error:
        return jsonify({'status': 'error', 'message': error}), 400
    # Devolvemos estructura JSON limpia que el JS sabe leer
    return jsonify({'success': True, 'new_id': resultado['new_id'] if resultado else id})


@invoices_bp.route('/cobrar/<int:id>', methods=['POST'])
def factura_cobrar(id):
    resultado, error = InvoiceManagementService.cobrar_factura(id)
    if error:
        return jsonify({'status': 'error', 'message': error}), 404
    return jsonify(resultado)


@invoices_bp.route('/eliminar/<int:id>', methods=['POST'])
def factura_eliminar(id):
    _, error = InvoiceManagementService.eliminar_factura(id)
    if error:
        flash(error, 'danger')
    else:
        flash('Factura eliminada correctamente.', 'success')
    return redirect(url_for('invoices.facturas'))


@invoices_bp.route('/rectificar/<int:id>', methods=['POST'])
def factura_rectificar(id):
    motivo = request.form.get('motivo_rectificacion', '').strip()
    resultado, error = InvoiceManagementService.rectificar_factura(id, motivo)
    if error:
        return jsonify({'status': 'error', 'message': error}), 400
    # Devolvemos estructura JSON limpia que el JS sabe leer
    return jsonify({'success': True, 'new_id': resultado['new_id'] if resultado else id})


@invoices_bp.route('/descargar/<int:id>')
def descargar_pdf(id):
    factura = db.session.get(Factura, id)
    if not factura:
        flash('Factura no encontrada para generar PDF.', 'danger')
        return redirect(url_for('invoices.facturas'))

    pdf_bytes = InvoicePdfService.generar_pdf_factura(factura)
    if not pdf_bytes:
        flash('Error interno al renderizar el documento PDF.', 'danger')
        return redirect(url_for('invoices.factura_editar', id=id))

    nombre_archivo = f"{factura.numero_factura.replace('/', '_')}.pdf"
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=nombre_archivo
    )


@invoices_bp.route('/previsualizar', methods=['POST'])
def factura_previsualizar():
    cliente_id = request.form.get('contacto_id')
    cliente = db.session.get(Contacto, int(cliente_id)) if (cliente_id and cliente_id.isdigit()) else None
    if not cliente:
        return "Error: Debe seleccionar un cliente para previsualizar.", 400

    metodo_pago_id = request.form.get('metodo_pago_id')
    metodo_pago = db.session.get(MetodoPago, int(metodo_pago_id)) if (metodo_pago_id and metodo_pago_id.isdigit()) else None

    # Buscamos si ya existe una factura con este número para saltar la validación de duplicados
    numero_factura = request.form.get('numero_factura', '').strip()
    factura_existente = None
    if numero_factura:
        factura_existente = Factura.query.filter_by(numero_factura=numero_factura).first()

    factura_simulada, _, error = InvoiceFormService.procesar_guardado_factura(
        request.form, 
        factura_existente=factura_existente
    )
    
    if error or not factura_simulada:
        return f"Error de validación en simulación: {error}", 400

    # Lógica robusta para extraer las líneas sin romper la sesión de la base de datos
    try:
        lista_lineas_puras = list(factura_simulada.lineas)  # type: ignore[arg-type]
    except Exception:
        # Si SQLAlchemy protesta por las relaciones en caliente, usamos las líneas del objeto original
        lista_lineas_puras = list(factura_existente.lineas) if factura_existente else [] # type: ignore[attr-defined]

    pdf_bytes = InvoicePdfService.generar_pdf_previsualizacion(
        factura_simulada=factura_simulada,
        cliente=cliente,
        metodo_pago=metodo_pago,
        lineas=lista_lineas_puras
    )

    if not pdf_bytes:
        return "Error al generar la previsualización del PDF.", 500

    # 1. Transformamos los bytes del PDF en un string Base64 compatible con la URI de datos del navegador
    pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')
    pdf_data_uri = f"data:application/pdf;base64,{pdf_base64}"

    # 2. Obtenemos datos básicos para que el script pueda nombrar amigablemente el archivo al descargar
    numero_factura = factura_simulada.numero_factura or 'Borrador'
    nombre_cliente = cliente.nombre_fiscal if cliente else 'Cliente'

    # 3. Retornamos la estructura exacta de JSON que tu JavaScript espera consumir
    return {
        'success': True,
        'pdf_data': pdf_data_uri,
        'numero_factura': numero_factura,
        'nombre_cliente': nombre_cliente
    }

    return send_file(io.BytesIO(pdf_bytes), mimetype='application/pdf')


@invoices_bp.route('/enviar/<int:id>', methods=['POST'])
def factura_enviar(id):
    cert_pass = request.form.get('cert_password') or request.form.get('cert_pass')
    if not cert_pass:
        return jsonify({'success': False, 'message': 'Contraseña del certificado requerida.'}), 400

    resultado, error = InvoiceSubmissionService.enviar_factura_verifactu(id, cert_pass)
    if error:
        return jsonify({'success': False, 'message': error}), 400
        
    mensaje = resultado.get('message', 'Factura enviada a Verifactu correctamente.') if resultado else 'Enviado.'
    return jsonify({
        'success': True, 
        'message': mensaje
    })