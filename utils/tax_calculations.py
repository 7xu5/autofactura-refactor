from decimal import Decimal

def calculate_totals(base, iva_percent, recargo=False, porcentaje_retencion=Decimal('0.00')):
    base = Decimal(base or 0)
    iva = (base * Decimal(iva_percent) / Decimal('100')).quantize(Decimal('0.01'))
    recargo_total = Decimal('0.00')
    if recargo:
        recargo_total = (base * Decimal('5.20') / Decimal('100')).quantize(Decimal('0.01'))
    retencion = (base * porcentaje_retencion / Decimal('100')).quantize(Decimal('0.01'))
    total = (base + iva + recargo_total - retencion).quantize(Decimal('0.01'))
    return base, iva, recargo_total, retencion, total

def parse_impuesto_porcentaje(impuesto_text):
    impuesto_text = (impuesto_text or '').strip()
    if not impuesto_text or 'exento' in impuesto_text.lower():
        return Decimal('0')
    porcentaje_text = impuesto_text.split('%', 1)[0].strip()
    try:
        return Decimal(porcentaje_text or '0')
    except Exception:
        return Decimal('0')