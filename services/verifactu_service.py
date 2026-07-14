from datetime import datetime
from typing import Tuple
from models import db, Factura, FacturaVerifactu, Configuracion, RegistroEventos
from utils.verifactu_hash import VerifactuHashMotor
from utils.verifactu_xml import VerifactuXmlBuilder
from utils.verifactu_signer import VerifactuSigner
from utils.verifactu_client import VerifactuClient
import time

class VerifactuOrchestrator:
    """
    Orquestador central que ejecuta el flujo Veri*Factu de principio a fin:
    Normalización -> Hash -> XML -> Firma -> Envío -> Registro de Eventos.
    """

    @classmethod
    def emitir_y_enviar_factura(cls, factura_id: int, ruta_certificado_p12: str, contraseña_p12: str) -> Tuple[bool, str]:
        """
        Consolida una factura ordinaria y realiza todo el proceso de reporte fiscal.
        
        Retorna:
            Tuple: (exito (bool), mensaje_informativo (str))
        """
        print(f"DEBUG: Iniciando proceso Veri*Factu para factura_id: {factura_id}")
        
        # 🚨 CRUCIAL: Fijar el timestamp exacto del evento de generación AQUÍ.
        # Esta única variable sincronizará el String del Hash, el XML y la Base de Datos.
        timestamp_unico = datetime.now().replace(microsecond=0)

        # 1. Recuperar los datos desde la base de datos de forma aislada
        factura = Factura.query.get(factura_id)
        config = Configuracion.query.first()

        if not factura:
            print(f"DEBUG: Error - Factura {factura_id} no encontrada.")
            return False, "La factura especificada no existe."
        if not config:
            print("DEBUG: Error - Configuración global no definida.")
            return False, "La configuración global del sistema no está definida."
        
        if factura.verifactu_estado == "Aceptado":
            print(f"DEBUG: Factura {factura.numero_factura} ya aceptada por la AEAT, proceso abortado.")
            return False, "Esta factura ya ha sido enviada y aceptada por la AEAT."

        try:
            # 2. Generar Hash de la factura actual y recuperar el encadenamiento anterior
            registro_vf = factura.verifactu_registro

            if registro_vf:
                print(f"DEBUG: Reutilizando hashes existentes para reintento de factura {factura.numero_factura}...")
                hash_actual = registro_vf.hash_actual
                hash_anterior = registro_vf.hash_anterior
            else:
                print(f"DEBUG: Generando nuevo hash para factura {factura.numero_factura}...")
                start_hash_gen = time.time()
                # 🚨 Pasamos timestamp_unico para que el hash calcule la fecha exacta con este segundo
                hash_actual, hash_anterior = VerifactuHashMotor.generar_hash_registro(factura, fecha_registro=timestamp_unico)
                end_hash_gen = time.time()
                print(f"DEBUG: Hash generado en {end_hash_gen - start_hash_gen:.4f} segundos.")
            
            # Evaluar si estructuralmente se trata de la primera factura del sistema
            es_primer_registro = True if not hash_anterior else False

            factura_anterior = None
            if not es_primer_registro:
                # Buscamos de forma activa el eslabón anterior en la tabla de registros Verifactu
                reg_ant = FacturaVerifactu.query.filter_by(hash_actual=hash_anterior).first()
                if reg_ant:
                    factura_anterior = reg_ant.factura
                
                # 🚨 DEFENSA CRÍTICA: Si no es el primer registro pero no encontramos el objeto factura_anterior,
                # significa que hay una inconsistencia o corrupción puntual en el histórico. Abortamos en caliente.
                if not factura_anterior:
                    raise LookupError(
                        f"Integridad de Cadena Rota: No se pudo recuperar el objeto Factura "
                        f"asociado al hash anterior '{hash_anterior}'. Operación cancelada para evitar un salto invisible."
                    )

            h_ant_str = hash_anterior[:10] if hash_anterior else "Génesis"
            print(f"DEBUG: Hash actual: {hash_actual[:10]}..., Hash anterior: {h_ant_str} (Primer registro: {es_primer_registro})")

            # 3. Construir la estructura del árbol XML oficial con su sobre SOAP integrado
            print(f"DEBUG: Construyendo sobre XML/SOAP para factura {factura.numero_factura}...")
            start_xml_build = time.time()
            # 🚨 Inyectamos timestamp_unico y el flag explícito de control de integridad de la cadena
            xml_completo_bytes = VerifactuXmlBuilder.construir_xml_alta(
                factura=factura,
                config=config,
                hash_actual=hash_actual,
                es_primer_registro=es_primer_registro,  # <-- NUEVO PARAMETRO OBLIGATORIO
                hash_anterior=hash_anterior,
                factura_anterior=factura_anterior,
                fecha_registro=timestamp_unico,
            )
            end_xml_build = time.time()
            print(f"DEBUG: XML/SOAP generado ({len(xml_completo_bytes)} bytes) en {end_xml_build - start_xml_build:.4f} segundos.")

            # 4. Aplicar la firma electrónica XAdES-BES avanzada directamente sobre el bloque completo
            print(f"DEBUG: Firmando XML con certificado en {ruta_certificado_p12}...")
            start_signing = time.time()
            xml_firmado_bytes = VerifactuSigner.firmar_xml_xades(
                xml_puro_bytes=xml_completo_bytes,
                ruta_p12=ruta_certificado_p12,
                contraseña_p12=contraseña_p12
            )

            # --- LIMPIEZA POST-FIRMA ---
            xml_firmado_str = xml_firmado_bytes.decode('utf-8')
            if xml_firmado_str.count('<?xml') > 1:
                partes = xml_firmado_str.split('<?xml', 2)
                xml_firmado_str = '<?xml' + partes[2] 
            
            xml_firmado_bytes = xml_firmado_str.encode('utf-8')
            end_signing = time.time()
            print(f"DEBUG: XML firmado en {end_signing - start_signing:.4f} segundos.")

            # 5. Abrir canal seguro mTLS y transmitir el paquete a la AEAT
            print(f"DEBUG: Enviando XML firmado ({len(xml_firmado_bytes)} bytes) a la AEAT...")
            start_sending = time.time()
            exito_envio, csv_recibo, error_glosa = VerifactuClient.enviar_factura_aeat(xml_firmado_bytes, ruta_certificado_p12, contraseña_p12)
            end_sending = time.time()
            print(f"DEBUG: Envío a AEAT completado en {end_sending - start_sending:.4f} segundos.")

            # 6. Persistencia e Inmutabilidad en Base de Datos
            factura.estado_ui = "Emitida"
            print(f"DEBUG: Factura {factura.numero_factura} marked as 'Emitida'.")
            
            if not registro_vf:
                registro_vf = FacturaVerifactu(factura_id=factura.id)
                db.session.add(registro_vf)

            # 🚨 Almacenamos exactamente el mismo timestamp de la firma para la auditoría local
            registro_vf.fecha_hora_alta = timestamp_unico
            registro_vf.hash_actual = hash_actual
            registro_vf.hash_anterior = hash_anterior
            registro_vf.estado_envio = "Enviado_Aceptado" if exito_envio else "Rechazado"
            registro_vf.csv_aeat = csv_recibo
            registro_vf.error_glosa = error_glosa
            registro_vf.xml_firmado = xml_firmado_bytes.decode('utf-8')

            # Actualizar los campos de la factura principal para consistencia
            factura.verifactu_estado = "Aceptado" if exito_envio else "Rechazado"
            factura.verifactu_csv = csv_recibo
            factura.verifactu_enviada = exito_envio
            print(f"DEBUG: Registro FacturaVerifactu creado/actualizado con estado: {registro_vf.estado_envio}.")

            # 7. Escribir en el Log de Auditoría exigido por la Ley Antifraude
            log_evento = RegistroEventos(
                fecha_hora=timestamp_unico,
                tipo_evento="Alta_Factura",
                descripcion=f"Factura {factura.numero_factura} consolidada criptográficamente con hash {hash_actual[:10]}..."
            )
            db.session.add(log_evento)
            print(f"DEBUG: Evento de auditoría 'Alta_Factura' registrado.")

            # Confirmamos toda la transacción de golpe de forma segura
            db.session.commit()
            print("DEBUG: Transacción de base de datos confirmada.")

            if exito_envio:
                return True, f"Factura emitida con éxito. Registrada en la AEAT con CSV: {csv_recibo}"
            else:
                return True, f"Factura emitida localmente de forma inmutable, pero rechazada por Hacienda: {error_glosa}"

        except Exception as e:
            db.session.rollback()
            print(f"DEBUG: Error crítico en el proceso Veri*Factu. Rollback de la transacción. Error: {str(e)}")
            return False, f"Error crítico en el proceso Veri*Factu: {str(e)}"