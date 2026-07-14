from datetime import date, datetime
from decimal import Decimal
from flask import Blueprint, flash, redirect, render_template, request, url_for
from models import Factura, Gasto, Pago, db

payments_bp = Blueprint('payments', __name__, url_prefix='/pagos')

# Función auxiliar para evitar repetición de código (DRY)
def actualizar_estado_documento(pago):
    # Lógica para Facturas
    if pago.factura_id:
        factura = Factura.query.get(pago.factura_id)
        if factura:
            total_pagado = db.session.query(db.func.sum(Pago.importe)).filter(Pago.factura_id == factura.id).scalar() or 0
            
            # CAMBIADO: Se usa estado_contable en lugar de estado_pago
            if total_pagado > factura.total_factura:
                factura.estado_contable = 'Pagado en exceso'
            elif total_pagado == factura.total_factura:
                factura.estado_contable = 'Cobrada'
            elif total_pagado > 0:
                factura.estado_contable = 'Parcialmente cobrada'
            else:
                factura.estado_contable = 'Pendiente'
    
    # Lógica para Gastos (Este se queda igual porque el modelo Gasto conserva estado_pago)
    if pago.gasto_id:
        gasto = Gasto.query.get(pago.gasto_id)
        if gasto:
            total_pagado = db.session.query(db.func.sum(Pago.importe)).filter(Pago.gasto_id == gasto.id).scalar() or 0
            
            if total_pagado > gasto.total_factura:
                gasto.estado_pago = 'Pagado en exceso'
            elif total_pagado == gasto.total_factura:
                gasto.estado_pago = 'Pagada'
            elif total_pagado > 0:
                gasto.estado_pago = 'Parcialmente pagada'
            else:
                gasto.estado_pago = 'Recibida'
    
    db.session.commit()

@payments_bp.route('/', methods=['GET', 'POST'])
def pagos():
    if request.method == 'POST':
        # 1. Obtenemos datos
        factura_id = request.form.get('factura_id')
        gasto_id = request.form.get('gasto_id')
        importe = Decimal(request.form.get('importe', '0') or '0')
        
        # 2. Creamos el objeto (pero aún no lo guardamos)
        pago = Pago(
            fecha_pago=datetime.strptime(request.form.get('fecha_pago', ''), '%Y-%m-%d').date() if request.form.get('fecha_pago') else date.today(),
            tipo_movimiento=request.form.get('tipo_movimiento', 'Ingreso'),
            factura_id=int(factura_id) if factura_id else None,
            gasto_id=int(gasto_id) if gasto_id else None,
            metodo_pago=request.form.get('metodo_pago', '').strip(),
            importe=importe,
            cuenta_bancaria_destino=request.form.get('cuenta_bancaria_destino', '').strip(),
            estado='Conciliado'
        )
        
        # 3. Lógica de validación antes de guardar
        if pago.factura_id:
            factura = Factura.query.get(pago.factura_id)
            if factura:  # ← guarda
                total_ya_pagado = db.session.query(db.func.sum(Pago.importe)).filter(Pago.factura_id == factura.id).scalar() or 0
                if (total_ya_pagado + importe) > factura.total_factura:
                    flash(f'Atención: El pago supera el saldo pendiente de la factura {factura.numero_factura}.', 'warning')

        if pago.gasto_id:
            gasto = Gasto.query.get(pago.gasto_id)
            if gasto:  # ← guarda
                total_ya_pagado = db.session.query(db.func.sum(Pago.importe)).filter(Pago.gasto_id == gasto.id).scalar() or 0
                if (total_ya_pagado + importe) > gasto.total_factura:
                    flash(f'Atención: El pago supera el saldo pendiente del gasto {gasto.numero_factura_proveedor}.', 'warning')

        # 4. Guardamos
        db.session.add(pago)
        db.session.commit()
        actualizar_estado_documento(pago)
        
        flash('Pago registrado correctamente', 'success')
        return redirect(url_for('payments.pagos'))
    
        

    # Flujo de Caja
   
    # Conciliación de Ingresos (Facturas)
    # Usamos únicamente tipo_factura que es el campo real de tu modelo Factura
    total_facturado = db.session.query(db.func.sum(Factura.total_factura))\
        .filter(Factura.tipo_factura != 'Rectificativa')\
        .scalar() or 0
        
    total_cobrado = db.session.query(db.func.sum(Pago.importe))\
        .join(Factura, Pago.factura_id == Factura.id)\
        .filter(Factura.tipo_factura != 'Rectificativa')\
        .scalar() or 0
    
    # Conciliación de Gastos (Lo que debemos a proveedores)
    # Usamos únicamente tipo_gasto que es el campo real de tu modelo Gasto
    total_gastos_emitidos = db.session.query(db.func.sum(Gasto.total_factura))\
        .filter(Gasto.tipo_gasto != 'Rectificativa')\
        .scalar() or 0
        
    total_pagado_gastos = db.session.query(db.func.sum(Pago.importe))\
        .join(Gasto, Pago.gasto_id == Gasto.id)\
        .filter(Gasto.tipo_gasto != 'Rectificativa')\
        .scalar() or 0

    # Obtenemos los documentos
    todas_las_facturas = Factura.query.order_by(Factura.fecha_factura.desc()).all()
    todos_los_gastos = Gasto.query.order_by(Gasto.fecha_factura.desc()).all()
    
    # Filtramos para enviar solo los pendientes a la UI y excluimos las facturas Borrador
    facturas_pendientes = [f for f in todas_las_facturas if f.estado_contable != 'Cobrada' and f.estado_contable != 'Borrador']
    gastos_pendientes = [g for g in todos_los_gastos if g.estado_pago != 'Pagada']

    # Nueva forma sugerida de calcular
    total_cobrado_clientes = db.session.query(db.func.sum(Pago.importe)).filter(Pago.factura_id.isnot(None)).scalar() or 0
    total_pagado_proveedores = db.session.query(db.func.sum(Pago.importe)).filter(Pago.gasto_id.isnot(None)).scalar() or 0
    
    return render_template(
        'pagos.html', 
        pagos=Pago.query.order_by(Pago.fecha_pago.desc()).all(),
        facturas=facturas_pendientes, # Enviamos solo pendientes
        gastos=gastos_pendientes,      # Enviamos solo pendientes
        total_ingresos=total_cobrado_clientes,
        total_gastos=total_pagado_proveedores,
        pendiente_cobro=total_facturado - total_cobrado,
        pendiente_pago=total_gastos_emitidos - total_pagado_gastos,
        today=date.today()
    )

@payments_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
def pagos_editar(id):
    pago = Pago.query.get_or_404(id)
    if request.method == 'POST':
        pago.importe = Decimal(request.form.get('importe', '0') or '0')
        fecha_pago_str = request.form.get('fecha_pago') or ''
        pago.fecha_pago = datetime.strptime(fecha_pago_str, '%Y-%m-%d').date() if fecha_pago_str else date.today()
        pago.metodo_pago = request.form.get('metodo_pago', '').strip()
        pago.tipo_movimiento = request.form.get('tipo_movimiento', 'Ingreso')
        
        db.session.commit()
        actualizar_estado_documento(pago) # Re-calcula estados tras edición
        
        flash('Pago actualizado correctamente', 'success')
        return redirect(url_for('payments.pagos'))
    return render_template('pagos_form.html', pago=pago)


@payments_bp.route('/<int:id>/eliminar', methods=['POST'])
def pagos_eliminar(id):
    pago = Pago.query.get_or_404(id)
    
    # Guardamos los IDs de forma temporal para actualizar los estados después de borrar
    factura_id = pago.factura_id
    gasto_id = pago.gasto_id
    
    try:
        # Eliminamos el registro del pago de la base de datos
        db.session.delete(pago)
        db.session.commit()
        
        # Forzamos la actualización de los estados contables del documento desvinculado
        # Creamos un objeto pago "ficticio" temporal con el ID para reutilizar tu función auxiliar DRY
        class PagoTemporal:
            def __init__(self, f_id, g_id):
                self.factura_id = f_id
                self.gasto_id = g_id
                
        pago_temp = PagoTemporal(factura_id, gasto_id)
        actualizar_estado_documento(pago_temp)
        
        flash('El pago ha sido anulado y eliminado correctamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Ocurrió un error al intentar anular el pago.', 'error')
        
    return redirect(url_for('payments.pagos'))