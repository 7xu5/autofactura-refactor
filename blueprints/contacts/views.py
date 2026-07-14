
from flask import Blueprint, flash, redirect, render_template, request, url_for, jsonify

from models import Contacto, db
from services.borme_service import OpenMercantilService

contacts_bp = Blueprint('contacts', __name__, url_prefix='/contactos')
borme_service = OpenMercantilService()

@contacts_bp.route('/')
def contactos():
    tipo = request.args.get('tipo', 'Cliente')
    query = Contacto.query
    if tipo == 'Cliente':
        query = query.filter(Contacto.tipo_contacto.in_(['Cliente', 'Ambas']))
    elif tipo == 'Proveedor':
        query = query.filter(Contacto.tipo_contacto.in_(['Proveedor', 'Ambas']))

    busqueda = request.args.get('q', '').strip()
    if busqueda:
        query = query.filter(
            (Contacto.nombre_fiscal.ilike(f'%{busqueda}%'))
            | (Contacto.numero_documento.ilike(f'%{busqueda}%'))
        )

    contactos = query.order_by(Contacto.nombre_fiscal).all()
    for contacto in contactos:
        if contacto.tipo_contacto == 'Proveedor':
            # Gastos totales (valores positivos)
            contacto.total_facturado = sum(
                float(g.total_factura) for g in contacto.gastos if g.estado_pago == 'Pagada'
            )
            # Evitamos sumar importes negativos de rectificativas como saldo pendiente de pago
            contacto.total_pendiente = sum(
                float(g.total_factura) for g in contacto.gastos 
                if g.estado_pago != 'Pagada' and float(g.total_factura) > 0
            )
        else:
            # Facturas totales (valores positivos)
            contacto.total_facturado = sum(
                float(f.total_factura) for f in contacto.facturas if f.estado_contable == 'Cobrada'
            )
            # Evitamos sumar rectificativas negativas como saldo pendiente de cobro
            contacto.total_pendiente = sum(
                float(f.total_factura) for f in contacto.facturas 
                if f.estado_contable != 'Cobrada' and float(f.total_factura) > 0
            )
            
        fechas = (
            [f.fecha_factura for f in contacto.facturas if f.fecha_factura]
            + [g.fecha_factura for g in contacto.gastos if g.fecha_factura]
        )
        contacto.ultimo_documento = max(fechas).strftime('%Y-%m-%d') if fechas else '-'

    return render_template('contactos.html', contactos=contactos, tipo=tipo, busqueda=busqueda)


@contacts_bp.route('/nuevo', methods=['GET', 'POST'])
def contacto_nuevo():
    contact = None
    if request.method == 'POST':

        # 1. Obtenemos el número de documento primero
        cif = request.form.get('numero_documento', '').strip()
        
        # 2. Verificamos si ya existe en la base de datos
        contacto_existente = Contacto.query.filter_by(numero_documento=cif).first()
        
        if contacto_existente:
            flash(f'Error: Ya existe un contacto registrado con el documento {cif}', 'danger')
            # Devolvemos el formulario con los datos que ya escribió el usuario
            return render_template('contacto_form.html', contact=request.form)
        
        contact = Contacto(
            nombre_fiscal=request.form.get('nombre_fiscal', '').strip(),
            tipo_documento=request.form.get('tipo_documento', 'NIF/CIF'),
            numero_documento=request.form.get('numero_documento', '').strip(),
            tipo_contacto=request.form.get('tipo_contacto', 'Cliente'),
            email_principal=request.form.get('email_principal', '').strip(),
            emails_adicionales=request.form.get('emails_adicionales', '').strip(),
            telefono=request.form.get('telefono', '').strip(),
            direccion_fiscal=request.form.get('direccion_fiscal', '').strip(),
            codigo_postal=request.form.get('codigo_postal', '').strip(),
            ciudad=request.form.get('ciudad', '').strip(),
            provincia=request.form.get('provincia', '').strip(),
            pais=request.form.get('pais', 'Espana').strip(),
            impuesto_defecto=request.form.get('impuesto_defecto', '21% IVA'),
            recargo_equivalencia=bool(request.form.get('recargo_equivalencia')),
            notas=request.form.get('notas', '').strip(),
        )
        if not contact.nombre_fiscal or not contact.numero_documento:
            flash('Nombre fiscal y numero de documento son obligatorios', 'danger')
        else:
            db.session.add(contact)
            db.session.commit()
            flash('Contacto anadido', 'success')
            return redirect(url_for('contacts.contactos'))

    return render_template('contacto_form.html', contact=contact)


@contacts_bp.route('/<int:contacto_id>/editar', methods=['GET', 'POST'])
def contacto_editar(contacto_id):
    contact = Contacto.query.get_or_404(contacto_id)
    
    if request.method == 'POST':
        nuevo_cif = request.form.get('numero_documento', '').strip()
        
        # 1. Comprobar si el nuevo NIF ya existe y NO es el del propio contacto
        # Buscamos si hay ALGUN OTRO contacto con ese mismo NIF
        otro_contacto = Contacto.query.filter(
            Contacto.numero_documento == nuevo_cif,
            Contacto.id != contacto_id
        ).first()

        if otro_contacto:
            flash(f'Error: Ya existe otro contacto con el documento {nuevo_cif}', 'danger')
            return render_template('contacto_form.html', contact=contact)

        # 2. Si no hay conflicto, actualizamos
        contact.nombre_fiscal = request.form.get('nombre_fiscal', '').strip()
        contact.tipo_documento = request.form.get('tipo_documento', 'NIF/CIF')
        contact.numero_documento = nuevo_cif
        contact.tipo_contacto = request.form.get('tipo_contacto', 'Cliente')
        contact.email_principal = request.form.get('email_principal', '').strip()
        contact.emails_adicionales = request.form.get('emails_adicionales', '').strip()
        contact.telefono = request.form.get('telefono', '').strip()
        contact.direccion_fiscal = request.form.get('direccion_fiscal', '').strip()
        contact.codigo_postal = request.form.get('codigo_postal', '').strip()
        contact.ciudad = request.form.get('ciudad', '').strip()
        contact.provincia = request.form.get('provincia', '').strip()
        contact.pais = request.form.get('pais', 'Espana').strip()
        contact.impuesto_defecto = request.form.get('impuesto_defecto', '21% IVA')
        contact.recargo_equivalencia = bool(request.form.get('recargo_equivalencia'))
        contact.notas = request.form.get('notas', '').strip()

        if not contact.nombre_fiscal or not contact.numero_documento:
            flash('Nombre fiscal y numero de documento son obligatorios', 'danger')
        else:
            try:
                db.session.commit()
                flash('Contacto actualizado', 'success')
                return redirect(url_for('contacts.contactos'))
            except Exception as e:
                db.session.rollback()
                flash('Error al guardar en la base de datos', 'danger')

    #print(f"DEBUG: Nombre fiscal en objeto: {contact.nombre_fiscal}")
    #print(f"DEBUG: Ciudad en objeto: {contact.ciudad}")
    return render_template('contacto_form.html', contact=contact)

@contacts_bp.route('/<int:contacto_id>/eliminar', methods=['POST'])
def contacto_eliminar(contacto_id):
    contacto = Contacto.query.get_or_404(contacto_id)
    try:
        db.session.delete(contacto)
        db.session.commit()
        return jsonify({"success": True, "message": "Contacto eliminado"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

@contacts_bp.route('/autocompletar')
def autocompletar_cif():
    """Endpoint API que será llamado desde el JavaScript del formulario."""
    cif = request.args.get('cif', '').strip()
    if not cif:
        return jsonify({"success": False, "message": "El CIF es obligatorio"}), 400
        
    resultado = borme_service.consultar_por_cif(cif)
    return jsonify(resultado)
