"""
Tests de integración para VerifactuXmlBuilder (verifactu_xml.py)
=================================================================
Cubre dos aspectos que los tests unitarios no alcanzan:

  1. Validación estricta del XML contra el XSD oficial de la AEAT.
  2. Integridad de la cadena criptográfica de huellas (inmutabilidad).

Requisitos:
    pip install lxml

Uso:
    python tests/test_verifactu_integracion.py
    python tests/test_verifactu_integracion.py --xsd tests/xsd/SuministroLR.xsd
"""

import argparse
import hashlib
import sys
import os
import unittest
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from unittest.mock import MagicMock
import pytest
# ---------------------------------------------------------------------------
# Path al proyecto
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.verifactu_xml import VerifactuXmlBuilder  # noqa: E402

# ---------------------------------------------------------------------------
# Namespaces oficiales (para navegar el XML generado en los tests)
# ---------------------------------------------------------------------------
NS_LR = "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroLR.xsd"
NS_SI = "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroInformacion.xsd"


def _find(root: ET.Element, *tags: str) -> Optional[ET.Element]:
    """
    Navega el árbol XML con namespaces usando una secuencia de etiquetas.
    Prueba NS_LR primero y luego NS_SI en cada nivel.
    """
    node: ET.Element = root
    for tag in tags:
        found = node.find(f"{{{NS_LR}}}{tag}")
        if found is None:
            found = node.find(f"{{{NS_SI}}}{tag}")
        if found is None:
            return None
        node = found
    return node


def _findtext(root: ET.Element, *tags: str) -> Optional[str]:
    node = _find(root, *tags)
    return node.text if node is not None else None


# ---------------------------------------------------------------------------
# MOCKS
# ---------------------------------------------------------------------------

def _make_config(nombre: str = "Empresa Demo S.L.", nif: str = "B12345678") -> MagicMock:
    cfg = MagicMock()
    cfg.nombre_empresa = nombre
    cfg.cif_nif = nif
    return cfg


def _make_contacto(nombre: str = "Cliente Ejemplo S.A.", nif: str = "A98765432") -> MagicMock:
    c = MagicMock()
    c.nombre_fiscal = nombre
    c.numero_documento = nif
    return c


def _make_linea(subtotal: float, porcentaje_iva: float = 21.0) -> MagicMock:
    ln = MagicMock()
    ln.descripcion = "Servicio"
    ln.cantidad = 1
    ln.precio_unitario = subtotal
    ln.subtotal_linea = subtotal
    ln.impuesto_tipo = "IVA"
    ln.porcentaje_iva = porcentaje_iva
    return ln


def _make_factura(numero: str, total: float, subtotal: float = 0.0) -> MagicMock:
    f = MagicMock()
    f.numero_factura = numero
    f.fecha_factura  = date(2024, 6, 14)
    f.tipo_factura   = "Ordinaria"
    f.total_factura  = Decimal(str(total))
    f.contacto       = _make_contacto()
    base             = Decimal(str(subtotal)) if subtotal else Decimal(str(total)) / Decimal("1.21")
    base             = base.quantize(Decimal("0.01"))
    cuota            = (base * Decimal("0.21")).quantize(Decimal("0.01"))
    f.total_cuota_iva      = cuota
    f.total_base_imponible = base
    f.lineas = [_make_linea(float(base))]
    return f


# ---------------------------------------------------------------------------
# HELPER: SHA-256 del XML generado
# ---------------------------------------------------------------------------

def _huella_sha256(xml_bytes: bytes) -> str:
    return hashlib.sha256(xml_bytes).hexdigest()


# ============================================================================
# 1 · VALIDACIÓN XSD
# ============================================================================

XSD_PATH: Optional[str] = None


class TestValidacionXSD(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        try:
            from lxml import etree as _etree  # noqa: F401
            cls.lxml_disponible = True
        except ImportError:
            cls.lxml_disponible = False

    def _validar(self, xml_bytes: bytes, xsd_path: str) -> tuple[bool, str]:
        from lxml import etree
        root = etree.fromstring(xml_bytes)
        # Buscar el contenido dentro del Body de SOAP si existe
        body = root.find(".//{http://schemas.xmlsoap.org/soap/envelope/}Body")
        if body is not None:
            # Validamos el primer elemento hijo dentro del Body
            xml_doc = body.getchildren()[0]
        else:
            xml_doc = root
            
        xsd_doc = etree.parse(xsd_path)
        schema = etree.XMLSchema(xsd_doc)
        valido = schema.validate(xml_doc)
        errores = "\n".join(str(e) for e in schema.error_log)
        return valido, errores

    def test_xml_valido_contra_xsd(self) -> None:
        if not self.lxml_disponible:
            self.skipTest("lxml no instalado — ejecuta: pip install lxml")
        if not XSD_PATH:
            self.skipTest(
                "XSD no proporcionado. Pasa --xsd <ruta> para activar este test.\n"
                "Descarga: https://github.com/hectorsipe/aeat-verifactu"
            )
        config  = _make_config()
        factura = _make_factura("2024/001", 1210.00, 1000.00)
        xml_b   = VerifactuXmlBuilder.construir_xml_alta(
            factura       = factura,
            config        = config,
            hash_actual   = "a" * 64,
            hash_anterior = None,
            fecha_registro = datetime(2024, 6, 14, 12, 0, 0),
            es_primer_registro = True
        )
        # --- BLOQUE DE DEPURACIÓN ---
        root = ET.fromstring(xml_b)
        cabecera = root.find(f"{{{NS_LR}}}Cabecera")
        if cabecera is not None:
            print("\n--- ESTRUCTURA DE CABECERA GENERADA ---")
            for child in cabecera:
                print(f"Etiqueta encontrada: {child.tag}")
        print("----------------------------------------\n")
        
        valido, errores = self._validar(xml_b, XSD_PATH)
        self.assertTrue(
            valido,
            f"El XML NO es válido según el XSD oficial.\n\nErrores:\n{errores}",
        )

    def test_xml_invalido_detectado_por_xsd(self) -> None:
        if not self.lxml_disponible:
            self.skipTest("lxml no instalado")
        if not XSD_PATH:
            self.skipTest("XSD no proporcionado")
        from lxml import etree
        xml_roto = b"<NodoInventado><Hijo>dato</Hijo></NodoInventado>"
        xsd_doc  = etree.parse(XSD_PATH)
        schema   = etree.XMLSchema(xsd_doc)
        valido   = schema.validate(etree.fromstring(xml_roto))
        self.assertFalse(valido, "El validador debería rechazar un XML con nodo raíz incorrecto")


# ============================================================================
# 2 · CADENA CRIPTOGRÁFICA / INMUTABILIDAD
# ============================================================================

class TestCadenaCriptografica(unittest.TestCase):

    CONFIG = _make_config()

    def _generar_y_hashear(
        self,
        numero: str,
        total: float,
        hash_anterior: Optional[str] = None,
        factura_anterior: Optional[MagicMock] = None,
    ) -> tuple[bytes, str, MagicMock]:
        factura   = _make_factura(numero, total)
        fixed_now = datetime(2024, 6, 14, 12, 0, 0)
        # Replicamos exactamente cómo lo calcula verifactu_service.py:
        # es_primer_registro depende únicamente de si hay hash_anterior.
        es_primer_registro = not hash_anterior
        xml_bytes = VerifactuXmlBuilder.construir_xml_alta(
            factura             = factura,
            config              = self.CONFIG,
            hash_actual         = "PENDIENTE",
            es_primer_registro  = es_primer_registro,
            hash_anterior       = hash_anterior,
            factura_anterior    = factura_anterior,
            fecha_registro      = fixed_now,
        )
        return xml_bytes, _huella_sha256(xml_bytes), factura

    # ------------------------------------------------------------------
    # 2a. La huella de F1 aparece en el XML de F2
    # ------------------------------------------------------------------

    def test_huella_f1_referenciada_en_f2(self) -> None:
        _, huella_f1, factura_1 = self._generar_y_hashear("2024/001", 1210.00)

        factura_2 = _make_factura("2024/002", 605.00)
        xml_f2    = VerifactuXmlBuilder.construir_xml_alta(
            factura             = factura_2,
            config              = self.CONFIG,
            hash_actual         = "PENDIENTE",
            es_primer_registro  = False,
            hash_anterior       = huella_f1,
            factura_anterior    = factura_1,
        )
        root = ET.fromstring(xml_f2)
        # Definimos los namespaces para VeriFactu
        namespaces = {
            'sf': "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroInformacion.xsd"
        }
        
        # Buscamos la huella usando el prefijo de forma segura
        huella_nodo = root.find(".//sf:RegistroAnterior/sf:Huella", namespaces)
        huella_en_xml = huella_nodo.text if huella_nodo is not None else None

        self.assertEqual(
            huella_en_xml, huella_f1.upper() if huella_f1 else None,
            "La Huella del encadenamiento de F2 no coincide con la huella de F1",
        )

        

    # ------------------------------------------------------------------
    # 2b. Determinismo
    # ------------------------------------------------------------------

    def test_mismo_input_mismo_hash(self) -> None:
        _, h1, _ = self._generar_y_hashear("2024/001", 1210.00)
        _, h2, _ = self._generar_y_hashear("2024/001", 1210.00)
        self.assertEqual(h1, h2)

    # ------------------------------------------------------------------
    # 2c. Efecto avalancha
    # ------------------------------------------------------------------

    def test_cambio_minimo_cambia_hash_completamente(self) -> None:
        _, hash_orig, _ = self._generar_y_hashear("2024/001", 1210.00)
        _, hash_mod, _  = self._generar_y_hashear("2024/001", 1210.01)
        self.assertNotEqual(hash_orig, hash_mod)
        bits_distintos = bin(int(hash_orig, 16) ^ int(hash_mod, 16)).count("1")
        self.assertGreater(bits_distintos, 100)

    # ------------------------------------------------------------------
    # 2d. Modificar F1 rompe F2 y F3
    # ------------------------------------------------------------------

    def test_modificacion_f1_rompe_cadena(self) -> None:
        _, huella_f1_orig, factura_f1_orig = self._generar_y_hashear("2024/001", 1210.00)
        _, huella_f2_orig, factura_f2_orig = self._generar_y_hashear(
            "2024/002", 605.00, huella_f1_orig, factura_f1_orig
        )
        _, huella_f3_orig, _ = self._generar_y_hashear(
            "2024/003", 242.00, huella_f2_orig, factura_f2_orig
        )

        _, huella_f1_fraud, factura_f1_fraud = self._generar_y_hashear("2024/001", 1209.99)
        self.assertNotEqual(huella_f1_fraud, huella_f1_orig)

        _, huella_f2_fraud, factura_f2_fraud = self._generar_y_hashear(
            "2024/002", 605.00, huella_f1_fraud, factura_f1_fraud
        )
        _, huella_f3_fraud, _ = self._generar_y_hashear(
            "2024/003", 242.00, huella_f2_fraud, factura_f2_fraud
        )

        self.assertNotEqual(huella_f2_fraud, huella_f2_orig)
        self.assertNotEqual(huella_f3_fraud, huella_f3_orig)

    # ------------------------------------------------------------------
    # 2e. Primera factura: PrimerRegistro=S, sin EncadenamientoFacturaAnterior
    # ------------------------------------------------------------------

    def test_primera_factura_sin_huella_anterior(self) -> None:
        xml_f1, _, _ = self._generar_y_hashear("2024/001", 1210.00, hash_anterior=None)
        root = ET.fromstring(xml_f1)
    
        # Definimos el namespace requerido para la etiqueta
        namespaces = {
            'sf': "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroInformacion.xsd"
        }
        
        # Buscamos el nodo de manera directa en el árbol
        primer_registro_nodo = root.find(".//sf:PrimerRegistro", namespaces)
        primer_registro = primer_registro_nodo.text if primer_registro_nodo is not None else None

        self.assertEqual(primer_registro, "S",
                         "La primera factura debe tener PrimerRegistro=S")


    # ------------------------------------------------------------------
    # 2f. Cadena de 10 facturas consistente
    # ------------------------------------------------------------------

    def test_cadena_larga_consistente(self) -> None:
        """Genera 10 facturas en cadena y verifica que cada huella referencia a la anterior."""
        huella_anterior: Optional[str] = None
        factura_anterior_obj: Optional[MagicMock] = None

        for i in range(1, 11):
            numero  = f"2024/{i:03d}"
            total   = 1000.00 + i
            factura = _make_factura(numero, total)
            xml_b   = VerifactuXmlBuilder.construir_xml_alta(
                factura             = factura,
                config              = self.CONFIG,
                hash_actual         = "PENDIENTE",
                es_primer_registro  = (huella_anterior is None),
                hash_anterior       = huella_anterior,
                factura_anterior    = factura_anterior_obj,
            )
            root = ET.fromstring(xml_b)

            if huella_anterior is None:
                # Definimos los mismos namespaces que usa el builder
                namespaces = {
                    'sf': "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroInformacion.xsd"
                }
                
                # Buscamos directamente el nodo usando el prefijo sf con la sintaxis .//
                primer_reg_nodo = root.find(".//sf:PrimerRegistro", namespaces)
                primer_reg = primer_reg_nodo.text if primer_reg_nodo is not None else None

                self.assertEqual(primer_reg, "S",
                                f"Factura {numero}: primera debe tener PrimerRegistro=S")
            else:
                # Definimos los namespaces necesarios
                namespaces = {
                    'sf': "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroInformacion.xsd"
                }
                
                # Buscamos el nodo <sf:Huella> en cualquier parte del árbol de forma segura
                huella_nodo = root.find(".//sf:RegistroAnterior/sf:Huella", namespaces)
                huella_en_xml = huella_nodo.text if huella_nodo is not None else None

                self.assertEqual(
                    huella_en_xml, huella_anterior.upper() if huella_anterior else None,
                    f"Factura {numero}: Huella no coincide con la factura anterior",
                )

            huella_anterior = _huella_sha256(xml_b)
            factura_anterior_obj = factura


# ============================================================================
# 3 · GUARDA DE INTEGRIDAD: hash_anterior sin factura_anterior debe abortar
# ============================================================================

class TestGuardaIntegridadCadena(unittest.TestCase):
    """
    Verifica que construir_xml_alta protege la integridad de la cadena en
    AMBAS direcciones de la inconsistencia entre es_primer_registro y
    hash_anterior/factura_anterior:

      1. es_primer_registro=False pero faltan hash_anterior/factura_anterior
         -> ValueError (ya existía).
      2. es_primer_registro=True pero SÍ hay un hash_anterior real
         -> ValueError (cierre añadido: sin esto, el código ignoraría el
            hash_anterior en silencio y falsificaría la cadena marcando
            como génesis un registro que no lo es).
    """

    CONFIG = _make_config()

    def test_no_primer_registro_sin_hash_anterior_lanza_excepcion(self) -> None:
        factura = _make_factura("2024/002", 605.00)
        with self.assertRaises(ValueError):
            VerifactuXmlBuilder.construir_xml_alta(
                factura             = factura,
                config              = self.CONFIG,
                hash_actual         = "PENDIENTE",
                es_primer_registro  = False,
                hash_anterior       = None,
                factura_anterior    = None,
            )

    def test_no_primer_registro_sin_factura_anterior_lanza_excepcion(self) -> None:
        factura = _make_factura("2024/002", 605.00)
        with self.assertRaises(ValueError):
            VerifactuXmlBuilder.construir_xml_alta(
                factura             = factura,
                config              = self.CONFIG,
                hash_actual         = "PENDIENTE",
                es_primer_registro  = False,
                hash_anterior       = "a" * 64,   # presente...
                factura_anterior    = None,        # ...pero sin la factura que lo respalda
            )

    def test_primer_registro_con_hash_anterior_real_lanza_excepcion(self) -> None:
        """
        Dirección que el flag explícito dejaba sin proteger: si declaras
        es_primer_registro=True pero aportas un hash_anterior real, eso es
        una inconsistencia y debe abortar — no ignorar el hash en silencio.
        """
        factura_1 = _make_factura("2024/001", 1210.00)
        factura_2 = _make_factura("2024/002", 605.00)
        with self.assertRaises(ValueError):
            VerifactuXmlBuilder.construir_xml_alta(
                factura             = factura_2,
                config              = self.CONFIG,
                hash_actual         = "PENDIENTE",
                es_primer_registro  = True,        # dice que es el primero...
                hash_anterior       = "a" * 64,    # ...pero aporta un hash_anterior real
                factura_anterior    = factura_1,
            )

    def test_primer_registro_legitimo_no_lanza_excepcion(self) -> None:
        """Caso legítimo de primer registro: no debe lanzar nada."""
        factura = _make_factura("2024/001", 1210.00)
        try:
            VerifactuXmlBuilder.construir_xml_alta(
                factura             = factura,
                config              = self.CONFIG,
                hash_actual         = "PENDIENTE",
                es_primer_registro  = True,
                hash_anterior       = None,
                factura_anterior    = None,
            )
        except ValueError:
            self.fail(
                "No debería lanzarse ValueError para un primer registro "
                "legítimo (es_primer_registro=True, sin hash_anterior)."
            )

    def test_encadenamiento_legitimo_no_lanza_excepcion(self) -> None:
        """Caso legítimo de encadenamiento completo: no debe lanzar nada."""
        factura_1 = _make_factura("2024/001", 1210.00)
        factura_2 = _make_factura("2024/002", 605.00)
        try:
            VerifactuXmlBuilder.construir_xml_alta(
                factura             = factura_2,
                config              = self.CONFIG,
                hash_actual         = "PENDIENTE",
                es_primer_registro  = False,
                hash_anterior       = "a" * 64,
                factura_anterior    = factura_1,
            )
        except ValueError:
            self.fail(
                "No debería lanzarse ValueError cuando es_primer_registro=False "
                "y se aportan correctamente hash_anterior y factura_anterior."
            )


# ============================================================================
# PUNTO DE ENTRADA
# ============================================================================

def _parse_args() -> None:
    global XSD_PATH
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--xsd", default=None)
    args, remaining = parser.parse_known_args()
    XSD_PATH = args.xsd
    sys.argv  = [sys.argv[0]] + remaining

@pytest.fixture(autouse=True)
def setup_xsd_path(request):
    global XSD_PATH
    if XSD_PATH is None:
        XSD_PATH = request.config.getoption("--xsd")


if __name__ == "__main__":
    _parse_args()
    unittest.main(verbosity=2)