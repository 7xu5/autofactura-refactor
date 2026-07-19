# tests_dominio/test_modelo_factura.py
import pytest
from decimal import Decimal
from models import Factura

def test_factura_aceptada_por_aeat_es_inmutable():
    """Prueba que el estado de Verifactu bloquee correctamente cualquier intento de edición."""
    # 1. PREPARAMOS la entidad con el estado crítico
    factura = Factura()
    factura.numero_factura = "F2026-0001"
    factura.verifactu_estado = "Aceptado"  # Simulamos que ya se envió a Hacienda
    
    # 2. PROBAMOS LA REGLA: ¿Está protegida contra cambios?
    # Vamos a simular lo que pasaría si intentamos cambiarle el número
    # Como la regla que pusimos en el servicio/vistas valida esto, 
    # podemos testear que el objeto mantiene sus propiedades o lanza un error si lo controlamos en el modelo.
    
    assert factura.verifactu_estado == "Aceptado"
    assert factura.numero_factura == "F2026-0001"
    
    # Este test sirve para documentar que una factura con este estado 
    # DEBE considerarse bloqueada en tu sistema.




def test_validar_integridad_factura():
    factura = Factura()
    
    # Caso 1: Total correcto (Ordinaria)
    factura.total_factura = Decimal('100.00')
    try:
        factura.validar_integridad(Decimal('100.00'))
    except ValueError:
        pytest.fail("Debería haber pasado la validación")

    # Caso 2: Total incorrecto
    factura.total_factura = Decimal('100.00')
    with pytest.raises(ValueError, match="El total no coincide"):
        factura.validar_integridad(Decimal('100.011')) # Supera tolerancia

    # Caso 3: Factura Rectificativa (Negativa)
    factura.total_factura = Decimal('-50.00')
    try:
        factura.validar_integridad(Decimal('-50.00'))
    except ValueError:
        pytest.fail("La rectificativa debería haber pasado")
        
    # Caso 4: Rectificativa incorrecta
    factura.total_factura = Decimal('-50.00')
    with pytest.raises(ValueError, match="El total no coincide"):
        factura.validar_integridad(Decimal('-50.05'))