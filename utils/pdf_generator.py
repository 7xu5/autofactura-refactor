# utils/pdf_generator.py
import os
import io
import base64
from flask import render_template, current_app
from xhtml2pdf import pisa

class PDFGenerator:
    @staticmethod
    def get_logo_base64(config_logo_path):
        """Busca el logotipo en el sistema de archivos y lo codifica en base64 para el PDF."""
        logo_base64 = ""
        logo_path = config_logo_path if config_logo_path else ""
        
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
                    if ext not in ['png', 'jpg', 'jpeg']: ext = 'png'
                    return f"data:image/{ext};base64,{encoded_string}"
            except Exception:
                pass
        return logo_base64

    @staticmethod
    def build_lines_html(lineas_data, tipo='presupuesto'):
        """
        Construye las filas de tabla HTML puras para xhtml2pdf.
        tipo: 'presupuesto' o 'factura'.
        """
        lineas_html = ""
        for item in lineas_data:
            # 1. Caso de Sección/Título
            if item.get('tipo') == 'titulo':
                lineas_html += f"""
                <tr style="background-color: #f9fafb;">
                    <td colspan="{'6' if tipo == 'factura' else '5'}" style="font-weight: bold; color: #374151; padding: 6px 10px; font-size: 9.5pt; border-bottom: 1px solid #e5e7eb;">
                        {item.get('texto', 'Sección')}
                    </td>
                </tr>"""
            
            # 2. Caso de Línea normal
            else:
                concepto = item.get('concepto', 'Concepto')
                info = item.get('informacion', '')
                uds = item.get('unidades', 1)
                precio = float(item.get('precio', 0))
                impuesto = item.get('impuesto', '21% IVA')
                total = float(item.get('total', 0))
                cuota_iva = float(item.get('cuota_iva', 0)) # Solo para factura

                html_concepto = f'<b>{concepto}</b>'
                if info:
                    info_fmt = info.replace('\n', '<br>')
                    html_concepto += f'<br><span style="font-size: 8pt; color: #6b7280; font-style: italic;">{info_fmt}</span>'
                
                if tipo == 'factura':
                    lineas_html += f"""
                    <tr>
                        <td style="padding: 6px 10px; font-size: 9pt; border-bottom: 1px solid #e5e7eb; width: 45%;">{html_concepto}</td>
                        <td style="padding: 6px 10px; font-size: 9pt; border-bottom: 1px solid #e5e7eb; text-align: right; width: 8%;">{uds}</td>
                        <td style="padding: 6px 10px; font-size: 9pt; border-bottom: 1px solid #e5e7eb; text-align: right; width: 13%;">{precio:.2f} €</td>
                        <td style="padding: 6px 10px; font-size: 9pt; border-bottom: 1px solid #e5e7eb; text-align: right; width: 12%;">{impuesto}</td>
                        <td style="padding: 6px 10px; font-size: 9pt; border-bottom: 1px solid #e5e7eb; text-align: right; width: 12%;">{cuota_iva:.2f} €</td>
                        <td style="padding: 6px 10px; font-size: 9pt; border-bottom: 1px solid #e5e7eb; text-align: right; width: 10%; font-weight: bold;">{total:.2f} €</td>
                    </tr>"""
                else:
                    # Presupuesto (5 columnas)
                    lineas_html += f"""
                    <tr>
                        <td style="padding: 6px 10px; font-size: 9pt; border-bottom: 1px solid #e5e7eb; width: 50%;">{html_concepto}</td>
                        <td style="padding: 6px 10px; font-size: 9pt; border-bottom: 1px solid #e5e7eb; text-align: right; width: 8%;">{uds}</td>
                        <td style="padding: 6px 10px; font-size: 9pt; border-bottom: 1px solid #e5e7eb; text-align: right; width: 14%;">{precio:.2f} €</td>
                        <td style="padding: 6px 10px; font-size: 9pt; border-bottom: 1px solid #e5e7eb; text-align: right; width: 14%;">{impuesto}</td>
                        <td style="padding: 6px 10px; font-size: 9pt; border-bottom: 1px solid #e5e7eb; text-align: right; width: 14%; font-weight: bold;">{total:.2f} €</td>
                    </tr>"""
        return lineas_html

    @classmethod
    def render_to_pdf(cls, template_name, context):
        """
        Orquesta la compilación final mediante xhtml2pdf y devuelve los bytes.
        Usa BytesIO con codificación utf-8 para manejar correctamente caracteres especiales.
        """
        html_content = render_template(template_name, **context)
        pdf_buffer = io.BytesIO()
        
        # IMPORTANTE: Convertir a bytes con utf-8 y usar BytesIO
        pisa_status = pisa.CreatePDF(
            io.BytesIO(html_content.encode('utf-8')), 
            dest=pdf_buffer,
            encoding='utf-8'
        )
        
        if pisa_status.err:
            # Aquí podrías loguear el error si lo necesitas
            return None
            
        pdf_buffer.seek(0)
        return pdf_buffer.read()
    
    @classmethod
    def generate_albaran_pdf(cls, albaran, configuracion):
        """
        Genera el PDF de un albarán logístico sin importes monetarios.
        """
        logo_b64 = cls.get_logo_base64(configuracion.logo_path if configuracion else None)
        
        context = {
            'albaran': albaran,
            'config': configuracion,
            'logo_base64': logo_b64
        }
        
        return cls.render_to_pdf('albaran_pdf.html', context)