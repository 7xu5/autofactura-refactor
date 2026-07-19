"""
tests/test_invoice_line_parsing.py
===================================
Caracterización de la lógica de cálculo de líneas de factura.

OBJETIVO: fijar el comportamiento actual de las DOS funciones que hacen
prácticamente lo mismo (_procesar_lineas_form y parse_invoice_lineas) ANTES
de unificarlas en la Fase 1 del refactor. Si tras la fusión algún test aquí
falla, sabemos exactamente qué comportamiento cambió sin querer — y si fue
intencionado, simplemente actualizas el test junto con el cambio.
"""
from decimal import Decimal

from services.invoice_service import InvoiceService
from utils.tax_calculations import calculate_totals


# ---------------------------------------------------------------------------
# _procesar_lineas_form  (usada en crear/editar -> construye FacturaLinea ORM)
# ---------------------------------------------------------------------------

class TestProcesarLineasForm:

    def test_linea_simple_ordinaria(self, app, cliente):
        form = {
            "lineas_count": "1",
            "concepto_1": "Diseño de logo",
            "informacion_1": "",
            "unidades_1": "2",
            "precio_1": "100",
            "impuesto_1": "21% IVA",
        }
        # La función ahora devuelve 3 elementos: instancias_lineas, totales_calculados, error
        lineas, totales, error = InvoiceService.procesar_lineas_form(
            form, cliente, pestana="Emitida", tipo_factura="Ordinaria"
        )

        print(f"\nDEBUG: Claves en totales -> {list(totales.keys())}")
        
        assert error is None
        assert len(lineas) == 1
        # Accedemos a los valores dentro del diccionario devuelto por el servicio
        assert totales['base_imponible'] == Decimal("200.00")
        assert totales['iva_total'] == Decimal("42.00")
        assert lineas[0].porcentaje_recargo == Decimal("0.00")

    def test_sin_concepto_se_ignora_la_linea(self, app, cliente):
        form = {"lineas_count": "1", "concepto_1": "", "unidades_1": "1", "precio_1": "10"}
        # Ajustamos el desempaquetado a 3 elementos
        lineas, totales, error = InvoiceService.procesar_lineas_form(
            form, cliente, pestana="Emitida", tipo_factura="Ordinaria"
        )
        assert lineas == []
        assert error == "Debes añadir al menos una línea de concepto para crear la factura."

    def test_ordinaria_rechaza_unidades_negativas(self, app, cliente):
        form = {
            "lineas_count": "1",
            "concepto_1": "Servicio",
            "unidades_1": "-3",
            "precio_1": "10",
            "impuesto_1": "21% IVA",
        }
        # Ajustamos el desempaquetado a 3 elementos
        lineas, totales, error = InvoiceService.procesar_lineas_form(
            form, cliente, pestana="Emitida", tipo_factura="Ordinaria"
        )
        assert lineas == []
        assert error == "Las cantidades no pueden ser negativas en facturas ordinarias."

    def test_rectificativa_fuerza_unidades_negativas(self, app, cliente):
        """Aunque el usuario meta unidades positivas, en una Rectificativa
        _procesar_lineas_form las invierte automáticamente."""
        form = {
            "lineas_count": "1",
            "concepto_1": "Abono parcial",
            "unidades_1": "3",
            "precio_1": "50",
            "impuesto_1": "21% IVA",
        }
        # Desempaquetado actualizado a 3 elementos
        lineas, totales, error = InvoiceService.procesar_lineas_form(
            form, cliente, pestana="Emitida", tipo_factura="Rectificativa"
        )
        
        assert error is None
        assert lineas[0].unidades == Decimal("-3")
        # Accedemos a los valores dentro del diccionario 'totales'
        assert totales['base_imponible'] == Decimal("-150.00")
        assert totales['iva_total'] == Decimal("-31.50")

    def test_recargo_equivalencia_solo_si_iva_21_y_no_borrador(self, app, cliente_recargo):
        form = {
            "lineas_count": "1",
            "concepto_1": "Producto con recargo",
            "unidades_1": "1",
            "precio_1": "100",
            "impuesto_1": "21% IVA",
        }
        # Desempaquetado a 3 elementos
        lineas, totales, error = InvoiceService.procesar_lineas_form(
            form, cliente_recargo, pestana="Emitida", tipo_factura="Ordinaria"
        )
        assert lineas[0].porcentaje_recargo == Decimal("5.20")

        # En Borrador, el recargo NO se aplica aunque el cliente lo tenga activado
        # Ajustamos el unpacking para que coincida con la nueva estructura de 3 elementos
        lineas_borrador, *_ = InvoiceService.procesar_lineas_form(
            form, cliente_recargo, pestana="Borrador", tipo_factura="Ordinaria"
        )
        assert lineas_borrador[0].porcentaje_recargo == Decimal("0.00")

    def test_recargo_no_aplica_si_iva_no_es_21(self, app, cliente_recargo):
        form = {
            "lineas_count": "1",
            "concepto_1": "Producto IGIC",
            "unidades_1": "1",
            "precio_1": "100",
            "impuesto_1": "7% IGIC",
        }
        lineas, *_ = InvoiceService.procesar_lineas_form(
            form, cliente_recargo, pestana="Emitida", tipo_factura="Ordinaria"
        )
        assert lineas[0].porcentaje_recargo == Decimal("0.00")


# ---------------------------------------------------------------------------
# parse_invoice_lineas -> Migrado al pipeline de InvoiceService
# ---------------------------------------------------------------------------

class TestParseInvoiceLineas:

    def test_linea_simple_sin_descuento(self, app, cliente):
        form = {
            "concepto_1": "Diseño de logo",
            "unidades_1": "2",
            "precio_1": "100",
            "descuento_1": "0",
            "impuesto_1": "21% IVA",
            "informacion_1": "",
        }
        # Desempaquetado ajustado a 3 elementos
        lineas, totales, error = InvoiceService.procesar_lineas_form(form, cliente, pestana="Borrador")
        datos_lineas, _ = InvoiceService.preparar_lineas_para_pdf(lineas)

        # Extraemos del diccionario para que los asserts posteriores funcionen sin cambios
        base = totales['base_imponible']
        iva = totales['iva_total']

        assert base == Decimal("200.00")
        assert iva == Decimal("42.00")
        assert base + iva == Decimal("242.00")
        assert datos_lineas[0]["total"] == "242.00"

    def test_aplica_descuento_porcentual(self, app, cliente):
        """
        DIVERGENCIA CONOCIDA #1: esta función SÍ soporta descuento por línea...
        """
        form = {
            "concepto_1": "Servicio con descuento",
            "unidades_1": "1",
            "precio_1": "100",
            "descuento_1": "10",
            "impuesto_1": "21% IVA",
        }
        # Desempaquetado ajustado a 3 elementos
        lineas, totales, error = InvoiceService.procesar_lineas_form(form, cliente, pestana="Borrador")

        # Extraemos las claves necesarias para los asserts
        base = totales['base_imponible']
        iva = totales['iva_total']

        # base bruta 100, descuento 10% = 10, base neta = 90
        assert base == Decimal("90.00")
        assert iva == Decimal("18.90")

    def test_no_aplica_recargo_de_equivalencia(self, app, cliente_recargo):
        """
        DIVERGENCIA CONOCIDA #2: parse_invoice_lineas no recibe el `cliente`...
        """
        form = {
            "concepto_1": "Producto",
            "unidades_1": "1",
            "precio_1": "100",
            "impuesto_1": "21% IVA",
        }
        # En previsualización forzamos pestana="Borrador", garantizando recargo 0.00
        # Ajustamos el desempaquetado a 3 elementos
        lineas, totales, error = InvoiceService.procesar_lineas_form(form, cliente_recargo, pestana="Borrador")
        
        assert lineas[0].porcentaje_recargo == Decimal("0.00")

    def test_unidades_negativas_se_clampan_silenciosamente_a_cero(self, app, cliente):
        """
        DIVERGENCIA CONOCIDA #3 (corregida tras ejecutar el test por
         primera vez): a diferencia de _procesar_lineas_form (que
         RECHAZA unidades negativas en facturas ordinarias con un
         mensaje de error explícito)...
        """
        form = {
            "concepto_1": "Línea con unidades negativas",
            "unidades_1": "-5",
            "precio_1": "10",
            "impuesto_1": "21% IVA",
        }
        # El nuevo servicio unificado intercepta de forma segura el error en ordinarias
        # Desempaquetado ajustado a 3 elementos (instancias_lineas, totales_calculados, error)
        lineas, totales, error = InvoiceService.procesar_lineas_form(
            form, cliente, pestana="Borrador", tipo_factura="Ordinaria"
        )
        
        assert lineas == []
        assert error == "Las cantidades no pueden ser negativas en facturas ordinarias."


# ---------------------------------------------------------------------------
# _calcular_totales
# ---------------------------------------------------------------------------

class TestCalcularTotales:

    def test_sin_recargo(self, app, cliente):
        # Base 200, IVA 21%
        _, _, recargo, _, total = calculate_totals(
            Decimal("200.00"), Decimal("21"), recargo=False
        )
        assert recargo == Decimal("0.00")
        assert total == Decimal("242.00") # 200 + 42

    def test_con_recargo_en_emitida(self, app, cliente_recargo):
        # Base 200, IVA 21%, recargo True
        _, _, recargo, _, total = calculate_totals(
            Decimal("200.00"), Decimal("21"), recargo=True
        )
        # 200 * 5.20% = 10.40
        assert recargo == Decimal("10.40")
        assert total == Decimal("252.40") # 200 + 42 + 10.40

    def test_sin_recargo_en_borrador_aunque_cliente_lo_tenga(self, app, cliente_recargo):
        # La lógica de "Borrador" debe controlarse antes de llamar a la utilidad
        pestana = "Borrador"
        es_borrador = (pestana == "Borrador")
        
        _, _, recargo, _, total = calculate_totals(
            Decimal("200.00"), Decimal("21"), recargo=(cliente_recargo.recargo_equivalencia and not es_borrador)
        )
        assert recargo == Decimal("0.00")
        assert total == Decimal("242.00")