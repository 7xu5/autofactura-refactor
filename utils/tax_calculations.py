# utils/tax_calculations.py
from decimal import Decimal, ROUND_HALF_UP

# Constante para forzar el redondeo estándar contable (mitad hacia arriba a 2 decimales)
TWOPLACES = Decimal('0.01')

def get_recargo_porcentaje(iva_percent: Decimal) -> Decimal:
    """
    Retorna el porcentaje de recargo de equivalencia correspondiente 
    al tipo de IVA aplicado en España.
    """
    if iva_percent >= Decimal('21.00'):
        return Decimal('5.20')
    elif iva_percent >= Decimal('10.00'):
        return Decimal('1.40')
    elif iva_percent >= Decimal('4.00'):
        return Decimal('0.50')
    return Decimal('0.00')

def calculate_totals(base, iva_percent, recargo=False, porcentaje_retencion=Decimal('0.00')):
    """
    Calcula de manera precisa los totales para una base imponible.
    """
    base = Decimal(base or 0)
    iva_percent = Decimal(iva_percent or 0)
    porcentaje_retencion = Decimal(porcentaje_retencion or 0)
    
    # Cálculos individuales con redondeo simétrico
    iva = (base * iva_percent / Decimal('100')).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    
    recargo_total = Decimal('0.00')
    if recargo:
        porcentaje_recargo = get_recargo_porcentaje(iva_percent)
        recargo_total = (base * porcentaje_recargo / Decimal('100')).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
        
    retencion = (base * porcentaje_retencion / Decimal('100')).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    
    total = (base + iva + recargo_total - retencion).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    
    return base, iva, recargo_total, retencion, total

def parse_impuesto_porcentaje(impuesto_text):
    """
    Parsea textos tipo '21%' o 'exento' a su representación Decimal.
    """
    impuesto_text = (impuesto_text or '').strip()
    if not impuesto_text or 'exento' in impuesto_text.lower():
        return Decimal('0')
    porcentaje_text = impuesto_text.split('%', 1)[0].strip()
    try:
        return Decimal(porcentaje_text or '0')
    except Exception:
        return Decimal('0')

def calculate_invoice_totals(lineas, recargo=False, porcentaje_retencion=Decimal('0.00')):
    """
    Calcula los totales globales de una factura sumando sus líneas de manera correcta,
    evitando discrepancias de céntimos mediante el cálculo individual por línea 
    y posterior agregación (con desglose de impuestos).
    """
    total_base = Decimal('0.00')
    total_iva = Decimal('0.00')
    total_recargo = Decimal('0.00')
    desglose_iva = {} # Para guardar bases e IVAs agrupados por tipo
    
    for linea in lineas:
        # Extraemos cantidad y precio unitario de la línea
        cantidad = Decimal(linea.get('cantidad') or 0)
        precio_unitario = Decimal(linea.get('precio_unitario') or 0)
        descuento = Decimal(linea.get('descuento') or 0) # Porcentaje
        
        # Subtotal de la línea antes de impuestos
        subtotal_linea = (cantidad * precio_unitario)
        if descuento > 0:
            subtotal_linea -= (subtotal_linea * descuento / Decimal('100'))
            
        subtotal_linea = subtotal_linea.quantize(TWOPLACES, rounding=ROUND_HALF_UP)
        
        # Tipo de IVA de la línea
        iva_linea_percent = Decimal(linea.get('iva_porcentaje') or 0)
        
        # Calculamos los impuestos de esta línea concreta
        _, iva_linea, recargo_linea, _, _ = calculate_totals(
            subtotal_linea, 
            iva_linea_percent, 
            recargo=recargo, 
            porcentaje_retencion=Decimal('0.00') # La retención se aplica sobre el total de la base de la factura, no por línea
        )
        
        total_base += subtotal_linea
        total_iva += iva_linea
        total_recargo += recargo_linea
        
        # Agrupamos en el desglose para la vista de la factura
        iva_key = str(iva_linea_percent)
        if iva_key not in desglose_iva:
            desglose_iva[iva_key] = {'base': Decimal('0.00'), 'cuota': Decimal('0.00'), 'recargo': Decimal('0.00')}
        desglose_iva[iva_key]['base'] += subtotal_linea
        desglose_iva[iva_key]['cuota'] += iva_linea
        desglose_iva[iva_key]['recargo'] += recargo_linea

    # La retención se calcula sobre el sumatorio total de las bases imponibles
    porcentaje_retencion = Decimal(porcentaje_retencion or 0)
    total_retencion = (total_base * porcentaje_retencion / Decimal('100')).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    
    # Suma final absoluta
    total_factura = (total_base + total_iva + total_recargo - total_retencion).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    
    return {
        'base_imponible': total_base,
        'iva_total': total_iva,
        'recargo_total': total_recargo,
        'retencion_total': total_retencion,
        'total': total_factura,
        'desglose': desglose_iva
    }