from decimal import Decimal

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from utils.sequence_generators import generate_product_code
from models import Producto, db

products_bp = Blueprint('products', __name__, url_prefix='/productos')


@products_bp.route('/')
def productos():
    items = Producto.query.order_by(Producto.nombre).all()
    return render_template('productos.html', productos=items)


@products_bp.route('/nuevo', methods=['GET', 'POST'])
def producto_nuevo():
    if request.method == 'POST':
        # 1. Recoger datos
        codigo = request.form.get('codigo', '').strip()
        nombre = request.form.get('nombre', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        descripcion_adicional = request.form.get('descripcion_adicional', '').strip()
        precio_raw = request.form.get('precio_unitario_base', '0')
        precio = Decimal(precio_raw if precio_raw else '0')
        impuesto = request.form.get('impuesto_defecto', '21% IVA')

        # 2. Validaciones (Usamos 'if' independientes o una lista de errores)
        if not codigo:
            flash("El código del producto es obligatorio.", "danger")
            return render_template('producto_form.html')
            
        if not nombre or precio <= 0:
            flash('El nombre y un precio válido son obligatorios.', 'danger')
            return render_template('producto_form.html')

        # 3. Comprobar si el código ya existe antes de crear el objeto
        # Esto evita el IntegrityError antes de que ocurra
        producto_existente = Producto.query.filter_by(codigo=codigo).first()
        if producto_existente:
            flash(f"El código '{codigo}' ya está en uso.", "danger")
            return render_template('producto_form.html')

        # 4. Guardar
        nuevo_producto = Producto(
            codigo=codigo,
            nombre=nombre,
            descripcion=descripcion,
            descripcion_adicional=descripcion_adicional,
            precio_unitario_base=precio,
            impuesto_defecto=impuesto
        )
        db.session.add(nuevo_producto)
        db.session.commit()
        flash('Producto añadido con éxito', 'success')
        return redirect(url_for('products.productos'))

    nuevo_codigo = generate_product_code()
    return render_template('producto_form.html', nuevo_codigo=nuevo_codigo)


@products_bp.route('/api')
def api_productos():
    term = request.args.get('q', '').strip().lower()
    productos = Producto.query.order_by(Producto.nombre).all()
    return jsonify([
        {
            'id': p.id,
            'nombre': p.nombre,
            'precio': str(p.precio_unitario_base),
            'impuesto': p.impuesto_defecto,
            'descripcion_adicional': p.descripcion_adicional,
        }
        for p in productos
        if term in p.nombre.lower()
    ])

@products_bp.route('/editar/<int:id>', methods=['GET', 'POST'])
def editar_producto(id):
    producto = Producto.query.get_or_404(id)
    if request.method == 'POST':
        # 1. Recoger datos
        nuevo_codigo = request.form.get('codigo', '').strip()
        nuevo_nombre = request.form.get('nombre', '').strip()
        
        # 2. Validaciones básicas
        if not nuevo_codigo:
            flash("El código es obligatorio.", "danger")
            return render_template('producto_form.html', producto=producto)
            
        # 3. Validación de unicidad (excluyendo al producto actual)
        producto_duplicado = Producto.query.filter(
            Producto.codigo == nuevo_codigo, 
            Producto.id != id
        ).first()
        
        if producto_duplicado:
            flash(f"El código '{nuevo_codigo}' ya está asignado a otro producto.", "danger")
            return render_template('producto_form.html', producto=producto)

        # 4. Asignación de valores
        producto.codigo = nuevo_codigo
        producto.nombre = nuevo_nombre
        producto.descripcion = request.form.get('descripcion', '').strip()
        producto.descripcion_adicional = request.form.get('descripcion_adicional', '').strip()
        
        precio_raw = request.form.get('precio_unitario_base', '0')
        producto.precio_unitario_base = Decimal(precio_raw or '0')
        producto.impuesto_defecto = request.form.get('impuesto_defecto', '21% IVA')
        
        # 5. Commit
        try:
            db.session.commit()
            flash('Producto actualizado', 'success')
            return redirect(url_for('products.productos'))
        except Exception as e:
            db.session.rollback()
            flash('Error al actualizar el producto.', 'danger')
            return render_template('producto_form.html', producto=producto)
    
    return render_template('producto_form.html', producto=producto)

@products_bp.route('/borrar/<int:id>', methods=['POST'])
def borrar_producto(id):
    producto = Producto.query.get_or_404(id)
    db.session.delete(producto)
    db.session.commit()
    flash('Producto eliminado', 'success')
    return redirect(url_for('products.productos'))
