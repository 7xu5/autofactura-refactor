# blueprints/delivery_notes/views.py
import json

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, make_response, abort
from models import db, Contacto, Albaran, MetodoPago, Configuracion, Producto, Factura, Presupuesto
from utils.sequence_generators import generate_delivery_note_number

from services.delivery_note_service import DeliveryNoteService
from utils.pdf_generator import PDFGenerator

delivery_notes_bp = Blueprint('delivery_notes', __name__, url_prefix='/albaranes')

@delivery_notes_bp.route('/')
def albaranes():
    estado = request.args.get('estado', 'Todos')
    query = Albaran.query
    if estado in ['Borrador', 'Emitido', 'Facturado', 'Anulado']:
        query = query.filter(Albaran.estado == estado)
    albaranes = query.order_by(Albaran.fecha_emision.desc()).all()
    return render_template('albaranes.html', albaranes=albaranes, estado=estado)


@delivery_notes_bp.route('/crear', methods=['GET', 'POST'])
def albaran_crear():
    contactos = Contacto.query.order_by(Contacto.nombre_fiscal).all()
    metodos_pago = MetodoPago.query.all()
    productos = Producto.query.order_by(Producto.nombre).all()

    # Consulta facturas y presupuestos para los selectores
    facturas = Factura.query.order_by(Factura.numero_factura.desc()).all()
    presupuestos = Presupuesto.query.order_by(Presupuesto.numero_presupuesto.desc()).all()
    
    productos_lista = [
        {
            'nombre': p.nombre,
            'precio': float(p.precio_unitario_base),
            'impuesto': p.impuesto_defecto,
            'descripcion_adicional': p.descripcion_adicional or ''
        } for p in productos
    ]
    productos_json = json.dumps(productos_lista)

    if request.method == 'POST':
        try:
            DeliveryNoteService.create_delivery_note(request.form)
            flash('Albarán creado con éxito', 'success')
            return redirect(url_for('delivery_notes.albaranes'))
        except ValueError as e:
            flash(str(e), 'danger')
            lineas_raw, _, _, _ = DeliveryNoteService.parse_form_lines(request.form)
            return render_template(
                'albaran_form.html', 
                contactos=contactos, 
                metodos_pago=metodos_pago, 
                lineas=lineas_raw,
                numero_albaran=request.form.get('numero_albaran') or generate_delivery_note_number(),
                productos_json=productos_json,
                facturas=facturas,
                presupuestos=presupuestos
            )

    return render_template(
        'albaran_form.html', 
        contactos=contactos, 
        metodos_pago=metodos_pago, 
        numero_albaran=generate_delivery_note_number(), 
        lineas=[], 
        productos_json=productos_json,
        facturas=facturas,
        presupuestos=presupuestos
    )


@delivery_notes_bp.route('/<int:albaran_id>/editar', methods=['GET', 'POST'])
def albaran_editar(albaran_id):
    albaran = Albaran.query.get_or_404(albaran_id)
    contactos = Contacto.query.order_by(Contacto.nombre_fiscal).all()
    metodos_pago = MetodoPago.query.all()
    productos = Producto.query.order_by(Producto.nombre).all()

    # Consulta facturas y presupuestos para los selectores
    facturas = Factura.query.order_by(Factura.numero_factura.desc()).all()
    presupuestos = Presupuesto.query.order_by(Presupuesto.numero_presupuesto.desc()).all()
    
    productos_lista = [
        {
            'nombre': p.nombre,
            'precio': float(p.precio_unitario_base),
            'impuesto': p.impuesto_defecto,
            'descripcion_adicional': p.descripcion_adicional or ''
        } for p in productos
    ]
    productos_json = json.dumps(productos_lista)

    if request.method == 'POST':
        try:
            # CORREGIDO PREVIAMENTE: Ahora llama a la función correcta de albaranes
            DeliveryNoteService.update_delivery_note(albaran, request.form)
            flash('Albarán actualizado con éxito', 'success')
            return redirect(url_for('delivery_notes.albaranes'))
        except ValueError as e:
            flash(str(e), 'danger')
            lineas_raw, _, _, _ = DeliveryNoteService.parse_form_lines(request.form)
            return render_template(
                'albaran_form.html',
                albaran=albaran, 
                contactos=contactos, 
                metodos_pago=metodos_pago, 
                lineas=lineas_raw, 
                selected_contacto_id=request.form.get('contacto_id'),
                facturas=facturas,
                presupuestos=presupuestos
            )

    return render_template(
        'albaran_form.html',
        albaran=albaran,
        contactos=contactos,
        metodos_pago=metodos_pago,
        numero_albaran=albaran.numero_albaran,
        fecha_emision=albaran.fecha_emision.isoformat(),
        fecha_entrega=albaran.fecha_entrega.isoformat() if albaran.fecha_entrega else '',
        referencia=albaran.referencia,
        referencia_presupuesto=albaran.referencia_presupuesto,
        estado=albaran.estado,
        notes=albaran.notas,
        lineas=albaran.lineas_json(),
        selected_contacto_id=albaran.contacto_id,
        selected_metodo_pago_id=albaran.metodo_pago_id,
        productos_json=productos_json,
        facturas=facturas,
        presupuestos=presupuestos
    )


@delivery_notes_bp.route('/<int:id>/descargar')
def albaran_descargar(id):
    albaran = db.session.get(Albaran, id)
    if not albaran:
        abort(404)

    config = Configuracion.query.first()
    cliente = db.session.get(Contacto, albaran.contacto_id)
    metodo_pago = db.session.get(MetodoPago, albaran.metodo_pago_id) if albaran.metodo_pago_id else None

    logo_base64 = PDFGenerator.get_logo_base64(config.logo_path if config else "")
    lineas_html = PDFGenerator.build_lines_html(albaran.lineas_json())

    context = {
        'albaran': albaran,
        'config': config,
        'cliente': cliente,
        'logo_base64': logo_base64,
        'metodo_pago': metodo_pago,
        'lineas_html': lineas_html
    }

    # Apunta correctamente a tu renderizador de PDFs
    pdf_bytes = PDFGenerator.render_to_pdf('pdf_templates/albaran_pdf.html', context)
    
    response = make_response(pdf_bytes)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=Albaran_{albaran.numero_albaran}.pdf'
    return response


# --- RUTAS DE ESTADO RÁPIDAS ---
@delivery_notes_bp.route('/<int:albaran_id>/emitir', methods=['POST'])
def albaran_emitir(albaran_id):
    albaran = Albaran.query.get_or_404(albaran_id)
    albaran.estado = 'Emitido'
    db.session.commit()
    flash('Albarán marcado como emitido', 'success')
    return redirect(url_for('delivery_notes.albaranes'))

@delivery_notes_bp.route('/<int:albaran_id>/anular', methods=['POST'])
def albaran_anular(albaran_id):
    albaran = Albaran.query.get_or_404(albaran_id)
    albaran.estado = 'Anulado'
    db.session.commit()
    flash('Albarán marcado como anulado', 'success')
    return redirect(url_for('delivery_notes.albaranes'))

@delivery_notes_bp.route('/<int:albaran_id>/eliminar', methods=['POST'])
def albaran_eliminar(albaran_id):
    albaran = Albaran.query.get_or_404(albaran_id)
    db.session.delete(albaran)
    db.session.commit()
    return jsonify({'status': 'ok'})

@delivery_notes_bp.route('/api/lineas-factura/<path:numero_factura>')
def api_lineas_factura(numero_factura):
    factura = Factura.query.filter_by(numero_factura=numero_factura).first()
    if not factura:
        return jsonify({'error': 'Factura no encontrada'}), 404
        
    # Usamos el método lineas_json() que ya tienes estandarizado
    return jsonify({'lineas': factura.lineas_json()})


@delivery_notes_bp.route('/api/lineas-presupuesto/<path:numero_presupuesto>')
def api_lineas_presupuesto(numero_presupuesto):
    presupuesto = Presupuesto.query.filter_by(numero_presupuesto=numero_presupuesto).first()
    if not presupuesto:
        return jsonify({'error': 'Presupuesto no encontrado'}), 404
        
    return jsonify({'lineas': presupuesto.lineas_json()})

from datetime import datetime

@delivery_notes_bp.route('/preview', methods=['POST'])
def albaran_preview():
    contacto_id = request.form.get('contacto_id')
    metodo_pago_id = request.form.get('metodo_pago_id')
    
    config = Configuracion.query.first()
    cliente = db.session.get(Contacto, contacto_id) if contacto_id else None
    metodo_pago = db.session.get(MetodoPago, metodo_pago_id) if metodo_pago_id else None
    
    # 1. Extraer los datos en formato diccionario plano (lo que espera build_lines_html)
    lineas_dict = []
    try:
        total_lines = int(request.form.get('lineas_count', 5))
    except ValueError:
        total_lines = 5

    total_base = 0.0
    total_imp = 0.0

    for i in range(total_lines):
        concepto = request.form.get(f'concepto_{i}')
        if concepto and concepto.strip():
            try:
                unidades = float(request.form.get(f'unidades_{i}', 1.00) or 1.00)
                precio = float(request.form.get(f'precio_{i}', 0.00) or 0.00)
                descuento = float(request.form.get(f'descuento_{i}', 0.00) or 0.00)
            except ValueError:
                unidades, precio, descuento = 1.00, 0.00, 0.00
                
            impuesto = request.form.get(f'impuesto_{i}', '21% IVA')
            subtotal = unidades * precio * (1.0 - (descuento / 100.0))
            
            total_base += subtotal
            porcentaje_iva = 0.21 if '21%' in impuesto else (0.10 if '10%' in impuesto else 0.04 if '4%' in impuesto else 0.0)
            total_imp += subtotal * porcentaje_iva

            raw_info = request.form.get(f'informacion_{i}', '')
            informacion_limpia = raw_info.strip() if raw_info and raw_info.strip() else None

            lineas_dict.append({
                'producto_id': request.form.get(f'articulo_id_{i}'),
                'concepto': concepto,
                'informacion': informacion_limpia, # Guardamos el valor limpio
                'unidades': unidades,
                'precio_unitario': precio,
                'descuento_porcentaje': descuento,
                'impuesto_tipo': impuesto,
                'subtotal_linea': subtotal
            })

    # 2. Convertir esos mismos diccionarios en objetos Mock para la plantilla Jinja del PDF
    class MockLinea:
        def __init__(self, d):
            self.producto_id = d['producto_id']
            self.concepto = d['concepto']
            self.informacion = d['informacion']
            self.unidades = d['unidades']
            self.precio_unitario = d['precio_unitario']
            self.descuento_porcentaje = d['descuento_porcentaje']
            self.impuesto_tipo = d['impuesto_tipo']
            self.subtotal_linea = d['subtotal_linea']

    lineas_objetos = [MockLinea(d) for d in lineas_dict]

    # 3. Formatear fechas
    fecha_emision_str = request.form.get('fecha_emision', '')
    fecha_entrega_str = request.form.get('fecha_entrega', '')
    fecha_emision_obj = datetime.strptime(fecha_emision_str, '%Y-%m-%d').date() if fecha_emision_str else None
    fecha_entrega_obj = datetime.strptime(fecha_entrega_str, '%Y-%m-%d').date() if fecha_entrega_str else None

    # 4. Simular el Albarán con todas las propiedades esperadas
    class MockAlbaran:
        def __init__(self, form, f_emision, f_entrega, listado_lineas, base, imp):
            self.numero_albaran = form.get('numero_albaran', 'PREVIEW')
            self.fecha_emision = f_emision
            self.fecha_entrega = f_entrega
            self.referencia = form.get('referencia', '')
            self.referencia_presupuesto = form.get('referencia_presupuesto', '')
            self.notas = form.get('notas', '')
            self.estado = 'Borrador'
            self.total_base_imponible = base
            self.total_impuestos = imp
            self.total_albaran = base + imp
            self.lineas = listado_lineas

    albaran_mock = MockAlbaran(request.form, fecha_emision_obj, fecha_entrega_obj, lineas_objetos, total_base, total_imp)
    logo_base64 = PDFGenerator.get_logo_base64(config.logo_path if config else "")
    
    # Pasamos la estructura plana de diccionarios que tu PDFGenerator maneja sin romperse
    lineas_html = PDFGenerator.build_lines_html(lineas_dict)

    context = {
        'albaran': albaran_mock,
        'config': config,
        'cliente': cliente,
        'logo_base64': logo_base64,
        'metodo_pago': metodo_pago,
        'lineas_html': lineas_html
    }

    try:
        pdf_bytes = PDFGenerator.render_to_pdf('pdf_templates/albaran_pdf.html', context)
    except Exception as e:
        return make_response(f"Error al compilar el PDF: {str(e)}", 500)
    
    response = make_response(pdf_bytes)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'inline; filename=preview_albaran.pdf'
    return response