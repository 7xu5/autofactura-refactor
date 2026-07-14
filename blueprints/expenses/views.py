import os
from datetime import date, datetime
from decimal import Decimal

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from models import Contacto, Gasto, ImpuestoGasto, db
from utils.file_handlers import allowed_file
import io
from flask import send_file
from xhtml2pdf import pisa

expenses_bp = Blueprint('expenses', __name__, url_prefix='/gastos')


@expenses_bp.route('/')
def gastos():
    pestana = request.args.get('pestana', 'Recibida')
    query = Gasto.query
    if pestana in ['Recibida', 'Pagada', 'A revisar']:
        query = query.filter(Gasto.estado_pago == pestana)
    search = request.args.get('q', '').strip()
    if search:
        query = query.join(Contacto).filter(
            (Gasto.numero_factura_proveedor.ilike(f'%{search}%'))
            | (Contacto.nombre_fiscal.ilike(f'%{search}%'))
        )
    gastos = query.order_by(Gasto.fecha_factura.desc()).all()
    return render_template('gastos.html', gastos=gastos, pestana=pestana, search=search)

# --- FUNCIÓN AUXILIAR CENTRALIZADA ---
def procesar_impuestos(gasto_id):
    """Limpia y guarda los impuestos asociados a un gasto."""
    ImpuestoGasto.query.filter_by(gasto_id=gasto_id).delete()
    
    tipos = request.form.getlist('impuesto_tipo[]')
    bases = request.form.getlist('impuesto_base[]')
    cuotas = request.form.getlist('impuesto_cuota[]')
    
    for tipo, base, cuota in zip(tipos, bases, cuotas):
        base_val = float(base) if base else 0.0
        cuota_val = float(cuota) if cuota else 0.0
        if base_val > 0 or cuota_val > 0:
            db.session.add(ImpuestoGasto(gasto_id=gasto_id, tipo=tipo, base=base_val, cuota=cuota_val))


def persistir_gasto_y_impuestos(gasto, request_form, archivo=None):
    """Guarda o actualiza gasto y sus impuestos hijos."""
    # 1. Asignación de campos del Gasto
    gasto.numero_factura_proveedor = request_form.get('numero_factura_proveedor', '').strip()
    gasto.contacto_id = request_form.get('contacto_id')
    gasto.referencia = request_form.get('referencia', '').strip()
    gasto.tipo_gasto = request_form.get('tipo_gasto', 'Gasto operativa')

    # CORRECCIÓN AQUÍ: Cambiado 'ruta_adjunto_url' por 'ruta_adjunto_actual'
    ruta_form = request_form.get('ruta_adjunto_actual')
    if archivo:
        gasto.ruta_adjunto_url = archivo
    elif ruta_form:
        gasto.ruta_adjunto_url = ruta_form

    fecha_fac = request_form.get('fecha_factura')
    gasto.fecha_factura = datetime.strptime(fecha_fac, '%Y-%m-%d').date() if fecha_fac else date.today()

    fecha_ven = request_form.get('fecha_vencimiento')
    gasto.fecha_vencimiento = datetime.strptime(fecha_ven, '%Y-%m-%d').date() if fecha_ven else None

    gasto.porcentaje_retencion = Decimal(request_form.get('porcentaje_retencion', '0') or '0')
    gasto.importe_retencion = Decimal(request_form.get('importe_retencion', '0') or '0')
    gasto.total_factura = Decimal(request_form.get('total_factura', '0') or '0')

    db.session.add(gasto)
    db.session.flush()

    # 2. Procesamiento de Impuestos (ImpuestoGasto)
    ImpuestoGasto.query.filter_by(gasto_id=gasto.id).delete()
    tipos = request_form.getlist('impuesto_tipo[]')
    bases = request_form.getlist('impuesto_base[]')
    cuotas = request_form.getlist('impuesto_cuota[]')
    
    for tipo, base, cuota in zip(tipos, bases, cuotas):
        base_val = Decimal(base or '0')
        cuota_val = Decimal(cuota or '0')
        if base_val > 0 or cuota_val > 0:
            db.session.add(ImpuestoGasto(gasto_id=gasto.id, tipo=tipo, base=base_val, cuota=cuota_val))
    
    db.session.commit()

@expenses_bp.route('/subir', methods=['GET', 'POST'])
def gasto_subir():
    if request.method == 'POST':
        gasto = Gasto(estado_pago='Recibida')
        
        # Procesar el archivo SOLO si existe
        ruta_archivo = None
        archivo = request.files.get('documento')
        if archivo and archivo.filename and allowed_file(archivo.filename):
            safe_name = secure_filename(archivo.filename)
            local_path = os.path.join(current_app.root_path, 'static', 'uploads')
            os.makedirs(local_path, exist_ok=True)
            archivo.save(os.path.join(local_path, safe_name))
            ruta_archivo = os.path.join('uploads', safe_name).replace('\\', '/')
            
        # Pasamos la ruta del archivo (o None) a la función de persistencia
        persistir_gasto_y_impuestos(gasto, request.form, archivo=ruta_archivo)
        
        flash('Gasto registrado exitosamente', 'success')
        return redirect(url_for('expenses.gastos'))
    
    proveedores = Contacto.query.filter(Contacto.tipo_contacto.in_(['Proveedor', 'Ambas'])).all()    
    return render_template('gasto_form.html', contactos=proveedores, gasto=None)

@expenses_bp.route('/<int:gasto_id>/editar', methods=['GET', 'POST'])
def gasto_editar(gasto_id):
    gasto = Gasto.query.get_or_404(gasto_id)
    if request.method == 'POST':
        nueva_ruta = None
        archivo = request.files.get('documento')
        if archivo and archivo.filename and allowed_file(archivo.filename):
            safe_name = secure_filename(archivo.filename)
            local_path = os.path.join(current_app.root_path, 'static', 'uploads')
            os.makedirs(local_path, exist_ok=True)
            archivo.save(os.path.join(local_path, safe_name))
            nueva_ruta = os.path.join('uploads', safe_name).replace('\\', '/')
        else:
            # Si no hay archivo nuevo, mantenemos la ruta que ya tenía el gasto
            nueva_ruta = gasto.ruta_adjunto_url
        
        # Pasamos la nueva_ruta (será None si no se cambió el archivo)
        persistir_gasto_y_impuestos(gasto, request.form, archivo=nueva_ruta)
        flash('Gasto actualizado', 'success')
        return redirect(url_for('expenses.gastos'))
    
    proveedores = Contacto.query.filter(Contacto.tipo_contacto.in_(['Proveedor', 'Ambas'])).all()
    return render_template('gasto_form.html', contactos=proveedores, gasto=gasto)

@expenses_bp.route('/guardar', methods=['POST'])
def guardar_gasto():
    gasto_id = request.form.get('id')
    gasto = Gasto.query.get(gasto_id) if gasto_id else Gasto(estado_pago='Recibida')
    
    if not gasto:
        flash('Error: Gasto no encontrado.', 'danger')
        return redirect(url_for('expenses.gastos'))
    
    # Simplemente llamamos a la función centralizada
    persistir_gasto_y_impuestos(gasto, request.form)
    
    flash('Gasto guardado correctamente.', 'success')
    return redirect(url_for('expenses.gastos'))


@expenses_bp.route('/<int:gasto_id>/eliminar', methods=['POST'])
def gasto_eliminar(gasto_id):
    gasto = Gasto.query.get_or_404(gasto_id)
    db.session.delete(gasto)
    db.session.commit()
    return jsonify({'status': 'ok'})


@expenses_bp.route('/<int:gasto_id>/descargar')
def gasto_descargar(gasto_id):
    gasto = Gasto.query.get_or_404(gasto_id)
    
    # CASO 1: Si el usuario ya subió un archivo físico, se lo redirigimos
    if gasto.ruta_adjunto_url:
        return redirect(url_for('static', filename=gasto.ruta_adjunto_url))
        
    # CASO 2: Si no hay archivo, generamos un documento PDF con sus datos y su desglose
    try:
        # Renderizamos la plantilla pasando el objeto 'gasto' exacto
        html_content = render_template('pdf_templates/pdf_gasto_reporte.html', gasto=gasto)
        
        pdf_buffer = io.BytesIO()
        pisa_status = pisa.CreatePDF(io.StringIO(html_content), dest=pdf_buffer)
        
        if pisa_status.err:
            raise Exception("Error al compilar el HTML a PDF con xhtml2pdf")
            
        pdf_buffer.seek(0)
        
        # --- NUEVA LÓGICA PARA EL NOMBRE DEL ARCHIVO ---
        # 1. Obtenemos el número de factura o usamos el ID como salvavidas
        num_factura = gasto.numero_factura_proveedor or str(gasto.id)
        
        # 2. Obtenemos el nombre del proveedor si existe, si no ponemos "SinProveedor"
        nombre_prov = gasto.contacto.nombre_fiscal if gasto.contacto else "SinProveedor"
        
        # 3. Limpiamos el nombre del proveedor para evitar espacios y caracteres problemáticos en archivos
        # Reemplaza espacios por guiones bajos y elimina acentos/caracteres extraños comunes
        nombre_prov_limpio = "".join(c for c in nombre_prov if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')
        num_factura_limpio = "".join(c for c in num_factura if c.isalnum() or c in ('_', '-')).strip().replace(' ', '_')
        
        # 4. Construimos el nombre final: Gasto_Numero_Proveedor.pdf
        nombre_archivo = f"Gasto_{num_factura_limpio}_{nombre_prov_limpio}.pdf"
        # -----------------------------------------------
        
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=nombre_archivo
        )
        
    except Exception as e:
        import traceback
        
        pestana_actual = request.args.get('pestana', 'Recibida')
        flash(f'No se pudo generar el reporte del gasto: {str(e)}', 'danger')
        return redirect(url_for('expenses.gastos', pestana=pestana_actual))


