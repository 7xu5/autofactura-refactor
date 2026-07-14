import tempfile
import os
from typing import Tuple, Optional, Any
import requests
from requests.sessions import Session
from cryptography.hazmat.primitives.serialization import pkcs12, Encoding, PrivateFormat, NoEncryption
from cryptography.hazmat.backends import default_backend

class VerifactuClient:
    """
    Cliente de red encargado de abrir el túnel seguro mTLS con la AEAT,
    transmitir el XML firmado e interpretar las respuestas del servidor.
    """
    
    # Endpoints Oficiales de la AEAT (Entorno Sandbox / Pruebas de Veri*Factu)

    URL_ENDPOINT = "https://www1.agenciatributaria.gob.es/wlpl/TIKE-CONT/ws/SistemaFacturacion/VerifactuSOAP" 
    # servidor de pruebasURL_ENDPOINT = "https://prewww1.aeat.es/wlpl/TIKE-CONT/ws/SistemaFacturacion/VerifactuSOAP" # server de pruebas

    @staticmethod
    def _preparar_contexto_mtls(ruta_p12: str, contraseña_p12: str) -> Tuple[Any, str]:
        """
        Extrae la clave privada y el certificado público de un archivo .p12,
        generando un archivo temporal compatible con el parámetro 'cert' de requests.
        Devuelve una tupla (contexto_manejador_archivo, ruta_archivo_pem).
        """
        if not os.path.exists(ruta_p12):
            raise FileNotFoundError(f"No se encontró el certificado en: {ruta_p12}")

        with open(ruta_p12, "rb") as f:
            p12_data = f.read()

        # Extraer los datos criptográficos directos 
        private_key, certificate, additional_certs = pkcs12.load_key_and_certificates(
            p12_data,
            contraseña_p12.encode('utf-8') if contraseña_p12 else None,
            backend=default_backend()
        )

        if private_key is None or certificate is None:
            raise ValueError("El archivo .p12 no contiene claves válidas.")

        # Exportar ambos elementos a formato de texto PEM en memoria
        cert_pem = certificate.public_bytes(Encoding.PEM)
        key_pem = private_key.private_bytes(
            encoding=Encoding.PEM,
            format=PrivateFormat.PKCS8,
            encryption_algorithm=NoEncryption()
        )

        # Guardar en un archivo temporal
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
        
        # 1. Escribir primero la CLAVE PRIVADA
        temp_file.write(key_pem)
        
        # 2. Escribir después el CERTIFICADO PÚBLICO
        temp_file.write(cert_pem)
        
        # 3. Si el P12 tenía certificados intermedios, incluirlos
        for extra_cert in additional_certs:
            temp_file.write(extra_cert.public_bytes(Encoding.PEM))
            
        temp_file.close()

        return temp_file, temp_file.name

    @classmethod
    def enviar_factura_aeat(cls, xml_firmado_bytes: bytes, ruta_p12: str, contraseña_p12: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Envía los bytes del XML firmado a la AEAT utilizando TLS Mutuo de forma segura.
        
        Retorna:
            Tuple: (exito (bool), csv_recibo (str o None), mensaje_error (str o None))
        """
        manejador_temp = None
        ruta_pem_temp = ""
        
        try:
            # 1. Resolver el certificado en memoria y volcarlo al archivo temporal mTLS
            manejador_temp, ruta_pem_temp = cls._preparar_contexto_mtls(ruta_p12, contraseña_p12)

            # 2. Configurar el objeto Session y sus cabeceras
            session = Session()  # <-- Instanciado directamente desde requests.sessions
            session.headers.update({
                "Content-Type": "text/xml;charset=UTF-8",
                "SOAPAction": "",  # Recomendado vacío para Veri*factu
                "User-Agent": "Mozilla/5.0" 
            })
            
            # 3. Realizar la petición utilizando la sesión (reutiliza handshake mTLS)
            respuesta = session.post(
                cls.URL_ENDPOINT,
                data=xml_firmado_bytes,
                cert=ruta_pem_temp,
                timeout=60          
            )

            print(f"DEBUG: Status Code: {respuesta.status_code}")
            print(f"DEBUG: Cabeceras devueltas: {respuesta.headers}")
            print(f"DEBUG: Respuesta cruda: {respuesta.text[:1000]}")
            print(f"DEBUG: Respuesta final de la AEAT: {respuesta.status_code}")
            print(f"DEBUG: Texto recibido: {respuesta.text}")

            # 4. Procesar la respuesta del servidor de Hacienda
            if respuesta.status_code == 200:
                # A) Comprobar si la AEAT ha devuelto un error SOAP Fault crítico
                if "<faultstring>" in respuesta.text or "<env:Fault>" in respuesta.text:
                    mensaje_error = "Desconocido"
                    if "<faultstring>" in respuesta.text:
                        mensaje_error = respuesta.text.split("<faultstring>")[1].split("</faultstring>")[0]
                    return False, None, f"Error SOAP devuelto por AEAT: {mensaje_error}"

                # B) Comprobar el estado de procesamiento de Veri*factu
                if "<tikR:EstadoRegistro>Incorrecto</tikR:EstadoRegistro>" in respuesta.text or "<tikR:EstadoEnvio>Incorrecto</tikR:EstadoEnvio>" in respuesta.text:
                    # Extraer la descripción del error del registro si existe
                    error_msg = "Rechazado por validación de datos en la AEAT."
                    if "<tikR:DescripcionErrorRegistro>" in respuesta.text:
                        error_msg = respuesta.text.split("<tikR:DescripcionErrorRegistro>")[1].split("</tikR:DescripcionErrorRegistro>")[0]
                    return False, None, f"Rechazada por la AEAT: {error_msg}"
                
                if "<tikR:EstadoRegistro>AceptadoConErrores</tikR:EstadoRegistro>" in respuesta.text:
                    return True, "Aceptada con Errores", "La factura fue registrada pero contiene advertencias en los campos."

                # C) Extracción del CSV real devuelto por la AEAT (Si todo fue correcto)
                if "<tikR:CSV>" in respuesta.text:
                    csv_real = respuesta.text.split("<tikR:CSV>")[1].split("</tikR:CSV>")[0]
                    return True, csv_real, None
                
                # Fallback por si la estructura cambia pero no hay errores explícitos
                print(f"ALERTA: AEAT devolvió HTTP 200 pero no se encontró la etiqueta <tikR:CSV>.")
                print(f"Texto íntegro recibido: {respuesta.text}")

                csv_mock_aeat = f"ERR_NO_CSV_" + os.urandom(6).hex().upper()
                error_msg = "El servidor aceptó el paquete (HTTP 200) pero la respuesta no incluyó el código CSV oficial de la AEAT."

                return True, csv_mock_aeat, error_msg
            else:
                return False, None, f"Error del Servidor de Hacienda (HTTP {respuesta.status_code}): {respuesta.text[:200]}"
            
             
        except requests.exceptions.SSLError as ssl_err:
            return False, None, f"Error de Seguridad/Certificado mTLS: {str(ssl_err)}"
        except requests.exceptions.Timeout:
            return False, None, "El servidor de la AEAT no ha respondido a tiempo (Timeout)."
        except Exception as e:
            return False, None, f"Excepción inesperada en la transmisión: {str(e)}"
            
        finally:
            # Limpieza de seguridad eliminar el archivo PEM temporal del disco inmediatamente
            if ruta_pem_temp and os.path.exists(ruta_pem_temp):
                try:
                    os.unlink(ruta_pem_temp)
                except Exception:
                    pass