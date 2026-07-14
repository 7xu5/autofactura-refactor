import xml.etree.ElementTree as ET
from utils.verifactu_signer import VerifactuSigner
from utils.verifactu_client import VerifactuClient
import contextlib
import io
import getpass
import re

def realizar_consulta_aeat(config, numero_factura: str, fecha_factura_str: str, ruta_p12: str, contraseña_p12: str):
    """
    Construye, firma y envía una petición de consulta estructurada a la AEAT.
    """
    NS_SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
    NS_VFC  = "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/RegFactuSistemaFacturacionBilConsulta.xsd"
    NS_SI   = "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroInformacion.xsd"

    ET.register_namespace("soapenv", NS_SOAP)
    ET.register_namespace("vfc",     NS_VFC)
    ET.register_namespace("sf",      NS_SI)

    envelope = ET.Element(f"{{{NS_SOAP}}}Envelope")
    ET.SubElement(envelope, f"{{{NS_SOAP}}}Header")
    body = ET.SubElement(envelope, f"{{{NS_SOAP}}}Body")

    root = ET.SubElement(body, f"{{{NS_VFC}}}ConsultaFactuSistemaFacturacion")

    cabecera = ET.SubElement(root, f"{{{NS_VFC}}}Cabecera")
    nif_el = ET.SubElement(cabecera, f"{{{NS_SI}}}NIF")
    nif_el.text = config.cif_nif
    nombre_el = ET.SubElement(cabecera, f"{{{NS_SI}}}NombreRazon")
    nombre_el.text = config.nombre_empresa

    filtro = ET.SubElement(root, f"{{{NS_VFC}}}FiltroConsulta")
    id_factura = ET.SubElement(filtro, f"{{{NS_VFC}}}IDFactura")
    
    id_emisor = ET.SubElement(id_factura, f"{{{NS_SI}}}IDEmisorFactura")
    id_emisor.text = config.cif_nif
    
    num_serie = ET.SubElement(id_factura, f"{{{NS_SI}}}NumSerieFactura")
    num_serie.text = numero_factura
    
    fecha_exp = ET.SubElement(id_factura, f"{{{NS_SI}}}FechaExpedicionFactura")
    fecha_exp.text = fecha_factura_str

    xml_puro_bytes = ET.tostring(envelope, encoding="utf-8", xml_declaration=True)

    print("[+] Aplicando firma digital avanzada al XML de consulta...")
    xml_firmado_bytes = VerifactuSigner.firmar_xml_xades(
        xml_puro_bytes=xml_puro_bytes,
        ruta_p12=ruta_p12,
        contraseña_p12=contraseña_p12
    )

    xml_firmado_str = xml_firmado_bytes.decode('utf-8')
    if xml_firmado_str.count('<?xml') > 1:
        partes = xml_firmado_str.split('<?xml', 2)
        xml_firmado_str = '<?xml' + partes[2]
    xml_firmado_bytes = xml_firmado_str.encode('utf-8')

    url_consulta = "https://www2.agenciatributaria.gob.es/wlpl/TIKE-CONT/ws/SistemaFacturacion/VerifactuConsultaSOAP"
    url_original = VerifactuClient.URL_ENDPOINT
    
    try:
        VerifactuClient.URL_ENDPOINT = url_consulta
        print("[+] Enviando consulta firmada a la AEAT...")
        
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            exito, csv_o_estado, error = VerifactuClient.enviar_factura_aeat(
                xml_firmado_bytes, 
                ruta_p12, 
                contraseña_p12
            )
        return exito, csv_o_estado, error, f.getvalue()
    finally:
        VerifactuClient.URL_ENDPOINT = url_original

def generar_url_conciliacion_oficial(config, numero_factura: str, fecha_factura_str: str, importe_total: str):
    base_url = "https://www2.agenciatributaria.gob.es/wlpl/TIKE-CONT/ws/SistemaFacturacion/Cotejo.html"
    return f"{base_url}?nif={config.cif_nif}&num_serie={numero_factura}&fecha={fecha_factura_str}&importe={importe_total}"

if __name__ == "__main__":
    print("=== INICIANDO PRUEBA DE CONSULTA VERI*FACTU FIRMADA ===")
    
    class ConfigMock:
        cif_nif = "44308760L"
        nombre_empresa = "Jesus Antonio Sanchez Leon"

    config_mock = ConfigMock()
    NUMERO_FACTURA_TEST = "2026-0001" 
    FECHA_FACTURA_TEST = "04-07-2026"  
    RUTA_CERTIFICADO = r"C:\Users\Txus\Programacion VisualStudio\Entorno\Software Facturacion Autonomos\certs\firma_test_verifactu.pfx"

    contraseña = getpass.getpass("[?] Introduce la contraseña del certificado PFX: ")

    if not contraseña:
        print("[-] Error: La contraseña no puede estar vacía.")
    else:
        exito, resultado, error, texto_capturado = realizar_consulta_aeat(
            config=config_mock,
            numero_factura=NUMERO_FACTURA_TEST,
            fecha_factura_str=FECHA_FACTURA_TEST,
            ruta_p12=RUTA_CERTIFICADO,
            contraseña_p12=contraseña
        )
        
        print("\n=== RESULTADO DE LA VALIDACIÓN ===")
        
        # Aislamiento del XML
        respuesta_xml_real = ""
        if "DEBUG: Texto recibido:" in texto_capturado:
            partes = texto_capturado.split("DEBUG: Texto recibido:", 1)
            if len(partes) > 1: respuesta_xml_real = partes[1].strip()
        
        if not respuesta_xml_real and "<" in texto_capturado and "Envelope" in texto_capturado:
            match = re.search(r"<[a-zA-Z0-9]+:Envelope", texto_capturado)
            if match: respuesta_xml_real = texto_capturado[match.start():].strip()

        # Procesamiento
        if respuesta_xml_real and "<" in respuesta_xml_real:
            # Detección prioritaria de error AEAT
            if "Fault" in respuesta_xml_real or "404" in respuesta_xml_real:
                print("\n[!] DETECTADO: El servicio SOAP de la AEAT está desactivado temporalmente.")
                url = generar_url_conciliacion_oficial(config_mock, NUMERO_FACTURA_TEST, FECHA_FACTURA_TEST, "121.00")
                print(f"[🔗] Enlace para verificación manual oficial: {url}")
            else:
                try:
                    root_resp = ET.fromstring(respuesta_xml_real)
                    NS_RE_CONS = "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/RegFactuSistemaFacturacionBilRespuestaConsulta.xsd"
                    registro = root_resp.find(f".//{{{NS_RE_CONS}}}RegistroRespuestaConsFactuSistemaFacturacion")
                    
                    if registro is not None:
                        estado_nodo = registro.find(f".//{{{NS_RE_CONS}}}EstadoFactura")
                        fecha_pres_nodo = registro.find(f".//{{{NS_RE_CONS}}}FechaPresentacion")
                        
                        estado_aeat = estado_nodo.text if estado_nodo is not None else "No disponible"
                        fecha_presentacion = fecha_pres_nodo.text if fecha_pres_nodo is not None else "No disponible"
                        
                        print(f"[🏆] CONCILIACIÓN OFICIAL: {estado_aeat} | Fecha: {fecha_presentacion}")
                    else:
                        print("[-] La factura no está registrada o respuesta vacía.")
                except Exception as e:
                    print(f"[-] Error al parsear XML: {e}")
        else:
            print(f"[!] No se recibió XML válido. Respuesta cruda: {resultado}")
            
        print(f"[-] Errores de red/SOAP: {error}")