import sys
# Esto fuerza a que Python recargue los módulos desde cero en cada ejecución
if 'utils.tax_calculations' in sys.modules:
    del sys.modules['utils.tax_calculations']
import utils.tax_calculations
print(f"DEBUG RUTA: {utils.tax_calculations.__file__}")

from decimal import Decimal
from utils.tax_calculations import calculate_invoice_totals
# Suponiendo que tienes una función similar a esta o que calculas los cambios
from utils.tax_calculations import calculate_totals # Importa la función interna
_, iva_calc, _, _, _ = calculate_totals(Decimal('-100.00'), Decimal('21'), False, Decimal('0'))
print(f"DEBUG - IVA calculado: {iva_calc}")

def test_rectificativa_invierte_signos_de_importes():
    # 1. ARRANGE (Preparar): Creamos los datos de una factura ordinaria (positivos)
    linea_positiva = [
        {
            'cantidad': Decimal('1'),
            'precio_unitario': Decimal('100.00'),
            'descuento': Decimal('0'),
            'iva_porcentaje': Decimal('21')
        }
    ]
    
    # 2. ACT (Actuar): Simulamos la conversión a rectificativa (negativización)
    # Aquí multiplicamos por -1 para representar lo que hace tu servicio de facturación
    linea_rectificativa = [
        {k: (v * Decimal('-1') if k == 'cantidad' else v) 
        for k, v in linea.items()}
        for linea in linea_positiva
    ]
    
    # Calculamos los totales sobre esa línea negativa
    totales = calculate_invoice_totals(
        lineas=linea_rectificativa, 
        recargo=False, 
        porcentaje_retencion=Decimal('0')
    )

    print(f"DEBUG FINAL - total en diccionario: {totales['total']}")
    print(f"DEBUG FINAL - base en diccionario: {totales['base_imponible']}")
    
    # 3. ASSERT (Afirmar): Comprobamos que el resultado es negativo
    assert totales['total'] == Decimal('-121.00')
    assert totales['base_imponible'] == Decimal('-100.00')
    assert totales['iva_total'] == Decimal('-21.00')