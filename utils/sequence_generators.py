from datetime import datetime
from models import Factura, Presupuesto, Configuracion, Albaran

def _generate_sequence_number(model, field_attr, prefix, initial_value=1):
    """
    Función interna genérica que automatiza la búsqueda del último número 
    correlativo de cualquier serie, ordenando por el número de serie real 
    para ser inmune a saltos o borrados de ID en el uso diario.
    """
    if not prefix.endswith('-'):
        prefix = f'{prefix}-'
        
    # CAMBIO CLAVE: Ordenamos por el atributo del número físico (ej. numero_factura) 
    # de forma descendente, en lugar de model.id.desc()
    last = model.query.filter(field_attr.like(f'{prefix}%')).order_by(field_attr.desc()).first()
    
    if last:
        value_str = getattr(last, field_attr.key)
        if '-' in value_str:
            try:
                # Extraemos el número final después del último guion
                last_num = int(value_str.split('-')[-1])
            except ValueError:
                last_num = initial_value - 1
        else:
            last_num = initial_value - 1
    else:
        last_num = initial_value - 1
        
    return f'{prefix}{last_num + 1:03d}'


# ---------------------------------------------------------------------------
# Funciones Oficiales del Sistema
# ---------------------------------------------------------------------------

def generate_invoice_number():
    """Genera el número correlativo para Facturas Ordinarias."""
    year = datetime.now().year
    configuracion = Configuracion.query.first()
    
    prefix = configuracion.serie_factura if configuracion and configuracion.serie_factura else f'F{str(year)[-2:]}-'
    initial = getattr(configuracion, 'numero_inicial_factura', None) or 1
    
    return _generate_sequence_number(Factura, Factura.numero_factura, prefix, initial)

def generate_draft_number():
    """Genera el número correlativo provisional para los Borradores de Factura."""
    year = datetime.now().year
    # Usamos el formato estandarizado de tus series: BORR seguido del año acortado (ej: BORR26-)
    prefix = f'BORR{str(year)[-2:]}-'
    initial = 1
    
    return _generate_sequence_number(Factura, Factura.numero_factura, prefix, initial)

def generate_rectificative_number():
    """Nueva función para automatizar las Facturas Rectificativas."""
    year = datetime.now().year
    configuracion = Configuracion.query.first()
    
    prefix = configuracion.serie_rectificativa if configuracion and configuracion.serie_rectificativa else f'R{str(year)[-2:]}-'
    initial = getattr(configuracion, 'numero_inicial_rectificativa', None) or 1
    
    return _generate_sequence_number(Factura, Factura.numero_factura, prefix, initial)


def generate_budget_number():
    """Genera el número correlativo para Presupuestos."""
    year = datetime.now().year
    configuracion = Configuracion.query.first()
    
    # Automatizado también con la tabla de configuración si existe
    prefix = configuracion.serie_presupuesto if configuracion and configuracion.serie_presupuesto else f'PR-{year}-'
    initial = getattr(configuracion, 'numero_inicial_presupuesto', None) or 1
    
    return _generate_sequence_number(Presupuesto, Presupuesto.numero_presupuesto, prefix, initial)


def generate_delivery_note_number():
    """Genera el número correlativo para Albaranes."""
    year = datetime.now().year
    configuracion = Configuracion.query.first()
    
    prefix = configuracion.serie_albaran if configuracion and configuracion.serie_albaran else f'ALB{str(year)[-2:]}-'
    initial = getattr(configuracion, 'numero_inicial_albaran', None) or 1
    
    return _generate_sequence_number(Albaran, Albaran.numero_albaran, prefix, initial)

def generate_product_code():
    """Genera el siguiente código secuencial entero formateado con ceros a la izquierda (ej. 009)."""
    from models import Producto
    
    # Obtenemos todos los códigos actuales para evaluar cuál es el número más alto
    todos_los_codigos = Producto.query.values(Producto.codigo)
    
    max_num = 0
    for (codigo,) in todos_los_codigos:
        if codigo and codigo.isdigit():
            num = int(codigo)
            if num > max_num:
                max_num = num
                
    # Le sumamos 1 al máximo encontrado y lo formateamos a 3 dígitos con ceros a la izquierda
    return f"{max_num + 1:03d}"

