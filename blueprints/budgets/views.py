# blueprints/budgets/views.py
import json
from datetime import date, datetime
from decimal import Decimal

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, make_response, abort
from models import db, Contacto, Presupuesto, MetodoPago, Configuracion, Producto, Factura, FacturaLinea
from utils.sequence_generators import generate_invoice_number, generate_budget_number

# NUEVOS IMPORTES TRAS LA REFACTORIZACIÓN SOLID
from services.budget_service import BudgetService
from utils.pdf_generator import PDFGenerator

budgets_bp = Blueprint('budgets', __name__, url_prefix='/presupuestos')


@budgets_bp.route('/')
def presupuestos():
    estado = request.args.get('estado', 'Todos')
    query = Presupuesto.query
    if estado in ['Borrador', 'Enviado', 'Aceptado', 'Rechazado']:
        query = query.filter(Presupuesto.estado == estado)
    presupuestos = query.order_by(Presupuesto.fecha_emision.desc()).all()
    return render_template('presupuestos.html', presupuestos=presupuestos, estado=estado)


@budgets_bp.route('/crear', methods=['GET', 'POST'])
def presupuesto_crear():
    contactos = Contacto.query.filter(Contacto.tipo_contacto != 'Proveedor').order_by(Contacto.nombre_fiscal).all()
    metodos_pago = MetodoPago.query.all()
    productos = Producto.query.order_by(Producto.nombre).all()
    
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
            BudgetService.create_budget(request.form)
            flash('Presupuesto creado con éxito', 'success')
            return redirect(url_for('budgets.presupuestos'))
        except ValueError as e:
            # Capturamos los errores lanzados por el servicio (sin cliente, sin líneas)
            flash(str(e), 'danger')
            lineas_raw, _, _, _ = BudgetService.parse_form_lines(request.form)
            return render_template(
                'presupuesto_form.html', 
                contactos=contactos, 
                metodos_pago=metodos_pago, 
                lineas=lineas_raw,
                numero_presupuesto=request.form.get('numero_presupuesto') or generate_budget_number(),
                productos_json=productos_json
            )

    return render_template(
        'presupuesto_form.html', 
        contactos=contactos, 
        metodos_pago=metodos_pago, 
        numero_presupuesto=generate_budget_number(), 
        lineas=[], 
        productos_json=productos_json
    )


@budgets_bp.route('/<int:presupuesto_id>/editar', methods=['GET', 'POST'])
def presupuesto_editar(presupuesto_id):
    presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
    contactos = Contacto.query.filter(Contacto.tipo_contacto != 'Proveedor').order_by(Contacto.nombre_fiscal).all()
    metodos_pago = MetodoPago.query.all()
    productos = Producto.query.order_by(Producto.nombre).all()
    
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
            BudgetService.update_budget(presupuesto, request.form)
            flash('Presupuesto actualizado con éxito', 'success')
            return redirect(url_for('budgets.presupuestos'))
        except ValueError as e:
            flash(str(e), 'danger')
            lineas_raw, _, _, _ = BudgetService.parse_form_lines(request.form)
            return render_template(
                'presupuesto_form.html',
                presupuesto=presupuesto, 
                contactos=contactos, 
                metodos_pago=metodos_pago, 
                lineas=lineas_raw, 
                selected_contacto_id=request.form.get('contacto_id')
            )

    return render_template(
        'presupuesto_form.html',
        presupuesto=presupuesto,
        contactos=contactos,
        metodos_pago=metodos_pago,
        numero_presupuesto=presupuesto.numero_presupuesto,
        fecha_emision=presupuesto.fecha_emision.isoformat(),
        fecha_validez=presupuesto.fecha_validez.isoformat(),
        referencia=presupuesto.referencia,
        estado=presupuesto.estado,
        notas=presupuesto.notas,
        lineas=presupuesto.lineas_json(),
        selected_contacto_id=presupuesto.contacto_id,
        selected_metodo_pago_id=presupuesto.metodo_pago_id,
        productos_json=productos_json
    )


@budgets_bp.route('/<int:id>/descargar')
def presupuesto_descargar(id):
    presupuesto = db.session.get(Presupuesto, id)
    if not presupuesto:
        abort(404)

    config = Configuracion.query.first()
    cliente = db.session.get(Contacto, presupuesto.contacto_id)
    metodo_pago = db.session.get(MetodoPago, presupuesto.metodo_pago_id) if presupuesto.metodo_pago_id else None

    # Delegación de tareas de PDF a su clase utilitaria
    logo_base64 = PDFGenerator.get_logo_base64(config.logo_path if config else "")
    lineas_html = PDFGenerator.build_lines_html(presupuesto.lineas_json())

    context = {
        'presupuesto': presupuesto,
        'config': config,
        'cliente': cliente,
        'logo_base64': logo_base64,
        'metodo_pago': metodo_pago,
        'lineas_html': lineas_html
    }

    pdf_bytes = PDFGenerator.render_to_pdf('pdf_templates/budget_pdf.html', context)
    
    response = make_response(pdf_bytes)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=Presupuesto_{presupuesto.numero_presupuesto}.pdf'
    return response


@budgets_bp.route('/previsualizar', methods=['POST'])
def presupuesto_previsualizar():
    cliente_id = request.form.get('contacto_id')
    cliente = db.session.get(Contacto, int(cliente_id)) if cliente_id and cliente_id.isdigit() else None
    config = Configuracion.query.first()

    if not cliente:
        return 'Seleccione un cliente primero', 400

    # Lógica de cálculo delegada al BudgetService
    lineas, total_base, total_impuestos, total_presupuesto = BudgetService.parse_form_lines(request.form)
    
    logo_base64 = PDFGenerator.get_logo_base64(config.logo_path if config else "")
    lineas_html = PDFGenerator.build_lines_html(lineas)
    
    metodo_pago_id = request.form.get('metodo_pago_id')
    metodo_pago = db.session.get(MetodoPago, int(metodo_pago_id)) if metodo_pago_id and metodo_pago_id.isdigit() else None

    # Simular objeto presupuesto para la plantilla (mantenido por compatibilidad con budget_preview.html)
    class PresupuestoSimulado:
        def __init__(self):
            self.numero_presupuesto = request.form.get('numero_presupuesto') or generate_budget_number()
            f_emision = request.form.get('fecha_emision')
            f_validez = request.form.get('fecha_validez')
            self.fecha_emision = datetime.strptime(f_emision, '%Y-%m-%d').date() if f_emision else date.today()
            self.fecha_validez = datetime.strptime(f_validez, '%Y-%m-%d').date() if f_validez else date.today()
            self.referencia = request.form.get('referencia', '')
            self.total_base_imponible = total_base
            self.total_impuestos = total_impuestos
            self.total_presupuesto = total_presupuesto

    context = {
        'presupuesto': PresupuestoSimulado(),
        'config': config,
        'cliente': cliente,
        'lineas_html': lineas_html,
        'logo_base64': logo_base64,
        'metodo_pago': metodo_pago
    }

    pdf_bytes = PDFGenerator.render_to_pdf('pdf_templates/budget_preview.html', context)
    
    response = make_response(pdf_bytes)
    response.headers['Content-Type'] = 'application/pdf'
    return response


# --- RUTAS DE ESTADO RESTANTES (Mantienen su lógica simple) ---

@budgets_bp.route('/<int:presupuesto_id>/convertir', methods=['POST'])
def presupuesto_convertir(presupuesto_id):
    presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
    factura = Factura(
        numero_factura=generate_invoice_number(),
        tipo_pestana='Emitida',
        estado_ui='Borrador',
        estado_contable='Pendiente',
        contacto_id=presupuesto.contacto_id,
        metodo_pago_id=presupuesto.metodo_pago_id,
        referencia=presupuesto.referencia,
        referencia_presupuesto=presupuesto.numero_presupuesto,
        fecha_factura=date.today(),
        total_base_imponible=presupuesto.total_base_imponible,
        total_cuota_iva=presupuesto.total_impuestos,
        total_recargo_equivalencia=Decimal('0.00'),
        total_factura=presupuesto.total_presupuesto,
        verifactu_enviada=False,
        verifactu_estado='Pendiente'
    )
    
    for linea_p in presupuesto.lineas:
        porcentaje_iva = Decimal('21.00')
        if '21' in getattr(linea_p, 'impuesto_tipo', '21% IVA'): porcentaje_iva = Decimal('21.00')
        elif '10' in getattr(linea_p, 'impuesto_tipo', ''): porcentaje_iva = Decimal('10.00')
        elif '4' in getattr(linea_p, 'impuesto_tipo', ''): porcentaje_iva = Decimal('4.00')
        elif '0' in getattr(linea_p, 'impuesto_tipo', '') or 'Exento' in getattr(linea_p, 'impuesto_tipo', ''): porcentaje_iva = Decimal('0.00')

        nueva_linea_factura = FacturaLinea(
            concepto=linea_p.concepto,
            informacion=linea_p.informacion,
            unidades=linea_p.unidades,
            precio_unitario=linea_p.precio_unitario,
            descuento_porcentaje=linea_p.descuento_porcentaje,
            impuesto_tipo=linea_p.impuesto_tipo,
            porcentaje_iva=porcentaje_iva,
            porcentaje_recargo=Decimal('0.00'),
            subtotal_linea=linea_p.subtotal_linea
        )
        factura.lineas.append(nueva_linea_factura)

    db.session.add(factura)
    db.session.commit()
    flash('Presupuesto convertido a factura borrador con éxito', 'success')
    return redirect(url_for('invoices.factura_editar', factura_id=factura.id))

@budgets_bp.route('/<int:presupuesto_id>/enviar', methods=['POST'])
def presupuesto_enviar(presupuesto_id):
    presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
    presupuesto.estado = 'Enviado'
    db.session.commit()
    flash('Presupuesto marcado como enviado', 'success')
    return redirect(url_for('budgets.presupuestos'))

@budgets_bp.route('/<int:presupuesto_id>/rechazar', methods=['POST'])
def presupuesto_rechazar(presupuesto_id):
    presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
    presupuesto.estado = 'Rechazado'
    db.session.commit()
    flash('Presupuesto marcado como rechazado', 'success')
    return redirect(url_for('budgets.presupuestos'))

@budgets_bp.route('/<int:presupuesto_id>/borrador', methods=['POST'])
def presupuesto_volver_borrador(presupuesto_id):
    presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
    presupuesto.estado = 'Borrador'
    db.session.commit()
    flash('Presupuesto vuelto a borrador', 'success')
    return redirect(url_for('budgets.presupuestos'))

@budgets_bp.route('/<int:presupuesto_id>/aceptar', methods=['POST'])
def presupuesto_aceptar(presupuesto_id):
    presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
    presupuesto.estado = 'Aceptado'
    db.session.commit()
    flash('Presupuesto marcado como aceptado', 'success')
    return redirect(url_for('budgets.presupuestos'))

@budgets_bp.route('/<int:presupuesto_id>/eliminar', methods=['POST'])
def presupuesto_eliminar(presupuesto_id):
    presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
    db.session.delete(presupuesto)
    db.session.commit()
    return jsonify({'status': 'ok'})