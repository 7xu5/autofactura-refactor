from decimal import Decimal
# Importamos la función matemática pura de tu dominio
from utils.tax_calculations import calculate_invoice_totals

def test_calculo_totales_factura_ordinaria_simple():
    """Prueba que el cálculo de IVA y totales funcione de forma aislada."""
    # 1. PREPARAMOS los datos de prueba (Simulamos una línea de servicio)
    lineas_prueba = [
        {
            'cantidad': Decimal('1'),
            'precio_unitario': Decimal('100.00'),
            'descuento': Decimal('0'),
            'iva_porcentaje': Decimal('21')
        }
    ]
    
    # 2. EJECUTAMOS la función de tu dominio
    totales = calculate_invoice_totals(
        lineas=lineas_prueba,
        recargo=False,
        porcentaje_retencion=Decimal('0')
    )
    
    # 3. VERIFICAMOS con asserts como los que tú conoces
    assert totales['base_imponible'] == Decimal('100.00')
    assert totales['iva_total'] == Decimal('21.00')
    assert totales['retencion_total'] == Decimal('0.00')
    assert totales['total'] == Decimal('121.00')


def test_calculo_totales_con_retencion_irpf():
    """Prueba que el IRPF se reste correctamente del total."""
    lineas_prueba = [
        {
            'cantidad': Decimal('2'),
            'precio_unitario': Decimal('50.00'),  # Base = 100.00
            'descuento': Decimal('0'),
            'iva_porcentaje': Decimal('21')       # IVA = 21.00
        }
    ]
    
    # Ejecutamos metiendo un 15% de IRPF (Retención)
    totales = calculate_invoice_totals(
        lineas=lineas_prueba,
        recargo=False,
        porcentaje_retencion=Decimal('15.00') # IRPF = 15.00
    )
    
    # Base (100) + IVA (21) - IRPF (15) = 106.00
    assert totales['base_imponible'] == Decimal('100.00')
    assert totales['retencion_total'] == Decimal('15.00')
    assert totales['total'] == Decimal('106.00')