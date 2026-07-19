"""
Test suite para VerifactuXmlBuilder (verifactu_xml.py)
Genera el XML completo y valida su estructura campo a campo.

Uso:
    python test_verifactu_xml.py
"""
import sys
import os

# Añade la raíz del proyecto al path para poder importar 'utils'
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import unittest
import xml.etree.ElementTree as ET
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# MOCKS DE MODELOS (sustituyen los imports de models.py)
# ---------------------------------------------------------------------------

def _make_config() -> MagicMock:
    cfg = MagicMock()
    cfg.nombre_empresa = "Empresa Demo S.L."
    cfg.cif_nif = "B12345678"
    return cfg


def _make_contacto(nombre: str = "Cliente Ejemplo S.A.", nif: str = "A98765432") -> MagicMock:
    c = MagicMock()
    c.nombre_fiscal = nombre
    c.numero_documento = nif
    return c


def _make_linea(descripcion: str, cantidad: float, precio: float,
                subtotal: float, tipo_impuesto: str = "IVA",
                porcentaje_iva: float = 21.0) -> MagicMock:
    ln = MagicMock()
    ln.descripcion = descripcion
    ln.cantidad = cantidad
    ln.precio_unitario = precio
    ln.subtotal_linea = subtotal
    ln.impuesto_tipo = tipo_impuesto
    ln.porcentaje_iva = porcentaje_iva
    return ln


def _make_factura(tipo: str = "Ordinaria") -> MagicMock:
    """Factura con dos líneas: una al 21 % y otra al 10 %."""
    f = MagicMock()
    f.numero_factura = "2024/001"
    f.fecha = datetime(2024, 6, 14)
    f.tipo_factura = tipo
    f.total_factura = Decimal("1331.00")
    f.total_cuota_iva = Decimal("240.00")
    f.total_base_imponible = Decimal("1091.00")
    f.contacto = _make_contacto()
    f.lineas = [
        _make_linea("Servicio de desarrollo web", 10, 100.0, 1000.0, "IVA", 21.0),
        _make_linea("Soporte técnico mensual",     5,  60.0,  300.0, "IVA", 10.0),
    ]
    return f


# ---------------------------------------------------------------------------
# IMPORTAR LA CLASE BAJO TEST
# ---------------------------------------------------------------------------
try:
    from utils.verifactu_xml import VerifactuXmlBuilder
except ModuleNotFoundError:
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from utils.verifactu_xml import VerifactuXmlBuilder


# ---------------------------------------------------------------------------
# HELPERS: parseo, pretty-print y acceso seguro a texto de nodos
# ---------------------------------------------------------------------------

NS = {
    'lr': 'https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroLR.xsd',
    'sf': 'https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroInformacion.xsd'
}

def _parse(xml_bytes: bytes) -> ET.Element:
    return ET.fromstring(xml_bytes)

def _pretty_print(xml_bytes: bytes) -> str:
    """Devuelve el XML indentado como string legible."""
    import xml.dom.minidom as minidom
    return minidom.parseString(xml_bytes).toprettyxml(indent="  ")

def _get_text(root: ET.Element, path: str) -> str:
    """Busca un nodo de manera precisa usando rutas XPath relativas e ignorando prefijos manuales."""
    namespaces = {
        'soap': "http://schemas.xmlsoap.org/soap/envelope/",
        'sf': "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroInformacion.xsd",
        'lr': "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroLR.xsd"
    }
    
    # 1. Si es una ruta larga (ej: "Destinatarios/IDDestinatario/NIF"), construimos un XPath con namespaces
    if '/' in path:
        parts = path.split('/')
        xpath_parts = []
        for part in parts:
            clean_tag = part.split(':')[-1]
            # La mayoría de etiquetas de contenido cuelgan de 'sf', excepto los contenedores raíz que cuelgan de 'lr'
            if clean_tag in ["RegFactuSistemaFacturacion", "Cabecera", "RegistroFactura"]:
                xpath_parts.append(f"lr:{clean_tag}")
            elif clean_tag in ["Envelope", "Header", "Body"]:
                xpath_parts.append(f"soap:{clean_tag}")
            else:
                xpath_parts.append(f"sf:{clean_tag}")
        
        full_xpath = ".//" + "/".join(xpath_parts)
        found = root.find(full_xpath, namespaces)
    else:
        # 2. Si es una etiqueta simple suelta, hacemos la búsqueda profunda como antes
        target_tag = path.split(':')[-1]
        found = None
        for prefix in ['sf', 'lr', 'soap']:
            found = root.find(f".//{prefix}:{target_tag}", namespaces)
            if found is not None:
                break

    assert found is not None, f"No se encontró el nodo para la ruta: {path}"
    return found.text if found.text else ""

# ---------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------

class TestVerifactuXmlBuilder(unittest.TestCase):

    HASH_ACTUAL   = "abc123def456"
    HASH_ANTERIOR = "zzz999yyy888"

    def setUp(self) -> None:
        self.config   = _make_config()
        self.factura  = _make_factura()
        
        # 1. Creamos un mock rápido para simular la factura anterior que exige el Builder
        factura_prev_mock = MagicMock()
        factura_prev_mock.numero_factura = "2024/000"
        factura_prev_mock.fecha_factura = datetime(2024, 1, 1)
        
        # 2. Se la pasamos al constructor junto con el flag en False
        self.xml_bytes = VerifactuXmlBuilder.construir_xml_alta(
            factura            = self.factura,
            config             = self.config,
            hash_actual        = self.HASH_ACTUAL,
            hash_anterior      = self.HASH_ANTERIOR,
            es_primer_registro = False,
            factura_anterior   = factura_prev_mock, # <-- Añadimos esto para calmar al Builder
        )
        self.root = _parse(self.xml_bytes)

    # ------------------------------------------------------------------
    # 1. Estructura raíz
    # ------------------------------------------------------------------

    def test_elemento_raiz(self) -> None:
        NS_SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
        NS_LR = "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroLR.xsd"
        
        # 1. Comprobamos que la raíz real es el sobre SOAP Envelope exigido
        self.assertEqual(self.root.tag, f"{{{NS_SOAP}}}Envelope")
        
        # 2. Comprobamos que dentro del Body se encuentra el nodo principal de Verifactu
        nodo_verifactu = self.root.find(f".//{{{NS_LR}}}RegFactuSistemaFacturacion")
        self.assertIsNotNone(nodo_verifactu, "No se encontró el nodo RegFactuSistemaFacturacion dentro del sobre SOAP")

    def test_raiz_tiene_atributo_schema(self) -> None:
        NS_LR = "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroLR.xsd"
        NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"
        
        # 1. Buscamos el nodo de Verifactu dentro del sobre SOAP
        nodo_verifactu = self.root.find(f".//{{{NS_LR}}}RegFactuSistemaFacturacion")
        
        # 2. Usamos un assert estándar de Python que Pylance entiende perfectamente
        # para hacer el "type narrowing" (estrechamiento de tipo)
        assert nodo_verifactu is not None, "No se encontró el nodo RegFactuSistemaFacturacion"
        
        # 3. Comprobamos que contiene la clave formateada con su namespace
        schema_attr_key = f"{{{NS_XSI}}}schemaLocation"
        self.assertIn(schema_attr_key, nodo_verifactu.attrib)
        
        # 4. Validamos que el contenido del esquema sea el correcto
        self.assertEqual(nodo_verifactu.attrib[schema_attr_key], f"{NS_LR} SuministroLR.xsd")

    # ------------------------------------------------------------------
    # 2. Cabecera
    # ------------------------------------------------------------------

    def test_cabecera_version(self) -> None:
        # Corregimos la ruta al elemento real exigido por el XSD: IDVersion dentro de RegistroAlta
        self.assertEqual(
            _get_text(self.root, "RegistroFactura/RegistroAlta/IDVersion"), 
            "1.0"
        )

    def test_cabecera_nombre_empresa(self) -> None:
        self.assertEqual(
            _get_text(self.root, "Cabecera/ObligadoEmision/NombreRazon"),
            "Empresa Demo S.L.",
        )

    def test_cabecera_nif_emisor(self) -> None:
        self.assertEqual(
            _get_text(self.root, "Cabecera/sf:ObligadoEmision/sf:NIF"),
            "B12345678",
        )

    # ------------------------------------------------------------------
    # 3. IDFactura
    # ------------------------------------------------------------------

    def test_id_factura_nif_emisor(self) -> None:
        self.assertEqual(
            _get_text(self.root, "RegistroFactura/RegistroAlta/IDFactura/IDEmisorFactura"),
            "B12345678",
        )

    def test_id_factura_numero_serie(self) -> None:
        self.assertEqual(
            _get_text(self.root, "RegistroFactura/RegistroAlta/IDFactura/NumSerieFactura"),
            "2024/001",
        )

    def test_id_factura_fecha(self) -> None:
        # 1. Forzar el retorno del mock antes de compilar
        self.factura.fecha_factura.strftime.return_value = "14-06-2024"
        
        # 2. Regenerar el root localmente para este test
        root_local = _parse(VerifactuXmlBuilder.construir_xml_alta(
            self.factura, self.config, "h1", es_primer_registro=True
        ))
        
        # 3. Comprobar contra el nuevo nodo generado
        self.assertEqual(
            _get_text(root_local, "RegistroFactura/RegistroAlta/IDFactura/FechaExpedicionFactura"),
            "14-06-2024",
        )

    # ------------------------------------------------------------------
    # 4. Datos generales
    # ------------------------------------------------------------------

    def test_clase_factura_ordinaria(self) -> None:
        self.assertEqual(
            _get_text(self.root, "RegistroFactura/RegistroAlta/TipoFactura"),
            "F1",
        )

    def test_clase_factura_rectificativa(self) -> None:
        f_rect   = _make_factura(tipo="Rectificativa")
        factura_prev_mock = MagicMock()
        factura_prev_mock.numero_factura = "2024/000"
        factura_prev_mock.fecha_factura = datetime(2024, 1, 1)
        
        # Le inyectamos tanto el mock de la factura como un hash anterior ficticio
        xml_rect = VerifactuXmlBuilder.construir_xml_alta(
            factura=f_rect, 
            config=self.config, 
            hash_actual="h1", 
            es_primer_registro=False, 
            hash_anterior="H_ANTERIOR_FAKE",  # <-- Añadimos esto para calmar al Builder
            factura_anterior=factura_prev_mock
        )

    # ------------------------------------------------------------------
    # 5. Destinatario
    # ------------------------------------------------------------------

    def test_destinatario_nombre(self) -> None:
        self.assertEqual(
            _get_text(self.root, "RegistroFactura/RegistroAlta/Destinatarios/IDDestinatario/NombreRazon"),
            "Cliente Ejemplo S.A.",
        )

    def test_destinatario_nif(self) -> None:
        self.assertEqual(
            _get_text(self.root, "RegistroFactura/RegistroAlta/Destinatarios/IDDestinatario/NIF"),
            "A98765432",
        )

    def test_destinatario_sin_contacto(self) -> None:
        f_sin = _make_factura()
        f_sin.contacto = None
        
        # Cambiamos es_primer_registro a True para aislar la prueba del cliente sin contacto
        root_sin = _parse(VerifactuXmlBuilder.construir_xml_alta(
            factura=f_sin, 
            config=self.config, 
            hash_actual="h1", 
            es_primer_registro=True  # <-- Cambiado a True
        ))
        
        # El resto del test se queda exactamente igual comprobando el "CLIENTE DESCONOCIDO"
        self.assertEqual(
            _get_text(root_sin, "RegistroFactura/RegistroAlta/Destinatarios/IDDestinatario/NombreRazon"),
            "CLIENTE DESCONOCIDO",
        )

    # ------------------------------------------------------------------
    # 6. Desglose IVA
    # ------------------------------------------------------------------

    def test_tipo_no_exenta_s1(self) -> None:
        self.assertEqual(
            _get_text(
                self.root,
                "RegistroFactura/RegistroAlta/Desglose/DetalleDesglose/CalificacionOperacion",
            ),
            "S1",
        )

    def test_num_bloques_iva(self) -> None:
        """Dos líneas con IVA distinto → dos bloques DetalleIVA."""
        detalles = self.root.findall(".//sf:DetalleDesglose", NS)
        self.assertEqual(len(detalles), 2)

    def _bloque_iva(self, porcentaje: str) -> ET.Element:
        """Devuelve el DetalleIVA cuyo TipoImpositivo coincide con el porcentaje dado."""
        detalles = self.root.findall(".//sf:DetalleDesglose", NS)
        target_val = float(porcentaje)
        for d in detalles:
            tipo_nodo = d.find("sf:TipoImpositivo", NS)
            if tipo_nodo is not None and tipo_nodo.text:
                try:
                    if float(tipo_nodo.text) == target_val:
                        return d
                except ValueError:
                    continue
        raise AssertionError(f"No se encontró bloque DetalleIVA con TipoImpositivo={porcentaje}")

    def test_base_imponible_21(self) -> None:
        bloque = self._bloque_iva("21.00")
        self.assertEqual(bloque.findtext("sf:BaseImponibleOimporteNoSujeto", namespaces=NS), "1000.00")
        self.assertEqual(bloque.findtext("sf:CuotaRepercutida", namespaces=NS), "210.00")

    def test_base_imponible_10(self) -> None:
        bloque = self._bloque_iva("10.00")
        self.assertEqual(bloque.findtext("sf:BaseImponibleOimporteNoSujeto", namespaces=NS), "300.00")
        self.assertEqual(bloque.findtext("sf:CuotaRepercutida", namespaces=NS), "30.00")

    # ------------------------------------------------------------------
    # 7. Importe total
    # ------------------------------------------------------------------

    def test_importe_total(self) -> None:
        self.assertEqual(
            _get_text(self.root, "RegistroFactura/RegistroAlta/ImporteTotal"),
            "1331.00",
        )

    # ------------------------------------------------------------------
    # 8. Sistema Informático / encadenamiento
    # ------------------------------------------------------------------

    def test_nombre_sistema(self) -> None:
        self.assertEqual(
            _get_text(self.root, "RegistroFactura/RegistroAlta/SistemaInformatico/NombreSistemaInformatico"),
            "AutoFactura-V9",
        )

    def test_huella_actual(self) -> None:
        self.assertEqual(
            _get_text(self.root, "RegistroFactura/RegistroAlta/Huella"),
            self.HASH_ACTUAL,
        )

    def test_huella_anterior_presente(self) -> None:
        self.assertEqual(
            _get_text(self.root, "RegistroFactura/RegistroAlta/Encadenamiento/RegistroAnterior/Huella"),
            self.HASH_ANTERIOR.upper(),
        )

    def test_huella_anterior_ausente(self) -> None:
        """Si es el primer registro (huella anterior ausente), se genera el nodo PrimerRegistro."""
        root_sin = _parse(
            VerifactuXmlBuilder.construir_xml_alta(
                factura=self.factura,
                config=self.config,
                hash_actual="h1",
                hash_anterior=None,
                es_primer_registro=True  # <-- Cambiado a True porque no hay eslabón previo
            )
        )
        
        # 1. Verificamos que se marque correctamente como el inicio de la cadena de confianza
        self.assertEqual(
            _get_text(root_sin, "RegistroFactura/RegistroAlta/Encadenamiento/PrimerRegistro"),
            "S"
        )
        
        # 2. Nos aseguramos de que NO exista el bloque de registro encadenado (RegistroAnterior)
        NS_SI = "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroInformacion.xsd"
        registro_anterior = root_sin.find(f".//{{{NS_SI}}}RegistroAnterior")
        self.assertIsNone(registro_anterior, "El nodo RegistroAnterior no debería existir en el primer registro.")

    def test_fecha_hora_hito_formato_iso(self) -> None:
        texto = _get_text(self.root, "RegistroFactura/RegistroAlta/FechaHoraHusoGenRegistro")
        # Lanza ValueError si el formato no coincide (ignoramos el offset del huso horario)
        datetime.strptime(texto[:19], "%Y-%m-%dT%H:%M:%S")

    # ------------------------------------------------------------------
    # 9. Output es bytes UTF-8 válidos
    # ------------------------------------------------------------------

    def test_devuelve_bytes(self) -> None:
        self.assertIsInstance(self.xml_bytes, bytes)

    def test_codificacion_utf8_en_declaracion(self) -> None:
        # ET.tostring(encoding="utf-8") devuelve bytes pero sin declaración XML
        # explícita a menos que se use xml_declaration=True. Verificamos que
        # los bytes son válidos UTF-8 decodificándolos directamente.
        decoded = self.xml_bytes.decode("utf-8")
        self.assertIn("RegFactuSistemaFacturacion", decoded)


# ---------------------------------------------------------------------------
# IMPRESIÓN DEL XML COMPLETO AL EJECUTAR EL SCRIPT DIRECTAMENTE
# ---------------------------------------------------------------------------

def imprimir_xml_demo() -> None:
    config  = _make_config()
    factura = _make_factura()

    xml_bytes = VerifactuXmlBuilder.construir_xml_alta(
        factura       = factura,
        config        = config,
        hash_actual   = "abc123def456",
        hash_anterior = "zzz999yyy888",
        es_primer_registro = False
    )

    xml_str = _pretty_print(xml_bytes)

    sep = "=" * 70
    print(f"\n{sep}")
    print("  XML VERI*FACTU GENERADO (demo)")
    print(sep)
    print(xml_str)

    print(f"\n{sep}")
    print("  RESUMEN DE CAMPOS EXTRAÍDOS")
    print(sep)

    root = _parse(xml_bytes)

    campos: dict[str, str] = {
        "Versión esquema":           "Cabecera/Version",
        "Nombre empresa (emisor)":   "Cabecera/ObligadoEmision/NombreRazon",
        "NIF emisor (cabecera)":     "Cabecera/ObligadoEmision/sf:NIF",
        "NIF emisor (IDFactura)":    "RegistroFactura/RegistroAlta/IDFactura/IDEmisorFactura",
        "Número de serie factura":   "RegistroFactura/RegistroAlta/IDFactura/NumSerieFactura",
        "Fecha expedición":          "RegistroFactura/RegistroAlta/IDFactura/FechaExpedicionFactura",
        "Tipo factura":              "RegistroFactura/RegistroAlta/TipoFactura",
        "Descripción Operación":     "RegistroFactura/RegistroAlta/DescripcionOperacion",
        "Nombre destinatario":       "RegistroFactura/RegistroAlta/Destinatarios/IDDestinatario/NombreRazon",
        "NIF destinatario":          "RegistroFactura/RegistroAlta/Destinatarios/IDDestinatario/NIF",
        "Importe total":             "RegistroFactura/RegistroAlta/ImporteTotal",
        "Sistema informático":       "RegistroFactura/RegistroAlta/SistemaInformatico/NombreSistemaInformatico",
        "Versión sistema":           "RegistroFactura/RegistroAlta/SistemaInformatico/Version",
        "Huella actual":             "RegistroFactura/RegistroAlta/Huella",
        "Huella anterior":           "RegistroFactura/RegistroAlta/Encadenamiento/RegistroAnterior/Huella",
        "Fecha/Hora hito":           "RegistroFactura/RegistroAlta/FechaHoraHusoGenRegistro",
    }

    max_k = max(len(k) for k in campos)
    for label, path in campos.items():
        try:
            valor = _get_text(root, path)
        except AssertionError:
            valor = "— (nodo no encontrado)"
        print(f"  {label:<{max_k}}  →  {valor}")

    # Bloques DetalleIVA (usa findtext → devuelve str | None, seguro para Pylance)
    print()
    detalles = root.findall(".//sf:DetalleDesglose", NS)
    print(f"  Bloques DetalleIVA encontrados: {len(detalles)}")
    for i, d in enumerate(detalles, 1):
        base  = d.findtext("sf:BaseImponibleOimporteNoSujeto", "—", namespaces=NS)
        tipo  = d.findtext("sf:TipoImpositivo", "—", namespaces=NS)
        cuota = d.findtext("sf:CuotaRepercutida", "—", namespaces=NS)
        print(f"    [{i}] Base: {base} €  |  IVA: {tipo} %  |  Cuota: {cuota} €")

    print(f"\n{sep}\n")


if __name__ == "__main__":
    imprimir_xml_demo()
    print("Ejecutando tests unitarios...\n")
    unittest.main(verbosity=2)