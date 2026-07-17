import os
import base64
from decimal import Decimal
from flask import current_app
from models import db, Contacto, Factura, FacturaLinea, MetodoPago, Configuracion
from services.invoice_service import InvoiceService
from utils.pdf_generator import PDFGenerator

class InvoicePdfService:

    @staticmethod
    def get_logo_base64(config: Configuracion | None) -> str:
        """Busca el logotipo corporativo en el disco y lo devuelve convertido en una URI Base64."""
        logo_base64 = ""
        logo_path = config.logo_path if config and config.logo_path else ""
        if logo_path:
            filename = os.path.basename(logo_path)
            posible_path = os.path.join(current_app.root_path, 'static', 'uploads', filename)
            if os.path.exists(posible_path):
                logo_path = posible_path
            else:
                logo_path = os.path.join(current_app.root_path, 'static', filename)
        else:
            logo_path = os.path.join(current_app.root_path, 'static', 'logo.png')

        if os.path.exists(logo_path) and os.path.isfile(logo_path):
            try:
                with open(logo_path, "rb") as image_file:
                    encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                    ext = os.path.splitext(logo_path)[1].lower().replace('.', '')
                    if ext not in ['png', 'jpg', 'jpeg']: 
                        ext = 'png'
                    logo_base64 = f"data:image/{ext};base64,{encoded_string}"
            except Exception:
                logo_base64 = ""
        return logo_base64

    @classmethod
    def normalizar_lineas_pdf(cls, lineas_pdf: list[dict]) -> list[dict]:
        """Asegura que los valores numéricos de las líneas mantengan precisión Decimal en Jinja2."""
        for item in lineas_pdf:
            for campo in ['precio', 'total', 'cuota_iva']:
                val = item.get(campo)
                if val is not None:
                    if isinstance(val, str):
                        item[campo] = Decimal(val)
                    elif isinstance(val, (int, float)):
                        item[campo] = Decimal(str(val))
        return lineas_pdf

    @classmethod
    def generar_pdf_factura(cls, factura: Factura) -> bytes | None:
        """Genera los bytes del PDF correspondientes a una factura guardada en la base de datos."""
        config = db.session.query(Configuracion).first()
        cliente = db.session.get(Contacto, factura.contacto_id)
        logo_base64 = cls.get_logo_base64(config)

        metodo_pago = None
        if hasattr(factura, 'metodo_pago_id') and factura.metodo_pago_id:
            metodo_pago = db.session.get(MetodoPago, factura.metodo_pago_id)
        elif hasattr(factura, 'metodo_pago') and factura.metodo_pago:
            metodo_pago = factura.metodo_pago

        lineas_relacion: list[FacturaLinea] = factura.lineas  # type: ignore[assignment]
        if lineas_relacion:
            lineas_pdf, texto_iva = InvoiceService.preparar_lineas_para_pdf(lineas_relacion)
        else:
            lineas_pdf, texto_iva = [], "Impuestos"

        lineas_pdf = cls.normalizar_lineas_pdf(lineas_pdf)
        qr_base64 = InvoiceService.generar_qr_verifactu(factura, config)

        porcentaje_irpf_seguro = factura.porcentaje_irpf if factura.porcentaje_irpf is not None else Decimal('0.00')
        total_retencion_seguro = factura.total_retencion_irpf if factura.total_retencion_irpf is not None else Decimal('0.00')

        context = {
            'factura': factura,
            'config': config,
            'cliente': cliente,
            'logo_base64': logo_base64,
            'metodo_pago': metodo_pago,
            'lineas': lineas_pdf,
            'texto_iva_totales': texto_iva,
            'qr_base64': qr_base64,
        }
        context['factura'].porcentaje_irpf = porcentaje_irpf_seguro
        context['factura'].total_retencion_irpf = total_retencion_seguro

        return PDFGenerator.render_to_pdf('pdf_templates/invoice_pdf.html', context)

    @classmethod
    def generar_pdf_previsualizacion(cls, factura_simulada, cliente: Contacto, metodo_pago: MetodoPago | None, lineas: list) -> bytes | None:
        """Genera los bytes del PDF para una simulación sin persistencia en base de datos."""
        config = db.session.query(Configuracion).first()
        logo_base64 = cls.get_logo_base64(config)

        lineas_datos, texto_iva = InvoiceService.preparar_lineas_para_pdf(lineas)
        lineas_datos = cls.normalizar_lineas_pdf(lineas_datos)

        context = {
            'factura': factura_simulada,
            'config': config,
            'cliente': cliente,
            'metodo_pago': metodo_pago,
            'lineas': lineas_datos,
            'texto_iva_totales': texto_iva,
            'logo_base64': logo_base64,
            'qr_base64': "", 
            'es_previsualizacion': True
        }

        return PDFGenerator.render_to_pdf('pdf_templates/invoice_pdf.html', context)