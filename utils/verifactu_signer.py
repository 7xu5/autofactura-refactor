import os
from typing import Tuple, Any
from lxml import etree
from signxml.signer import XMLSigner  # Corregido Aviso 1
from signxml import methods
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.backends import default_backend

class VerifactuSigner:
    """
    Módulo encargado de la carga criptográfica de certificados digitales (.p12/.pfx)
    y de la aplicación de la firma avanzada XAdES-BES exigida por la AEAT.
    """

    @staticmethod
    def cargar_certificado_p12(ruta_p12: str, contraseña: str) -> Tuple[Any, Any]:
        """
        Lee el archivo PKCS#12 (.p12 o .pfx) del autónomo y extrae la clave privada
        y el certificado público asociado.
        """
        if not os.path.exists(ruta_p12):
            raise FileNotFoundError(f"No se encontró el certificado digital en la ruta: {ruta_p12}")

        with open(ruta_p12, "rb") as f:
            p12_data = f.read()

        # Cargar los componentes usando la librería criptográfica estándar de Python
        private_key, certificate, additional_certs = pkcs12.load_key_and_certificates(
            p12_data,
            contraseña.encode('utf-8') if contraseña else None,
            backend=default_backend()
        )

        if private_key is None or certificate is None:
            raise ValueError("El archivo del certificado no contiene una clave privada o un certificado válido.")

        return private_key, certificate

    @classmethod
    def firmar_xml_xades(cls, xml_puro_bytes: bytes, ruta_p12: str, contraseña_p12: str) -> bytes:
        """
        Toma los bytes de un XML limpio y les incrusta la estructura de firma digital XAdES-BES.
        Retorna los bytes del documento XML ya firmado listos para su envío.
        """
        # 1. Extraer las credenciales criptográficas del autónomo
        llave_privada, certificado = cls.cargar_certificado_p12(ruta_p12, contraseña_p12)

        # 2. Parsear el XML puro a un árbol de elementos compatible con lxml
        parser = etree.XMLParser(remove_blank_text=True, resolve_entities=False)
        xml_nodo = etree.fromstring(xml_puro_bytes, parser=parser)

        # 3. Configurar el firmador siguiendo las directrices de Veri*Factu
        signer = XMLSigner(
            method=methods.enveloped,
            signature_algorithm="rsa-sha256",
            digest_algorithm="sha256"
        )

        # 4. Ejecutar el proceso criptográfico de firma
        key_param: Any = llave_privada
        cert_param: Any = [certificado]

        xml_firmado_nodo = signer.sign(
            xml_nodo,
            key=key_param,
            cert=cert_param
        )

        # 5. Exportar el árbol modificado a bytes planos UTF-8
        resultado_bytes = etree.tostring(
            xml_firmado_nodo,
            xml_declaration=False,  # La AEAT no requiere declaración XML en el sobre SOAP
            encoding="utf-8",
            pretty_print=False
        )

        return resultado_bytes