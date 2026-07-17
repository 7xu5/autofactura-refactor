import os
from flask import current_app
from models import db, Factura, Configuracion
# IMPORTACIÓN CORRECTA DESDE SU SERVICIO ORIGINAL
from services.verifactu_service import VerifactuOrchestrator

class InvoiceSubmissionService:

    @staticmethod
    def enviar_factura_verifactu(factura_id: int, cert_pass: str) -> tuple[dict | None, str | None]:
        """
        Gestiona la lógica técnica del envío de una factura a VeriFactu
        utilizando el Orquestador original del sistema.
        """
        factura = db.session.get(Factura, factura_id)
        if not factura:
            return None, "Factura no encontrada."
            
        if factura.estado_ui == 'Borrador':
            return None, "No se puede enviar una factura en estado Borrador."

        config = db.session.query(Configuracion).first()
        if not config or not config.ruta_certificado:
            return None, "Certificado no configurado en el sistema."
            
        ruta_cert = os.path.join(current_app.root_path, config.ruta_certificado)
        
        try:
            # Invocar al orquestador original con sus argumentos reglamentarios
            exito, mensaje = VerifactuOrchestrator.emitir_y_enviar_factura(
                factura_id=factura_id, 
                ruta_certificado_p12=ruta_cert, 
                contraseña_p12=cert_pass
            )
            
            if exito:
                return {
                    'status': 'ok', 
                    'message': mensaje
                }, None
            else:
                return None, mensaje
                
        except Exception as e:
            return None, f"Error crítico de comunicación con el servicio de inspección: {str(e)}"