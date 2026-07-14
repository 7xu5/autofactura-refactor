import json
import zlib
import io
import base64
import re
from datetime import datetime, date
from decimal import Decimal

from werkzeug.utils import secure_filename
from models import db, init_db, User, Contacto, Factura, Gasto, ImpuestoGasto, Presupuesto, Producto, Pago, Configuracion, MetodoPago
import os
from werkzeug.security import check_password_hash
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, make_response, abort
import pdfplumber
import re
from flask import jsonify, request


ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}


def parse_jpeg_size(data):
    if not data.startswith(b'\xff\xd8'):
        return None, None
    pos = 2
    while pos < len(data):
        if data[pos] != 0xFF:
            break
        marker = data[pos:pos+2]
        pos += 2
        if marker == b'\xff\xd9':
            break
        if marker == b'\xff\x00':
            continue
        if 0xD0 <= marker[1] <= 0xD9:
            continue
        if pos + 2 > len(data):
            break
        length = int.from_bytes(data[pos:pos+2], 'big')
        if marker in (b'\xff\xc0', b'\xff\xc1', b'\xff\xc2', b'\xff\xc3', b'\xff\xc5', b'\xff\xc6', b'\xff\xc7', b'\xff\xc9', b'\xff\xca', b'\xff\xcb', b'\xff\xcd', b'\xff\xce', b'\xff\xcf'):
            if pos + 7 <= len(data):
                height = int.from_bytes(data[pos+3:pos+5], 'big')
                width = int.from_bytes(data[pos+5:pos+7], 'big')
                return width, height
            break
        pos += length
    return None, None


def parse_png_info(data):
    if not data.startswith(b'\x89PNG\r\n\x1a\n'):
        return None
    pos = 8
    width = height = None
    bit_depth = None
    color_type = None
    idat_data = b''
    while pos + 12 <= len(data):
        length = int.from_bytes(data[pos:pos+4], 'big')
        chunk_type = data[pos+4:pos+8]
        chunk_data = data[pos+8:pos+8+length]
        if chunk_type == b'IHDR':
            width = int.from_bytes(chunk_data[0:4], 'big')
            height = int.from_bytes(chunk_data[4:8], 'big')
            bit_depth = chunk_data[8]
            color_type = chunk_data[9]
            compression_method = chunk_data[10]
            filter_method = chunk_data[11]
            interlace_method = chunk_data[12]
            if compression_method != 0 or filter_method != 0 or interlace_method != 0:
                return None
        elif chunk_type == b'IDAT':
            idat_data += chunk_data
        elif chunk_type == b'IEND':
            break
        pos += length + 12
    if width is None or height is None or bit_depth != 8:
        return None
    try:
        decompressed = zlib.decompress(idat_data)
    except Exception:
        return None
    if color_type == 2:
        return {
            'format': 'PNG',
            'width': width,
            'height': height,
            'colors': 3,
            'data': decompressed,
            'has_alpha': False,
        }
    if color_type == 6:
        return {
            'format': 'PNG',
            'width': width,
            'height': height,
            'colors': 4,
            'data': decompressed,
            'has_alpha': True,
        }
    return None


def get_logo_image_info(logo_path):
    if not logo_path:
        return None
    full_path = os.path.join(app.root_path, 'static', logo_path)
    if not os.path.isfile(full_path):
        return None
    with open(full_path, 'rb') as f:
        data = f.read()
    if data.startswith(b'\xff\xd8'):
        width, height = parse_jpeg_size(data)
        if width and height:
            return {'format': 'JPEG', 'width': width, 'height': height, 'data': data}
        return None
    png_info = parse_png_info(data)
    if png_info:
        png_info['raw_bytes'] = data
        return png_info
    return None

app = Flask(__name__)
app.config.from_object('config')
db.init_app(app)
app.jinja_env.globals['date'] = date


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def calculate_totals(base, iva_percent, recargo=False, porcentaje_retencion=Decimal('0.00')):
    base = Decimal(base or 0)
    iva = (base * Decimal(iva_percent) / Decimal('100')).quantize(Decimal('0.01'))
    recargo_total = Decimal('0.00')
    if recargo:
        recargo_total = (base * Decimal('5.20') / Decimal('100')).quantize(Decimal('0.01'))
    retencion = (base * porcentaje_retencion / Decimal('100')).quantize(Decimal('0.01'))
    total = (base + iva + recargo_total - retencion).quantize(Decimal('0.01'))
    return base, iva, recargo_total, retencion, total


def parse_impuesto_porcentaje(impuesto_text):
    impuesto_text = (impuesto_text or '').strip()
    if not impuesto_text or 'exento' in impuesto_text.lower():
        return Decimal('0')
    porcentaje_text = impuesto_text.split('%', 1)[0].strip()
    try:
        return Decimal(porcentaje_text or '0')
    except Exception:
        return Decimal('0')


def escape_pdf_text(value):
    text = str(value)
    text = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
    text = text.replace('€', 'EUR')
    return ''.join(ch if 32 <= ord(ch) < 127 or 128 <= ord(ch) < 256 else '?' for ch in text)


def get_invoice_tax_label(lineas):
    used_types = set()
    for linea in lineas:
        impuesto = (linea.get('impuesto') or '').upper()
        if 'IGIC' in impuesto:
            used_types.add('IGIC')
        elif 'IVA' in impuesto:
            used_types.add('IVA')
    if not used_types:
        return 'Impuesto'
    if len(used_types) == 1:
        return used_types.pop()
    return 'IVA/IGIC'


def generate_invoice_pdf_bytes(factura):
    def pdf_text(x, y, text, size=12):
        return f'BT /F1 {size} Tf {x} {y} Td ({escape_pdf_text(text)}) Tj ET'

    def pdf_line(x1, y1, x2, y2):
        return f'{x1} {y1} m {x2} {y2} l S'

    def pdf_image(x, y, w, h):
        return f'q {w} 0 0 {h} {x} {y} cm /Im0 Do Q'

    def split_png_rgba(decompressed, width, height):
        rgb_data = bytearray()
        alpha_data = bytearray()
        stride = 1 + width * 4
        for row in range(height):
            offset = row * stride
            row = decompressed[offset:offset+stride]
            rgb_data.append(row[0])
            alpha_data.append(row[0])
            for pixel in range(1, len(row), 4):
                rgb_data.extend(row[pixel:pixel+3])
                alpha_data.append(row[pixel+3])
        return bytes(rgb_data), bytes(alpha_data)

    configuracion = Configuracion.query.first()
    cliente = factura.contacto
    logo_info = get_logo_image_info(configuracion.logo_path if configuracion else None)

    company_name = configuracion.nombre_empresa if configuracion and configuracion.nombre_empresa else 'Empresa'
    company_tax = configuracion.cif_nif if configuracion and configuracion.cif_nif else ''
    company_address = configuracion.direccion_fiscal if configuracion and configuracion.direccion_fiscal else ''
    company_location = ' '.join(filter(None, [configuracion.codigo_postal or '', configuracion.ciudad or ''])) if configuracion else ''
    company_region = ' '.join(filter(None, [configuracion.provincia or '', configuracion.pais or ''])) if configuracion else ''
    company_contact = ' '.join(filter(None, [configuracion.telefono or '', configuracion.email or ''])) if configuracion else ''
    company_website = configuracion.website if configuracion and configuracion.website else ''
    company_note = configuracion.nota_legal if configuracion and configuracion.nota_legal else ''

    header = []
    if logo_info:
        max_logo_width = 140
        max_logo_height = 50
        logo_display_width = min(max_logo_width, logo_info['width'])
        logo_display_height = int(logo_display_width * logo_info['height'] / logo_info['width'])
        if logo_display_height > max_logo_height:
            logo_display_height = max_logo_height
            logo_display_width = int(logo_display_height * logo_info['width'] / logo_info['height'])
        # Posicionar logo en la esquina superior izquierda, en la zona de la empresa
        header.append(pdf_image(50, 750, logo_display_width, logo_display_height))
    header.extend([
        pdf_text(50, 805, 'FACTURA', 22),
        pdf_text(50, 780, company_name, 11),
        pdf_text(50, 765, company_tax, 10),
        pdf_text(50, 750, company_address, 9),
        pdf_text(50, 735, company_location, 9),
        pdf_text(50, 720, company_region, 9),
        pdf_text(50, 705, company_contact, 9),
        pdf_text(50, 690, company_website, 9),
        pdf_text(330, 780, 'CLIENTE', 11),
        pdf_text(330, 765, cliente.nombre_fiscal, 10),
        pdf_text(330, 750, f'{cliente.direccion_fiscal or ""}', 9),
        pdf_text(330, 735, f'{cliente.codigo_postal or ""} {cliente.ciudad or ""}', 9),
        pdf_text(330, 720, f'{cliente.provincia or ""} {cliente.pais or ""}', 9),
        pdf_text(330, 705, f'NIF/CIF: {cliente.numero_documento or ""}', 9),
        pdf_text(50, 640, f'Número: {factura.numero_factura}', 10),
        pdf_text(50, 625, f'Fecha: {factura.fecha_factura.strftime("%d/%m/%Y")}', 10),
        pdf_text(50, 610, f'Vencimiento: {factura.fecha_vencimiento.strftime("%d/%m/%Y") if factura.fecha_vencimiento else "-"}', 10),
        pdf_text(50, 595, f'Referencia: {factura.referencia or "-"}', 10),
    ])

    table_header_y = 565
    table_header = [
        pdf_text(50, table_header_y, 'Concepto', 10),
        pdf_text(320, table_header_y, 'Cant.', 10),
        pdf_text(380, table_header_y, 'Precio', 10),
        pdf_text(450, table_header_y, 'Impuesto', 10),
        pdf_text(520, table_header_y, 'Total', 10),
        pdf_line(50, table_header_y - 4, 560, table_header_y - 4),
    ]

    content_parts = []
    content_parts.extend(header)
    content_parts.extend(table_header)

    y = table_header_y - 20
    row_index = 0
    for linea in factura.lineas_json():
        if y < 100:
            break
        concepto = linea.get('concepto', '')
        unidades = linea.get('unidades', '0')
        precio = linea.get('precio', '0.00')
        impuesto = linea.get('impuesto', '')
        total = linea.get('total', '0.00')
        content_parts.append(pdf_text(50, y, concepto[:52], 9))
        content_parts.append(pdf_text(320, y, unidades, 9))
        content_parts.append(pdf_text(380, y, f'{float(precio):.2f} EUR', 9))
        content_parts.append(pdf_text(450, y, impuesto, 9))
        content_parts.append(pdf_text(520, y, f'{float(total):.2f} EUR', 9))
        y -= 14

        # Añadir información adicional si existe
        informacion = linea.get('informacion', '').strip()
        if informacion:
            content_parts.append(pdf_text(60, y, informacion[:70], 8))
            y -= 12
            
        content_parts.append(pdf_line(50, y - 2, 560, y - 2))
        y -= 10
        row_index += 1

    y -= 20 # Más espacio antes de los totales
    content_parts.append(pdf_line(50, y, 560, y))
    y -= 14
    content_parts.append(pdf_text(400, y, f'Base imponible: {factura.total_base_imponible:.2f} EUR', 10))
    y -= 14
    tax_label = get_invoice_tax_label(factura.lineas_json())
    content_parts.append(pdf_text(400, y, f'Cuota {tax_label}: {factura.total_cuota_iva:.2f} EUR', 10))
    y -= 14
    content_parts.append(pdf_text(400, y, f'Recargo: {factura.total_recargo_equivalencia:.2f} EUR', 10))
    y -= 16
    content_parts.append(pdf_text(400, y, f'Total: {factura.total_factura:.2f} EUR', 12))
    y -= 18
    content_parts.append(pdf_text(50, y, f'Estado: {factura.estado_pago}', 10))
    
    # Método de pago inferior izquierda
    if factura.metodo_pago_id:
        mp = MetodoPago.query.get(factura.metodo_pago_id)
        if mp:
            y -= 30
            texto_pago = f'Forma de pago: {mp.nombre} ({mp.tipo or "Contado"})'
            content_parts.append(pdf_text(50, y, texto_pago, 9))
            if mp.entidad or mp.cuenta_iban:
                y -= 15
                detalles = f'Entidad: {mp.entidad or "-"} | IBAN: {mp.cuenta_iban or "-"}'
                content_parts.append(pdf_text(50, y, detalles, 8))

    content_stream = '\n'.join(content_parts).encode('latin1')
    objects = []
    objects.append(b'1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n')
    objects.append(b'2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n')

    resources = '<< /Font << /F1 4 0 R >>'
    logo_objects = []
    if logo_info:
        resources += ' /XObject << /Im0 6 0 R >>'
        if logo_info['format'] == 'JPEG':
            image_stream = b'stream\n' + logo_info['data'] + b'\nendstream\n'
            logo_objects.append(
                b'6 0 obj\n<< /Type /XObject /Subtype /Image /Width ' + str(logo_info['width']).encode() + b' /Height ' + str(logo_info['height']).encode() + b' /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ' + str(len(logo_info['data'])).encode() + b' >>\n' + image_stream + b'endobj\n'
            )
        else:
            if logo_info['has_alpha']:
                rgb_data, alpha_data = split_png_rgba(logo_info['data'], logo_info['width'], logo_info['height'])
                image_stream = b'stream\n' + zlib.compress(rgb_data) + b'\nendstream\n'
                mask_stream = b'stream\n' + zlib.compress(alpha_data) + b'\nendstream\n'
                logo_objects.append(
                    b'6 0 obj\n<< /Type /XObject /Subtype /Image /Width ' + str(logo_info['width']).encode() + b' /Height ' + str(logo_info['height']).encode() + b' /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /DecodeParms << /Predictor 15 /Colors 3 /BitsPerComponent 8 /Columns ' + str(logo_info['width']).encode() + b' >> /SMask 7 0 R /Length ' + str(len(zlib.compress(rgb_data))).encode() + b' >>\n' + image_stream + b'endobj\n'
                )
                logo_objects.append(
                    b'7 0 obj\n<< /Type /XObject /Subtype /Image /Width ' + str(logo_info['width']).encode() + b' /Height ' + str(logo_info['height']).encode() + b' /ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode /DecodeParms << /Predictor 15 /Colors 1 /BitsPerComponent 8 /Columns ' + str(logo_info['width']).encode() + b' >> /Length ' + str(len(zlib.compress(alpha_data))).encode() + b' >>\n' + mask_stream + b'endobj\n'
                )
            else:
                raw = logo_info['data']
                compressed = zlib.compress(raw)
                logo_objects.append(
                    b'6 0 obj\n<< /Type /XObject /Subtype /Image /Width ' + str(logo_info['width']).encode() + b' /Height ' + str(logo_info['height']).encode() + b' /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /DecodeParms << /Predictor 15 /Colors 3 /BitsPerComponent 8 /Columns ' + str(logo_info['width']).encode() + b' >> /Length ' + str(len(compressed)).encode() + b' >>\n' + b'stream\n' + compressed + b'\nendstream\nendobj\n'
                )
    resources += ' >>'
    objects.append(f'3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources {resources} /Contents 5 0 R >>\n'.encode())
    objects.append(b'4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n')
    stream = b'stream\n' + content_stream + b'\nendstream\n'
    objects.append(b'5 0 obj\n<< /Length ' + str(len(content_stream)).encode() + b' >>\n' + stream + b'endobj\n')
    objects.extend(logo_objects)
    pdf = b'%PDF-1.4\n'
    xref_positions = []
    for obj in objects:
        xref_positions.append(len(pdf))
        pdf += obj
    xref_start = len(pdf)
    pdf += b'xref\n0 ' + str(len(objects) + 1).encode() + b'\n0000000000 65535 f \n'
    for pos in xref_positions:
        pdf += f'{pos:010d} 00000 n \n'.encode()
    trailer = b'trailer\n<< /Size ' + str(len(objects) + 1).encode() + b' /Root 1 0 R >>\nstartxref\n' + str(xref_start).encode() + b'\n%%EOF\n'
    pdf += trailer
    return pdf


def generate_budget_pdf_bytes(data):
    def pdf_text(x, y, text, size=12):
        return f'BT /F1 {size} Tf {x} {y} Td ({escape_pdf_text(text)}) Tj ET'

    def pdf_line(x1, y1, x2, y2):
        return f'{x1} {y1} m {x2} {y2} l S'

    def pdf_image(x, y, w, h):
        return f'q {w} 0 0 {h} {x} {y} cm /Im0 Do Q'

    def split_png_rgba(decompressed, width, height):
        rgb_data = bytearray()
        alpha_data = bytearray()
        stride = 1 + width * 4
        for row in range(height):
            offset = row * stride
            row = decompressed[offset:offset+stride]
            rgb_data.append(row[0])
            alpha_data.append(row[0])
            for pixel in range(1, len(row), 4):
                rgb_data.extend(row[pixel:pixel+3])
                alpha_data.append(row[pixel+3])
        return bytes(rgb_data), bytes(alpha_data)

    configuracion = Configuracion.query.first()
    cliente = data['cliente']
    logo_info = get_logo_image_info(configuracion.logo_path if configuracion else None)
    
    company_name = configuracion.nombre_empresa if configuracion and configuracion.nombre_empresa else 'Empresa'
    company_tax = configuracion.cif_nif if configuracion and configuracion.cif_nif else ''
    company_address = configuracion.direccion_fiscal if configuracion and configuracion.direccion_fiscal else ''
    company_location = ' '.join(filter(None, [configuracion.codigo_postal or '', configuracion.ciudad or ''])) if configuracion else ''
    company_region = ' '.join(filter(None, [configuracion.provincia or '', configuracion.pais or ''])) if configuracion else ''
    company_contact = ' '.join(filter(None, [configuracion.telefono or '', configuracion.email or ''])) if configuracion else ''
    company_website = configuracion.website if configuracion and configuracion.website else ''
    company_note = configuracion.nota_legal if configuracion and configuracion.nota_legal else ''

    header = []
    if logo_info:
        max_logo_width = 140
        max_logo_height = 50
        logo_display_width = min(max_logo_width, logo_info['width'])
        logo_display_height = int(logo_display_width * logo_info['height'] / logo_info['width'])
        if logo_display_height > max_logo_height:
            logo_display_height = max_logo_height
            logo_display_width = int(logo_display_height * logo_info['width'] / logo_info['height'])
        # Posicionar logo en la esquina superior izquierda, en la zona de la empresa
        header.append(pdf_image(50, 750, logo_display_width, logo_display_height))

    header.extend([
        pdf_text(50, 805, 'PRESUPUESTO', 22),
        pdf_text(50, 780, company_name, 11),
        pdf_text(50, 765, company_tax, 10),
        pdf_text(50, 750, company_address, 9),
        pdf_text(50, 735, company_location, 9),
        pdf_text(50, 720, company_region, 9),
        pdf_text(50, 705, company_contact, 9),
        pdf_text(50, 690, company_website, 9),
        pdf_text(50, 675, company_note[:80], 9),
        pdf_text(330, 780, 'CLIENTE', 11),
        pdf_text(330, 765, cliente.nombre_fiscal, 10),
        pdf_text(330, 750, f'{cliente.direccion_fiscal or ""}', 9),
        pdf_text(330, 735, f'{cliente.codigo_postal or ""} {cliente.ciudad or ""}', 9),
        pdf_text(330, 720, f'{cliente.provincia or ""} {cliente.pais or ""}', 9),
        pdf_text(330, 705, f'NIF/CIF: {cliente.numero_documento or ""}', 9),
        pdf_text(50, 640, f'Número: {data["numero"]}', 10),
        pdf_text(50, 625, f'Fecha: {data["fecha"]}', 10),
        pdf_text(50, 610, f'Validez: {data["validez"]}', 10),
        pdf_text(50, 595, f'Referencia: {data["referencia"] or "-"}', 10),
    ])

    table_header_y = 565
    table_header = [
        pdf_text(50, table_header_y, 'Concepto', 10),
        pdf_text(320, table_header_y, 'Cant.', 10),
        pdf_text(380, table_header_y, 'Precio', 10),
        pdf_text(450, table_header_y, 'Impuesto', 10),
        pdf_text(520, table_header_y, 'Total', 10),
        pdf_line(50, table_header_y - 4, 560, table_header_y - 4),
    ]

    content_parts = []
    content_parts.extend(header)
    content_parts.extend(table_header)

    y = table_header_y - 20
    for linea in data['lineas']:
        if y < 100: break
        if linea.get('tipo') == 'titulo':
            y -= 5
            content_parts.append(pdf_text(50, y, linea.get('texto', '').upper(), 10))
            y -= 20
            continue
            
        concepto = linea.get('concepto', '')
        unidades = linea.get('unidades', '0')
        precio = linea.get('precio', '0.00')
        impuesto = linea.get('impuesto', '')
        total = linea.get('total', '0.00')
        
        content_parts.append(pdf_text(50, y, concepto[:52], 9))
        content_parts.append(pdf_text(320, y, unidades, 9))
        content_parts.append(pdf_text(380, y, f'{float(precio):.2f} EUR', 9))
        content_parts.append(pdf_text(450, y, impuesto, 9))
        content_parts.append(pdf_text(520, y, f'{float(total):.2f} EUR', 9))
        y -= 14
        
        # Información adicional
        informacion = linea.get('informacion', '').strip()
        if informacion:
            content_parts.append(pdf_text(60, y, informacion[:70], 8))
            y -= 12
            
        content_parts.append(pdf_line(50, y - 2, 560, y - 2))
        y -= 10

    y -= 20  # Más espacio antes de los totales
    content_parts.append(pdf_line(50, y, 560, y))
    y -= 14
    content_parts.append(pdf_text(400, y, f'Base imponible: {data["total_base"]:.2f} EUR', 10))
    y -= 14
    tax_label = get_invoice_tax_label(data['lineas'])
    content_parts.append(pdf_text(400, y, f'Cuota {tax_label}: {data["total_impuestos"]:.2f} EUR', 10))
    y -= 14
    content_parts.append(pdf_text(400, y, f'Recargo: 0.00 EUR', 10))
    y -= 16
    content_parts.append(pdf_text(400, y, f'Total: {data["total_presupuesto"]:.2f} EUR', 12))
    y -= 18
    content_parts.append(pdf_text(50, y, f'Estado: {data.get("estado", "-")}', 10))

    # Método de pago inferior izquierda
    metodo_pago = data.get('metodo_pago')
    if metodo_pago:
        # Usamos una coordenada 'y' baja o vinculada al flujo actual
        # Asegúrate de restarle margen para que no se pise con los conceptos (ej: y - 30)
        y_pago = y - 30 if 'y' in locals() else 150 
        
        # Texto con el nombre descriptivo del método de pago elegido
        texto_pago = f"Forma de pago: {metodo_pago.nombre}"
        content_parts.append(pdf_text(50, y_pago, texto_pago, 9)) # Margen izquierdo X=50
        
        # Si tiene un IBAN o número de cuenta asociado, lo pintamos una línea más abajo
        # Validamos dinámicamente si el atributo es 'cuenta_iban' o 'iban' según tu modelo
        iban_valor = getattr(metodo_pago, 'cuenta_iban', None) or getattr(metodo_pago, 'iban', None)
        if iban_valor:
            y_pago -= 12
            texto_iban = f"IBAN: {iban_valor}"
            content_parts.append(pdf_text(50, y_pago, texto_iban, 8))

    content_stream = '\n'.join(content_parts).encode('latin1')
    objects = []
    objects.append(b'1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n')
    objects.append(b'2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n')

    resources = '<< /Font << /F1 4 0 R >>'
    logo_objects = []
    if logo_info:
        resources += ' /XObject << /Im0 6 0 R >>'
        if logo_info['format'] == 'JPEG':
            image_stream = b'stream\n' + logo_info['data'] + b'\nendstream\n'
            logo_objects.append(
                b'6 0 obj\n<< /Type /XObject /Subtype /Image /Width ' + str(logo_info['width']).encode() + b' /Height ' + str(logo_info['height']).encode() + b' /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ' + str(len(logo_info['data'])).encode() + b' >>\n' + image_stream + b'endobj\n'
            )
        else:
            if logo_info['has_alpha']:
                rgb_data, alpha_data = split_png_rgba(logo_info['data'], logo_info['width'], logo_info['height'])
                image_stream = b'stream\n' + zlib.compress(rgb_data) + b'\nendstream\n'
                mask_stream = b'stream\n' + zlib.compress(alpha_data) + b'\nendstream\n'
                logo_objects.append(
                    b'6 0 obj\n<< /Type /XObject /Subtype /Image /Width ' + str(logo_info['width']).encode() + b' /Height ' + str(logo_info['height']).encode() + b' /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /DecodeParms << /Predictor 15 /Colors 3 /BitsPerComponent 8 /Columns ' + str(logo_info['width']).encode() + b' >> /SMask 7 0 R /Length ' + str(len(zlib.compress(rgb_data))).encode() + b' >>\n' + image_stream + b'endobj\n'
                )
                logo_objects.append(
                    b'7 0 obj\n<< /Type /XObject /Subtype /Image /Width ' + str(logo_info['width']).encode() + b' /Height ' + str(logo_info['height']).encode() + b' /ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode /DecodeParms << /Predictor 15 /Colors 1 /BitsPerComponent 8 /Columns ' + str(logo_info['width']).encode() + b' >> /Length ' + str(len(zlib.compress(alpha_data))).encode() + b' >>\n' + mask_stream + b'endobj\n'
                )
            else:
                raw = logo_info['data']
                compressed = zlib.compress(raw)
                logo_objects.append(
                    b'6 0 obj\n<< /Type /XObject /Subtype /Image /Width ' + str(logo_info['width']).encode() + b' /Height ' + str(logo_info['height']).encode() + b' /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /DecodeParms << /Predictor 15 /Colors 3 /BitsPerComponent 8 /Columns ' + str(logo_info['width']).encode() + b' >> /Length ' + str(len(compressed)).encode() + b' >>\n' + b'stream\n' + compressed + b'\nendstream\nendobj\n'
                )
    resources += ' >>'
    objects.append(f'3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources {resources} /Contents 5 0 R >>\n'.encode())
    objects.append(b'4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n')
    stream = b'stream\n' + content_stream + b'\nendstream\n'
    objects.append(b'5 0 obj\n<< /Length ' + str(len(content_stream)).encode() + b' >>\n' + stream + b'endobj\n')
    objects.extend(logo_objects)

    pdf = b'%PDF-1.4\n'
    xref_positions = []
    for obj in objects:
        xref_positions.append(len(pdf))
        pdf += obj
    xref_start = len(pdf)
    pdf += b'xref\n0 ' + str(len(objects) + 1).encode() + b'\n0000000000 65535 f \n'
    for pos in xref_positions:
        pdf += f'{pos:010d} 00000 n \n'.encode()
    pdf += b'trailer\n<< /Size ' + str(len(objects) + 1).encode() + b' /Root 1 0 R >>\nstartxref\n' + str(xref_start).encode() + b'\n%%EOF\n'
    return pdf


@app.route('/presupuestos/previsualizar', methods=['POST'])
def presupuesto_previsualizar():
    cliente_id = request.form.get('contacto_id')
    cliente = Contacto.query.get(cliente_id)
    config = Configuracion.query.first()
    
    if not cliente:
        return "Seleccione un cliente primero", 400
        
    lineas, total_base, total_impuestos, total_presupuesto, _ = parse_presupuesto_lineas(request.form)

    # --- LOGOTIPO ROBUSTO ---
    logo_html = f'<div style="font-size: 20pt; font-weight: bold; color: #d58a1d;">{config.nombre_empresa if config and config.nombre_empresa else "Mi Empresa"}</div>'
    
    if config and config.logo_path:
        logo_path = os.path.join(app.root_path, 'static', 'uploads', os.path.basename(config.logo_path))
        if os.path.exists(logo_path):
            try:
                with open(logo_path, "rb") as image_file:
                    encoded = base64.b64encode(image_file.read()).decode('utf-8')
                    logo_html = f'<img src="data:image/png;base64,{encoded}" width="150" />'
            except Exception:
                pass
    
    # Construcción de líneas (igual que en factura_descargar)
    lineas_html = ""
    for item in lineas:
        lineas_html += f"""
        <tr>
            <td style="padding: 6px 10px; font-size: 9pt; border-bottom: 1px solid #e5e7eb;">{item.get('concepto', 'Concepto')}</td>
            <td style="padding: 6px 10px; font-size: 9pt; text-align: right; border-bottom: 1px solid #e5e7eb;">{item.get('unidades', 1)}</td>
            <td style="padding: 6px 10px; font-size: 9pt; text-align: right; border-bottom: 1px solid #e5e7eb;">{float(item.get('precio_ud', 0)):.2f} €</td>
            <td style="padding: 6px 10px; font-size: 9pt; text-align: right; border-bottom: 1px solid #e5e7eb;">{item.get('impuesto', '21%')}</td>
            <td style="padding: 6px 10px; font-size: 9pt; text-align: right; font-weight: bold; border-bottom: 1px solid #e5e7eb;">{float(item.get('total', 0)):.2f} €</td>
        </tr>"""

    # HTML Completo con datos de empresa y cliente
    html_content = f"""
    <html>
    <head><style>
        body {{ font-family: Helvetica; font-size: 11pt; }}
        .header-table, .details-table {{ width: 100%; margin-bottom: 20px; }}
        .logo-container {{ width: 50%; text-align: left; vertical-align: top; }}
        .details-box {{ width: 48%; vertical-align: top; }}
        .box-title {{ font-size: 10pt; color: #6b7280; text-transform: uppercase; font-weight: bold; }}
        .concepts-table {{ width: 100%; border-collapse: collapse; }}
        .concepts-table th {{ background-color: #f3f4f6; padding: 5px; text-align: left; border-bottom: 2px solid #d1d5db; }}
    </style></head>
    <body>
        <table class="header-table">
            <tr>
                <td style="width: 15%; text-align: left; vertical-align: top;">
                    {logo_html}
                </td>
                
                <td style="width: 80%; text-align: right; vertical-align: top;">
                    <h1 style="color: #d58a1d; margin: 0;">PRESUPUESTO</h1>
                    <strong>Nº:</strong> {request.form.get('numero_presupuesto')}<br>
                    <strong>Fecha:</strong> {request.form.get('fecha_emision')}<br>
                    <strong>Validez:</strong> {request.form.get('fecha_validez')}
                </td>
            </tr>
        </table>

        <table class="details-table">
            <tr>
                <td class="details-box">
                    <div class="box-title">Emisor</div>
                    <strong>{config.nombre_empresa if config else ''}</strong><br>
                    CIF/NIF:{config.cif_nif if config else ''}<br>
                    {config.direccion_fiscal if config else ''}<br>
                    {config.codigo_postal if config else ''} {config.ciudad if config else ''}<br>
                    {config.provincia if config else ''}<br>
                    {config.telefono if config else ''}<br> 
                    {config.email if config else ''}<br>
                </td>
                <td class="details-box">
                    <div class="box-title">Cliente</div>
                    <strong>{cliente.nombre_fiscal}</strong><br>
                    CIF/NIF: {cliente.numero_documento}<br>
                    {cliente.direccion_fiscal}<br>
                    {cliente.codigo_postal} {cliente.ciudad}<br>
                    {cliente.provincia}<br>


                </td>
            </tr>
        </table>

        <table class="concepts-table">
            <thead><tr><th>Concepto</th><th>Uds.</th><th>Precio</th><th>Impuesto</th><th>Total</th></tr></thead>
            <tbody>{lineas_html}</tbody>
        </table>

        <div style="text-align: right; margin-top: 20px;">
            <p>Base Imponible: {total_base:.2f} €</p>
            <p>Impuestos: {total_impuestos:.2f} €</p>
            <h2 style="color: #1a2232;">TOTAL: {total_presupuesto:.2f} €</h2>
        </div>
    </body>
    </html>
    """

    pdf_buffer = io.BytesIO()
    pisa.CreatePDF(io.StringIO(html_content), dest=pdf_buffer)
    pdf_buffer.seek(0)
    
    response = make_response(pdf_buffer.read())
    response.headers['Content-Type'] = 'application/pdf'
    return response


def generate_invoice_number():
    year = datetime.now().year
    configuracion = Configuracion.query.first()
    prefix = configuracion.serie_factura if configuracion and configuracion.serie_factura else f'F{str(year)[-2:]}-'
    initial = getattr(configuracion, 'numero_inicial_factura', None) or 1
    if not prefix.endswith('-'):
        prefix = f'{prefix}-'
    
    # CAMBIO CLAVE: Ordenamos por el propio campo 'numero_factura' de forma descendente, NO por 'id'
    last = Factura.query.filter(
        Factura.numero_factura.like(f'{prefix}%')
    ).order_by(Factura.numero_factura.desc()).first()
    
    if last and '-' in last.numero_factura:
        try:
            last_num = int(last.numero_factura.split('-')[-1])
        except ValueError:
            last_num = initial - 1
    else:
        last_num = initial - 1
        
    return f'{prefix}{last_num + 1:03d}'


def generate_budget_number():
    year = datetime.now().year
    prefix = f'PR-{year}-'
    last = Presupuesto.query.filter(Presupuesto.numero_presupuesto.like(f'{prefix}%')).order_by(Presupuesto.id.desc()).first()
    if last and '-' in last.numero_presupuesto:
        try:
            last_num = int(last.numero_presupuesto.split('-')[-1])
        except ValueError:
            last_num = 0
    else:
        last_num = 0
    return f'{prefix}{last_num + 1:03d}'


def ensure_login():
    if not session.get('user_id') and request.endpoint not in ('login', 'static'):
        return redirect(url_for('login'))


@app.before_request
def require_login():
    if request.endpoint and request.endpoint != 'static' and request.endpoint != 'login':
        if not session.get('user_id'):
            return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        # Buscamos al usuario únicamente por su nombre de usuario
        user = User.query.filter_by(username=username).first()
        
        # Verificamos si el usuario existe y si el hash de la contraseña coincide
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['username'] = user.username
            flash('Sesión iniciada correctamente.', 'success')
            return redirect(url_for('facturas'))
        else:
            flash('Usuario o contraseña incorrectos.', 'danger')
            
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('Sesión cerrada', 'info')
    return redirect(url_for('login'))


@app.route('/')
def index():
    return redirect(url_for('facturas'))


@app.route('/contactos')
def contactos():
    tipo = request.args.get('tipo', 'Cliente')
    query = Contacto.query
    if tipo in ['Cliente', 'Proveedor']:
        query = query.filter(Contacto.tipo_contacto == tipo)
    busqueda = request.args.get('q', '').strip()
    if busqueda:
        query = query.filter((Contacto.nombre_fiscal.ilike(f'%{busqueda}%')) | (Contacto.numero_documento.ilike(f'%{busqueda}%')))
    contactos = query.order_by(Contacto.nombre_fiscal).all()
    current_year = date.today().year
    for contacto in contactos:
        facturas_year = [f for f in contacto.facturas if f.fecha_factura and f.fecha_factura.year == current_year]
        contacto.total_facturado = sum([float(f.total_factura) for f in facturas_year if f.estado_pago == 'Cobrada'])
        contacto.total_pendiente = sum([float(f.total_factura) for f in facturas_year if f.estado_pago != 'Cobrada'])
        fechas = [f.fecha_factura for f in contacto.facturas if f.fecha_factura] + [g.fecha_factura for g in contacto.gastos if g.fecha_factura]
        contacto.ultimo_documento = max(fechas).strftime('%Y-%m-%d') if fechas else '-'
    return render_template('contactos.html', contactos=contactos, tipo=tipo, busqueda=busqueda)


@app.route('/contactos/nuevo', methods=['GET', 'POST'])
def contacto_nuevo():
    if request.method == 'POST':
        contact = Contacto(
            nombre_fiscal=request.form.get('nombre_fiscal', '').strip(),
            tipo_documento=request.form.get('tipo_documento', 'NIF/CIF'),
            numero_documento=request.form.get('numero_documento', '').strip(),
            tipo_contacto=request.form.get('tipo_contacto', 'Cliente'),
            email_principal=request.form.get('email_principal', '').strip(),
            emails_adicionales=request.form.get('emails_adicionales', '').strip(),
            telefono=request.form.get('telefono', '').strip(),
            direccion_fiscal=request.form.get('direccion_fiscal', '').strip(),
            codigo_postal=request.form.get('codigo_postal', '').strip(),
            ciudad=request.form.get('ciudad', '').strip(),
            provincia=request.form.get('provincia', '').strip(),
            pais=request.form.get('pais', 'España').strip(),
            impuesto_defecto=request.form.get('impuesto_defecto', '21% IVA'),
            recargo_equivalencia=bool(request.form.get('recargo_equivalencia')),
            notas=request.form.get('notas', '').strip(),
        )
        if not contact.nombre_fiscal or not contact.numero_documento:
            flash('Nombre fiscal y número de documento son obligatorios', 'danger')
        else:
            db.session.add(contact)
            db.session.commit()
            flash('Contacto añadido', 'success')
            return redirect(url_for('contactos'))
    return render_template('contacto_form.html')


@app.route('/contactos/<int:contacto_id>/editar', methods=['GET', 'POST'])
def contacto_editar(contacto_id):
    contact = Contacto.query.get_or_404(contacto_id)
    if request.method == 'POST':
        contact.nombre_fiscal = request.form.get('nombre_fiscal', '').strip()
        contact.tipo_documento = request.form.get('tipo_documento', 'NIF/CIF')
        contact.numero_documento = request.form.get('numero_documento', '').strip()
        contact.tipo_contacto = request.form.get('tipo_contacto', 'Cliente')
        contact.email_principal = request.form.get('email_principal', '').strip()
        contact.emails_adicionales = request.form.get('emails_adicionales', '').strip()
        contact.telefono = request.form.get('telefono', '').strip()
        contact.direccion_fiscal = request.form.get('direccion_fiscal', '').strip()
        contact.codigo_postal = request.form.get('codigo_postal', '').strip()
        contact.ciudad = request.form.get('ciudad', '').strip()
        contact.provincia = request.form.get('provincia', '').strip()
        contact.pais = request.form.get('pais', 'España').strip()
        contact.impuesto_defecto = request.form.get('impuesto_defecto', '21% IVA')
        contact.recargo_equivalencia = bool(request.form.get('recargo_equivalencia'))
        contact.notas = request.form.get('notas', '').strip()
        if not contact.nombre_fiscal or not contact.numero_documento:
            flash('Nombre fiscal y número de documento son obligatorios', 'danger')
        else:
            db.session.commit()
            flash('Contacto actualizado', 'success')
            return redirect(url_for('contactos'))
    return render_template('contacto_form.html', contact=contact)


@app.route('/facturas')
def facturas():
    pestana = request.args.get('pestana', 'Emitida')
    query = Factura.query
    if pestana in ['Emitida', 'Recurrente', 'Borrador']:
        query = query.filter(Factura.tipo_pestana == pestana)
    search = request.args.get('q', '').strip()
    if search:
        query = query.join(Contacto).filter((Factura.numero_factura.ilike(f'%{search}%')) | (Contacto.nombre_fiscal.ilike(f'%{search}%')) | (Factura.referencia.ilike(f'%{search}%')))
    facturas = query.order_by(Factura.fecha_factura.desc()).all()
    return render_template('facturas.html', facturas=facturas, pestana=pestana, search=search)


@app.route('/facturas/crear', methods=['GET', 'POST'])
def factura_crear():
    contactos = Contacto.query.order_by(Contacto.nombre_fiscal).all()
    productos = Producto.query.order_by(Producto.nombre).all()
    metodos_pago = MetodoPago.query.all()
    configuracion = Configuracion.query.first()
    if request.method == 'POST':
        cliente_id = request.form.get('contacto_id')
        cliente_id = int(cliente_id) if cliente_id and cliente_id.isdigit() else None
        fecha_factura = request.form.get('fecha_factura')
        fecha_vencimiento = request.form.get('fecha_vencimiento')
        referencia = request.form.get('referencia', '').strip()
        metodo_pago_id = request.form.get('metodo_pago_id')
        selected_metodo_pago_id = int(metodo_pago_id) if metodo_pago_id and metodo_pago_id.isdigit() else None
        pestana = 'Borrador' if request.form.get('guardar_borrador') else 'Emitida'
        cliente = Contacto.query.get(cliente_id)
        if not cliente:
            flash('Debe seleccionar un cliente válido', 'danger')
            return render_template('factura_form.html', contactos=contactos, productos=productos, metodos_pago=metodos_pago, configuracion=configuracion, numero_factura=request.form.get('numero_factura', '').strip() or generate_invoice_number(), lineas=[], selected_contacto_id=cliente_id, selected_metodo_pago_id=selected_metodo_pago_id)
        numero_factura = request.form.get('numero_factura', '').strip() or generate_invoice_number()
        if Factura.query.filter_by(numero_factura=numero_factura).first():
            flash('Ya existe una factura con ese número.', 'danger')
            return render_template('factura_form.html', contactos=contactos, productos=productos, metodos_pago=metodos_pago, configuracion=configuracion, numero_factura=numero_factura, lineas=[], selected_contacto_id=cliente_id, selected_metodo_pago_id=selected_metodo_pago_id)
        lineas = []
        total_base = Decimal('0')
        total_iva = Decimal('0')
        total_recargo = Decimal('0')
        line_count = 0
        try:
            line_count = int(request.form.get('lineas_count', '0') or '0')
        except ValueError:
            line_count = 0
        if line_count < 1:
            line_count = 5
        for index in range(1, line_count + 1):
            concepto = request.form.get(f'concepto_{index}', '').strip()
            if not concepto:
                continue
            unidades = Decimal(request.form.get(f'unidades_{index}', '1') or '1')
            precio = Decimal(request.form.get(f'precio_{index}', '0') or '0')
            impuesto = request.form.get(f'impuesto_{index}', cliente.impuesto_defecto or '0% Exento')
            impuesto_text = impuesto.strip()
            if not impuesto_text:
                impuesto_text = '0% Exento'
            if 'exento' in impuesto_text.lower():
                porcentaje = Decimal('0')
            else:
                porcentaje_text = impuesto_text.split('%', 1)[0].strip()
                porcentaje = Decimal(porcentaje_text or '0')
            linea_base = (unidades * precio).quantize(Decimal('0.01'))
            iva = (linea_base * porcentaje / Decimal('100')).quantize(Decimal('0.01'))
            total_linea = (linea_base + iva).quantize(Decimal('0.01'))
            informacion = request.form.get(f'informacion_{index}', '').strip()
            lineas.append({'concepto': concepto, 'unidades': str(unidades), 'precio': str(precio), 'impuesto': impuesto, 'total': str(total_linea), 'informacion': informacion})
            total_base += linea_base
            total_iva += iva
        if not lineas:
            flash('Debes añadir al menos una línea de concepto para crear la factura.', 'danger')
            return render_template('factura_form.html', contactos=contactos, productos=productos, metodos_pago=metodos_pago, configuracion=configuracion, numero_factura=numero_factura, lineas=[], selected_contacto_id=cliente_id, selected_metodo_pago_id=selected_metodo_pago_id)
        recargo = cliente.recargo_equivalencia and pestana != 'Borrador'
        recargo_total = (total_base * Decimal('5.20') / Decimal('100')).quantize(Decimal('0.01')) if recargo else Decimal('0.00')
        total_factura = (total_base + total_iva + recargo_total).quantize(Decimal('0.01'))
        factura = Factura(
            numero_factura=numero_factura,
            tipo_pestana=pestana,
            contacto_id=cliente.id,
            referencia=referencia,
            fecha_factura=datetime.strptime(fecha_factura, '%Y-%m-%d').date() if fecha_factura else date.today(),
            fecha_vencimiento=datetime.strptime(fecha_vencimiento, '%Y-%m-%d').date() if fecha_vencimiento else None,
            porcentaje_iva=Decimal('21.00'),
            total_base_imponible=total_base,
            total_cuota_iva=total_iva,
            total_recargo_equivalencia=recargo_total,
            total_factura=total_factura,
            estado_pago='Emitida' if pestana != 'Borrador' else 'Borrador',
            linea_items=json.dumps(lineas),
            metodo_pago_id=int(metodo_pago_id) if metodo_pago_id else None
        )
        db.session.add(factura)
        db.session.commit()
        flash('Factura creada', 'success')
        return redirect(url_for('facturas'))
    default_numero = generate_invoice_number()
    return render_template('factura_form.html', contactos=contactos, productos=productos, metodos_pago=metodos_pago, numero_factura=default_numero, configuracion=configuracion, lineas=[])


@app.route('/facturas/<int:factura_id>/duplicar', methods=['POST'])
def factura_duplicar(factura_id):
    original = Factura.query.get_or_404(factura_id)
    nuevo_numero = generate_invoice_number()
    nueva = Factura(
        numero_factura=nuevo_numero,
        tipo_pestana='Borrador',
        contacto_id=original.contacto_id,
        referencia=original.referencia,
        fecha_factura=date.today(),
        fecha_vencimiento=original.fecha_vencimiento,
        porcentaje_iva=original.porcentaje_iva,
        total_base_imponible=original.total_base_imponible,
        total_cuota_iva=original.total_cuota_iva,
        total_recargo_equivalencia=original.total_recargo_equivalencia,
        total_factura=original.total_factura,
        estado_pago='Borrador',
        linea_items=original.linea_items,
        metodo_pago_id=original.metodo_pago_id
    )
    db.session.add(nueva)
    db.session.commit()
    return jsonify({'new_id': nueva.id, 'new_numero': nueva.numero_factura})


@app.route('/facturas/<int:factura_id>/cobrar', methods=['POST'])
def factura_cobrar(factura_id):
    factura = Factura.query.get_or_404(factura_id)
    factura.estado_pago = 'Cobrada'
    db.session.commit()
    return jsonify({'status': 'ok', 'estado_pago': factura.estado_pago})


import io
from xhtml2pdf import pisa
from flask import make_response
import json
import base64

@app.route('/facturas/<int:id>/descargar')
def factura_descargar(id):
    # Sintaxis moderna de SQLAlchemy 2.0
    factura = db.session.get(Factura, id)
    if not factura:
        abort(404)
        
    config = Configuracion.query.first()
    cliente = db.session.get(Contacto, factura.contacto_id)

    # --- PROCESAR LOGOTIPO PARA PDF ---
    logo_base64 = ""
    logo_path = config.logo_path if config and config.logo_path else ""
    
    if logo_path:
        filename = os.path.basename(logo_path)
        posible_path = os.path.join(app.root_path, 'static', 'uploads', filename)
        
        if os.path.exists(posible_path) and os.path.isfile(posible_path):
            logo_path = posible_path
        else:
            logo_path = os.path.join(app.root_path, 'static', filename)
    else:
        logo_path = os.path.join(app.root_path, 'static', 'logo.png')

    if os.path.exists(logo_path) and os.path.isfile(logo_path):
        try:
            with open(logo_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                ext = os.path.splitext(logo_path)[1].lower().replace('.', '')
                if ext not in ['png', 'jpg', 'jpeg', 'gif']: ext = 'png'
                logo_base64 = f"data:image/{ext};base64,{encoded_string}"
        except Exception:
            logo_base64 = ""
    
    # Obtener el método de pago asignado (Sintaxis corregida SQLAlchemy 2.0 para evitar LegacyAPIWarning)
    metodo_pago = None
    if hasattr(factura, 'metodo_pago_id') and factura.metodo_pago_id:
        metodo_pago = db.session.get(MetodoPago, factura.metodo_pago_id)
    elif hasattr(factura, 'metodo_pago') and factura.metodo_pago:
        metodo_pago = factura.metodo_pago

    # Variables para detectar el tipo de IVA dinámicamente desde las líneas
    lineas_html = ""
    texto_iva_totales = f"{int(factura.porcentaje_iva)}% IVA"
    
    try:
        lineas_data = factura.lineas_json()
        
        if lineas_data and isinstance(lineas_data, list):
            for item in lineas_data:
                es_titulo = item.get('type') == 'title' or item.get('is_title') or 'title' in item
                
                if es_titulo:
                    titulo_texto = item.get('concepto') or item.get('title') or item.get('line_concepto') or 'Sección'
                    lineas_html += f"""
                    <tr style="background-color: #f9fafb;">
                        <td colspan="5" style="font-weight: bold; color: #374151; padding: 6px 10px; font-size: 9.5pt; border-bottom: 1px solid #e5e7eb;">
                            {titulo_texto}
                        </td>
                    </tr>
                    """
                else:
                    concepto = item.get('concepto') or item.get('line_concepto') or item.get('nombre') or 'Concepto general'
                    informacion_adicional = item.get('informacion') or item.get('informacion_adicional') or item.get('line_informacion') or ''
                    
                    try:
                        unidades = float(item.get('unidades') or item.get('line_unidades') or 1)
                    except (ValueError, TypeError):
                        unidades = 1.0
                        
                    try:
                        precio_ud = float(item.get('precio_ud') or item.get('line_precio') or item.get('precio') or 0)
                    except (ValueError, TypeError):
                        precio_ud = 0.0
                        
                    try:
                        total_item = float(item.get('total') or item.get('line_total') or (unidades * precio_ud))
                    except (ValueError, TypeError):
                        total_item = unidades * precio_ud
                        
                    impuesto_item = item.get('impuesto') or item.get('line_impuesto') or f"{int(factura.porcentaje_iva)}% IVA"
                    
                    if impuesto_item:
                        texto_iva_totales = impuesto_item
                        
                    unidades_formateadas = f"{unidades:g}"
                    
                    # --- CONSTRUIR EL CONTENIDO DE LA CELDA DE CONCEPTO ---
                    # Reducimos los tamaños de fuente (9pt para el concepto, 8pt para la info adicional)
                    if informacion_adicional:
                        informacion_formateada = informacion_adicional.replace('\n', '<br>')
                        html_celda_concepto = f"""
                        <span style="font-weight: bold; font-size: 9pt; display: inline;">{concepto}</span><br>
                        <span style="font-size: 8pt; color: #6b7280; font-style: italic; font-weight: normal; line-height: 1.1;">{informacion_formateada}</span>
                        """
                    else:
                        html_celda_concepto = f"<span style='font-weight: bold; font-size: 9pt;'>{concepto}</span>"
                    
                    # Estilo base común: Bajamos el tamaño global a 9pt y el padding a 6px para compactar
                    estilo_celda = "padding: 6px 10px; font-size: 9pt; vertical-align: center; border-bottom: 1px solid #e5e7eb;"
                    
                    # Ajuste estratégico de los anchos (Concepto sube al 50% y los precios se optimizan)
                    lineas_html += f"""
                    <tr>
                        <td style="{estilo_celda} width: 50%;">{html_celda_concepto}</td>
                        <td style="{estilo_celda} text-align: right; width: 8%;">{unidades_formateadas}</td>
                        <td style="{estilo_celda} text-align: right; width: 14%;">{precio_ud:.2f} €</td>
                        <td style="{estilo_celda} text-align: right; color: #4b5563; width: 14%;">{impuesto_item}</td>
                        <td style="{estilo_celda} text-align: right; font-weight: bold; width: 14%;">{total_item:.2f} €</td>
                    </tr>
                    """
        else:
            raise ValueError("Las líneas están vacías")
            
    except Exception as e:
        lineas_html = f"""
        <tr>
            <td style="padding: 10px; border-bottom: 1px solid #e5e7eb; font-size: 10pt;">Servicios profesionales (Ref: {factura.referencia or 'S/R'})</td>
            <td style="padding: 10px; border-bottom: 1px solid #e5e7eb; text-align: right; font-size: 10pt;">1</td>
            <td style="padding: 10px; border-bottom: 1px solid #e5e7eb; text-align: right; font-size: 10pt;">{float(factura.total_base_imponible):.2f} €</td>
            <td style="padding: 10px; border-bottom: 1px solid #e5e7eb; text-align: right; font-size: 10pt; color: #4b5563;">{texto_iva_totales}</td>
            <td style="padding: 10px; border-bottom: 1px solid #e5e7eb; text-align: right; font-size: 10pt; font-weight: bold;">{float(factura.total_base_imponible):.2f} €</td>
        </tr>
        """

    # Construcción de la plantilla HTML limpia para xhtml2pdf
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            @page {{
                size: A4;
                margin: 2cm;
            }}
            body {{
                font-family: Helvetica, Arial, sans-serif;
                color: #1a2232;
                font-size: 11pt;
                line-height: 1.5;
            }}
            .header-table {{
                width: 100%;
                margin-bottom: 30px;
            }}
            .logo-container {{
                width: 15%;
                vertical-align: top;
                text-align: left;
            }}
            .invoice-title {{
                font-size: 18pt;
                font-weight: bold;
                text-align: right;
                color: #1a2232;
            }}
            .details-table {{
                width: 100%;
                margin-bottom: 40px;
            }}
            .details-box {{
                width: 48%;
                vertical-align: top;
            }}
            .box-title {{
                font-size: 10pt;
                color: #6b7280;
                text-transform: uppercase;
                margin-bottom: 5px;
                font-weight: bold;
            }}
            .concepts-table {{
                width: 100%;
                border-collapse: collapse;
                margin-bottom: 10px;
            }}
            .concepts-table th {{
                background-color: #f3f4f6;
                color: #1a2232;
                font-weight: bold;
                text-align: left;
                padding: 5px;
                font-size: 10pt;
                border-bottom: 2px solid #d1d5db;
            }}
            .payment-box {{
                font-size: 10pt;
                color: #4b5563;
                margin-top: 15px;
                line-height: 1.4;
            }}
            .totals-table {{
                width: 45%;
                margin-bottom: 30px;
            }}
            .totals-table td {{
                padding: 6px 10px;
            }}
            .total-row {{
                font-size: 13pt;
                font-weight: bold;
                background-color: #f8fafc;
            }}
            .footer-note {{
                margin-top: 60px;
                font-size: 8pt;
                color: #6b7280;
                text-align: center;
                border-top: 1px solid #e5e7eb;
                padding-top: 15px;
                line-height: 1.4;
            }}
        </style>
    </head>
    <body>
        <table class="header-table" style="width: 100%;">
            <tr>
                <td class="logo-container">
                    {f'<img src="{logo_base64}" width="150" style="display: block; margin-bottom: 8px;" />' if logo_base64 else f'<div class="logo-title" style="font-size: 20pt; font-weight: bold; color: #d58a1d; margin-bottom: 8px;">{config.nombre_empresa if config and config.nombre_empresa else "AutoFactura"}</div>'}
                    
                </td>
                
                <td style="width: 80%; text-align: right; vertical-align: top;">
                    <span class="invoice-title" style="display: block;">FACTURA</span>
                    <span style="font-size: 10.5pt; line-height: 1.4; display: block;">
                        <strong>Número:</strong> {factura.numero_factura}
                        <strong> Fecha:</strong> {factura.fecha_factura.strftime('%d/%m/%Y') if factura.fecha_factura else ''}<br>
                        {f"<strong>Referencia:</strong> {factura.referencia}<br>" if factura.referencia else ""}
                    </span>
                </td>
            </tr>
        </table>

        <table class="details-table">
            <tr>
                <td class="details-box">
                    <div class="box-title">Emisor</div>
                    <strong>{config.nombre_empresa if config and config.nombre_empresa else ''}</strong><br>
                    <span>CIF/NIF: {config.cif_nif if config and config.cif_nif else ''}</span><br>
                    {config.direccion_fiscal if config and config.direccion_fiscal else ''}<br>
                    {config.codigo_postal if config and config.codigo_postal else ''} {config.ciudad if config and config.ciudad else ''}<br>
                    {config.email if config and config.email else ''}<br>
                    {config.telefono if config and config.telefono else ''}
                </td>
                <td style="width: 4%;"></td>
                <td class="details-box">
                    <div class="box-title">Cliente</div>
                    <strong>{cliente.nombre_fiscal if cliente else 'Cliente General'}</strong><br>
                    <span>CIF/NIF: {cliente.numero_documento if cliente else ''}</span><br>
                    {cliente.direccion_fiscal if cliente else ''}<br>
                    {cliente.codigo_postal if cliente else ''} {cliente.ciudad if cliente else ''}
                    {cliente.email_principal if cliente else ''}<br>
                    {cliente.telefono if cliente else ''}
                </td>
            </tr>
        </table>

        <table class="concepts-table">
            <thead>
                <tr>
                    <th style="width: 45%;">Concepto / Descripción</th>
                    <th style="text-align: right; width: 10%;">Uds.</th>
                    <th style="text-align: right; width: 15%;">Precio</th>
                    <th style="text-align: right; width: 15%;">Impuestos</th>
                    <th style="text-align: right; width: 15%;">Total</th>
                </tr>
            </thead>
            <tbody>
                {lineas_html}
            </tbody>
        </table>

        <table style="width: 100%; margin-top: 10px;">
            <tr>
                <td style="width: 55%; vertical-align: top;">
                    <div class="payment-box">
                        <strong>Método de pago:</strong><br>
                        {metodo_pago.nombre if metodo_pago else 'A convenir / Transferencia Bancaria'}<br>
                        <span style="font-size: 9pt; color: #6b7280;">
                            {f"{metodo_pago.entidad or ''}</br>{metodo_pago.cuenta_iban or ''}".strip() if metodo_pago else ''}</br></br>
                            {config.nota_legal if config and config.nota_legal else 'Factura generada automáticamente mediante el sistema AutoFactura de acuerdo con la normativa fiscal vigente.'}
                        </span>
                    </div>
                </td>
                <td style="width: 45%; vertical-align: top;">
                    <table class="totals-table" style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="font-size: 10pt; color: #4b5563; padding: 3px 10px; border: none;">Base Imponible:</td>
                            <td style="text-align: right; font-size: 10pt; padding: 3px 10px; border: none;">{float(factura.total_base_imponible):.2f} €</td>
                        </tr>
                        <tr>
                            <td style="font-size: 10pt; color: #4b5563; padding: 3px 10px; border: none;">{texto_iva_totales}:</td>
                            <td style="text-align: right; font-size: 10pt; padding: 3px 10px; border: none;">{float(factura.total_cuota_iva):.2f} €</td>
                        </tr>
                        {f"<tr><td style='font-size: 10pt; color: #4b5563; padding: 3px 10px; border: none;'>Recargo Equiv.:</td><td style='text-align: right; font-size: 10pt; padding: 3px 10px; border: none;'>{float(factura.total_recargo_equivalencia):.2f} €</td></tr>" if hasattr(factura, 'total_recargo_equivalencia') and factura.total_recargo_equivalencia else ""}
                        
                        <tr>
                            <td colspan="2" style="padding: 4px 10px 0 10px;"><div style="border-top: 1px solid #e5e7eb; height: 1px; font-size: 1px;">&nbsp;</div></td>
                        </tr>

                        <tr class="total-row">
                            <td style="padding: 6px 10px; font-weight: bold;">TOTAL:</td>
                            <td style="text-align: right; padding: 6px 10px; color: #1a2232; font-weight: bold;">{float(factura.total_factura):.2f} €</td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>

        <div class="footer-note">
            
        </div>
    </body>
    </html>
    """

    pdf_buffer = io.BytesIO()
    pisa.CreatePDF(io.StringIO(html_content), dest=pdf_buffer)
    pdf_buffer.seek(0)
    
    response = make_response(pdf_buffer.read())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=Factura_{factura.numero_factura}.pdf'
    return response


@app.route('/facturas/<int:factura_id>/eliminar', methods=['POST'])
def factura_eliminar(factura_id):
    factura = Factura.query.get_or_404(factura_id)
    db.session.delete(factura)
    db.session.commit()
    return jsonify({'status': 'ok'})


@app.route('/facturas/<int:factura_id>/editar', methods=['GET', 'POST'])
def factura_editar(factura_id):
    factura = Factura.query.get_or_404(factura_id)
    contactos = Contacto.query.order_by(Contacto.nombre_fiscal).all()
    productos = Producto.query.order_by(Producto.nombre).all()
    metodos_pago = MetodoPago.query.all()
    configuracion = Configuracion.query.first()
    if request.method == 'POST':
        cliente_id = request.form.get('contacto_id')
        cliente_id = int(cliente_id) if cliente_id and cliente_id.isdigit() else None
        fecha_factura = request.form.get('fecha_factura')
        fecha_vencimiento = request.form.get('fecha_vencimiento')
        referencia = request.form.get('referencia', '').strip()
        metodo_pago_id = request.form.get('metodo_pago_id')
        pestana = 'Borrador' if request.form.get('guardar_borrador') else 'Emitida'
        cliente = Contacto.query.get(cliente_id)
        if not cliente:
            flash('Debe seleccionar un cliente válido', 'danger')
            return render_template('factura_form.html', contactos=contactos, productos=productos, configuracion=configuracion, edit_mode=True, lineas=factura.lineas_json(), selected_contacto_id=factura.contacto_id)
        numero_factura = request.form.get('numero_factura', '').strip() or factura.numero_factura
        existing = Factura.query.filter(Factura.numero_factura == numero_factura, Factura.id != factura.id).first()
        if existing:
            flash('Ya existe una factura con ese número.', 'danger')
            return render_template('factura_form.html', contactos=contactos, productos=productos, configuracion=configuracion, edit_mode=True, lineas=factura.lineas_json(), selected_contacto_id=factura.contacto_id)
        lineas = []
        total_base = Decimal('0')
        total_iva = Decimal('0')
        line_count = 0
        try:
            line_count = int(request.form.get('lineas_count', '0') or '0')
        except ValueError:
            line_count = 0
        if line_count < 1:
            line_count = 5
        for index in range(1, line_count + 1):
            concepto = request.form.get(f'concepto_{index}', '').strip()
            if not concepto:
                continue
            unidades = Decimal(request.form.get(f'unidades_{index}', '1') or '1')
            precio = Decimal(request.form.get(f'precio_{index}', '0') or '0')
            impuesto = request.form.get(f'impuesto_{index}', cliente.impuesto_defecto or '0% Exento')
            porcentaje = parse_impuesto_porcentaje(impuesto)
            linea_base = (unidades * precio).quantize(Decimal('0.01'))
            iva = (linea_base * porcentaje / Decimal('100')).quantize(Decimal('0.01'))
            total_linea = (linea_base + iva).quantize(Decimal('0.01'))
            informacion = request.form.get(f'informacion_{index}', '').strip()
            lineas.append({'concepto': concepto, 'unidades': str(unidades), 'precio': str(precio), 'impuesto': impuesto, 'total': str(total_linea), 'informacion': informacion})
            total_base += linea_base
            total_iva += iva
        if not lineas:
            flash('Debes añadir al menos una línea de concepto para crear la factura.', 'danger')
            return render_template('factura_form.html', contactos=contactos, productos=productos, configuracion=configuracion, edit_mode=True, lineas=factura.lineas_json(), selected_contacto_id=factura.contacto_id)
        recargo = cliente.recargo_equivalencia and pestana != 'Borrador'
        recargo_total = (total_base * Decimal('5.20') / Decimal('100')).quantize(Decimal('0.01')) if recargo else Decimal('0.00')
        total_factura = (total_base + total_iva + recargo_total).quantize(Decimal('0.01'))
        factura.numero_factura = numero_factura
        factura.tipo_pestana = pestana
        factura.contacto_id = cliente.id
        factura.referencia = referencia
        factura.fecha_factura = datetime.strptime(fecha_factura, '%Y-%m-%d').date() if fecha_factura else date.today()
        factura.fecha_vencimiento = datetime.strptime(fecha_vencimiento, '%Y-%m-%d').date() if fecha_vencimiento else None
        factura.porcentaje_iva = Decimal('21.00')
        factura.total_base_imponible = total_base
        factura.total_cuota_iva = total_iva
        factura.total_recargo_equivalencia = recargo_total
        factura.total_factura = total_factura
        factura.estado_pago = 'Emitida' if pestana != 'Borrador' else 'Borrador'
        factura.linea_items = json.dumps(lineas)
        factura.metodo_pago_id = int(metodo_pago_id) if metodo_pago_id else None
        db.session.commit()
        flash('Factura actualizada', 'success')
        return redirect(url_for('facturas'))
    lineas = factura.lineas_json()
    return render_template(
        'factura_form.html',
        contactos=contactos,
        productos=productos,
        metodos_pago=metodos_pago,
        numero_factura=factura.numero_factura,
        configuracion=configuracion,
        referencia=factura.referencia,
        fecha_factura=factura.fecha_factura.isoformat(),
        fecha_vencimiento=factura.fecha_vencimiento.isoformat() if factura.fecha_vencimiento else '',
        selected_contacto_id=factura.contacto_id,
        selected_metodo_pago_id=factura.metodo_pago_id,
        lineas=lineas,
        edit_mode=True,
    )


@app.route('/gastos')
def gastos():
    pestana = request.args.get('pestana', 'Recibida')
    query = Gasto.query
    if pestana in ['Recibida', 'Pagada', 'A revisar']:
        query = query.filter(Gasto.estado_pago == pestana)
    search = request.args.get('q', '').strip()
    if search:
        query = query.join(Contacto).filter((Gasto.numero_factura_proveedor.ilike(f'%{search}%')) | (Contacto.nombre_fiscal.ilike(f'%{search}%')))
    gastos = query.order_by(Gasto.fecha_factura.desc()).all()
    return render_template('gastos.html', gastos=gastos, pestana=pestana, search=search)


@app.route('/gastos/subir', methods=['GET', 'POST'])
def gasto_subir():
    # Obtener contactos para el selector
    contactos = Contacto.query.order_by(Contacto.nombre_fiscal).all()
    
    if request.method == 'POST':
        # 1. Capturar el ID del contacto seleccionado en el nuevo <select>
        contacto_id = request.form.get('contacto_id')
        
        # 2. Capturar el resto de datos
        num_fact = request.form.get('numero_factura_proveedor', '').strip()
        referencia = request.form.get('referencia', '').strip()
        tipo_gasto = request.form.get('tipo_gasto', 'Gasto operativa')
        fecha_factura = request.form.get('fecha_factura')
        fecha_vencimiento = request.form.get('fecha_vencimiento')
        base = Decimal(request.form.get('base_imponible', '0') or '0')
        porcentaje_iva = Decimal(request.form.get('porcentaje_iva', '21') or '0')
        importe_impuesto = Decimal(request.form.get('importe_impuesto', '0') or '0')
        porcentaje_retencion = Decimal(request.form.get('porcentaje_retencion', '0') or '0')
        importe_retencion = Decimal(request.form.get('importe_retencion', '0') or '0')
        total_factura = Decimal(request.form.get('total_factura', '0') or '0')

        # 3. Manejo del archivo
        archivo = request.files.get('documento')
        nombre_archivo = None
        if archivo and archivo.filename:
            if allowed_file(archivo.filename):
                safe_name = secure_filename(archivo.filename)
                local_path = os.path.join(app.root_path, 'static', 'uploads')
                os.makedirs(local_path, exist_ok=True)
                archivo.save(os.path.join(local_path, safe_name))
                nombre_archivo = os.path.join('uploads', safe_name)

        # 4. Crear el gasto
        gasto = Gasto(
            numero_factura_proveedor=num_fact,
            contacto_id=request.form.get('contacto_id'),
            referencia=referencia,
            tipo_gasto=tipo_gasto,
            fecha_factura=datetime.strptime(fecha_factura, '%Y-%m-%d').date() if fecha_factura else date.today(),
            fecha_vencimiento=datetime.strptime(fecha_vencimiento, '%Y-%m-%d').date() if fecha_vencimiento else None,
            base_imponible=base,
            porcentaje_iva=porcentaje_iva,
            importe_impuesto=importe_impuesto,
            porcentaje_retencion=porcentaje_retencion,
            importe_retencion=importe_retencion,
            total_factura=total_factura,
            estado_pago='Recibida',
            ruta_adjunto_url=nombre_archivo
        )
        db.session.add(gasto)
        db.session.commit()
        flash('Gasto registrado exitosamente', 'success')
        return redirect(url_for('gastos'))

    return render_template('gasto_form.html', contactos=contactos, gasto=None)


@app.route('/gastos/<int:gasto_id>/editar', methods=['GET', 'POST'])
def gasto_editar(gasto_id):
    gasto = Gasto.query.get_or_404(gasto_id)
    contactos = Contacto.query.order_by(Contacto.nombre_fiscal).all()
    if request.method == 'POST':
        gasto.numero_factura_proveedor = request.form.get('numero_factura_proveedor', '').strip()
        gasto.referencia = request.form.get('referencia', '').strip()
        gasto.tipo_gasto = request.form.get('tipo_gasto', 'Gasto operativa')
        fecha_factura = request.form.get('fecha_factura')
        gasto.fecha_factura = datetime.strptime(fecha_factura, '%Y-%m-%d').date() if fecha_factura else date.today()
        fecha_vencimiento = request.form.get('fecha_vencimiento')
        gasto.fecha_vencimiento = datetime.strptime(fecha_vencimiento, '%Y-%m-%d').date() if fecha_vencimiento else None
        gasto.base_imponible = Decimal(request.form.get('base_imponible', '0') or '0')
        gasto.porcentaje_iva = Decimal(request.form.get('porcentaje_iva', '21') or '0')
        gasto.importe_impuesto = Decimal(request.form.get('importe_impuesto', '0') or '0')
        gasto.porcentaje_retencion = Decimal(request.form.get('porcentaje_retencion', '0') or '0')
        gasto.importe_retencion = Decimal(request.form.get('importe_retencion', '0') or '0')
        gasto.total_factura = Decimal(request.form.get('total_factura', '0') or '0')
        
        nif = request.form.get('nif_cif', '').strip()
        nombre_fiscal = request.form.get('nombre_fiscal', '').strip()
        proveedor_obj = Contacto.query.filter_by(numero_documento=nif).first()
        if not proveedor_obj and nif and nombre_fiscal:
            proveedor_obj = Contacto(nombre_fiscal=nombre_fiscal, numero_documento=nif, tipo_contacto='Proveedor')
            db.session.add(proveedor_obj)
            db.session.commit()
        gasto.contacto_id = proveedor_obj.id if proveedor_obj else gasto.contacto_id

        archivo = request.files.get('documento')
        if archivo and archivo.filename and allowed_file(archivo.filename):
            safe_name = secure_filename(archivo.filename)
            local_path = os.path.join('static', 'uploads')
            os.makedirs(local_path, exist_ok=True)
            archivo.save(os.path.join(local_path, safe_name))
            gasto.ruta_adjunto_url = os.path.join('uploads', safe_name).replace('\\', '/')
            
        db.session.commit()
        flash('Gasto actualizado', 'success')
        return redirect(url_for('gastos'))
    return render_template('gasto_form.html', contactos=contactos, gasto=gasto)


@app.route('/gastos/<int:gasto_id>/eliminar', methods=['POST'])
def gasto_eliminar(gasto_id):
    gasto = Gasto.query.get_or_404(gasto_id)
    db.session.delete(gasto)
    db.session.commit()
    return jsonify({'status': 'ok'})


@app.route('/gastos/<int:gasto_id>/descargar')
def gasto_descargar(gasto_id):
    gasto = Gasto.query.get_or_404(gasto_id)
    # Si el adjunto es un PDF, lo descargamos (redirección al archivo estático)
    if gasto.ruta_adjunto_url and gasto.ruta_adjunto_url.lower().endswith('.pdf'):
        return redirect(url_for('static', filename=gasto.ruta_adjunto_url))
    
    # Si no hay PDF adjunto, avisamos al usuario
    flash('No hay un documento PDF asociado a este gasto para exportar.', 'warning')
    return redirect(url_for('gastos'))

@app.route('/gasto/guardar', methods=['POST'])
def guardar_gasto():
    gasto_id = request.form.get('id')
    
    # 1. Recuperar o crear el gasto de forma segura
    if gasto_id:
        gasto = Gasto.query.get(gasto_id)
        if not gasto:
            flash("Error: Gasto no encontrado.", "danger")
            return redirect(url_for('listado_gastos'))
    else:
        gasto = Gasto()
        db.session.add(gasto)
        db.session.flush() # Reservamos el ID antes de guardar impuestos

    # 2. Procesar campos básicos con validación simple
    gasto.numero_factura_proveedor = request.form.get('numero_factura_proveedor')
    gasto.contacto_id = request.form.get('contacto_id')
    gasto.referencia = request.form.get('referencia')
    gasto.tipo_gasto = request.form.get('tipo_gasto')
    
    # Manejo seguro de fechas
    fecha_fac = request.form.get('fecha_factura')
    if fecha_fac:
        gasto.fecha_factura = datetime.strptime(fecha_fac, '%Y-%m-%d')
        
    fecha_ven = request.form.get('fecha_vencimiento')
    gasto.fecha_vencimiento = datetime.strptime(fecha_ven, '%Y-%m-%d') if fecha_ven else None
    
    # Conversión segura de números
    gasto.porcentaje_retencion = float(request.form.get('porcentaje_retencion') or 0)
    gasto.importe_retencion = float(request.form.get('importe_retencion') or 0)
    gasto.total_factura = float(request.form.get('total_factura') or 0)

    # 3. Guardar Impuestos (Limpiamos los anteriores y creamos los nuevos)
    # Esto elimina la necesidad de comprobar si existe cada impuesto individualmente
    ImpuestoGasto.query.filter_by(gasto_id=gasto.id).delete()
    
    tipos = request.form.getlist('impuesto_tipo[]')
    bases = request.form.getlist('impuesto_base[]')
    cuotas = request.form.getlist('impuesto_cuota[]')

    for i in range(len(tipos)):
        # Solo guardamos si la base o la cuota tienen valor
        base_val = float(bases[i]) if bases[i] else 0.0
        cuota_val = float(cuotas[i]) if cuotas[i] else 0.0
        
        if base_val > 0 or cuota_val > 0:
            imp = ImpuestoGasto(
                gasto_id=gasto.id, 
                tipo=tipos[i], 
                base=base_val, 
                cuota=cuota_val
            )
            db.session.add(imp)

    # 4. Finalizar
    db.session.commit()
    flash("Gasto guardado correctamente.", "success")
    return redirect(url_for('listado_gastos'))

@app.route('/presupuestos')
def presupuestos():
    estado = request.args.get('estado', 'Todos')
    query = Presupuesto.query
    if estado in ['Borrador', 'Enviado', 'Aceptado', 'Rechazado']:
        query = query.filter(Presupuesto.estado == estado)
    presupuestos = query.order_by(Presupuesto.fecha_emision.desc()).all()
    return render_template('presupuestos.html', presupuestos=presupuestos, estado=estado)


def parse_presupuesto_lineas(form):
    try:
        line_count = int(form.get('lineas_count', '0') or '0')
    except ValueError:
        line_count = 0
    if line_count < 1:
        line_count = 5

    lineas = []
    total_base = Decimal('0')
    total_impuestos = Decimal('0')

    for index in range(1, line_count + 1):
        tipo = form.get(f'tipo_{index}', 'linea')
        if tipo == 'titulo':
            texto = form.get(f'titulo_{index}', '').strip()
            if not texto:
                continue
            lineas.append({'tipo': 'titulo', 'texto': texto})
            continue

        concepto = form.get(f'concepto_{index}', '').strip()
        if not concepto:
            continue

        unidades = Decimal(form.get(f'unidades_{index}', '1') or '1')
        precio = Decimal(form.get(f'precio_{index}', '0') or '0')
        descuento = Decimal(form.get(f'descuento_{index}', '0') or '0')
        impuesto = form.get(f'impuesto_{index}', '21% IVA')
        porcentaje = parse_impuesto_porcentaje(impuesto)
        base_bruta = (unidades * precio).quantize(Decimal('0.01'))
        valor_descuento = (base_bruta * descuento / Decimal('100')).quantize(Decimal('0.01'))
        linea_base = max(Decimal('0'), base_bruta - valor_descuento)
        impuesto_val = (linea_base * porcentaje / Decimal('100')).quantize(Decimal('0.01'))
        total_linea = (linea_base + impuesto_val).quantize(Decimal('0.01'))
        informacion = form.get(f'informacion_{index}', '').strip()

        lineas.append({
            'tipo': 'linea',
            'concepto': concepto,
            'unidades': str(unidades),
            'precio': str(precio),
            'descuento': str(descuento),
            'impuesto': impuesto,
            'informacion': informacion,
            'total': str(total_linea),
        })
        total_base += linea_base
        total_impuestos += impuesto_val

    total_presupuesto = (total_base + total_impuestos).quantize(Decimal('0.01'))
    return lineas, total_base, total_impuestos, total_presupuesto, line_count


@app.route('/presupuestos/crear', methods=['GET', 'POST'])
def presupuesto_crear():
    contactos = Contacto.query.order_by(Contacto.nombre_fiscal).all()
    metodos_pago = MetodoPago.query.all()
    if request.method == 'POST':
        cliente_id = request.form.get('contacto_id')
        fecha_emision = request.form.get('fecha_emision')
        fecha_validez = request.form.get('fecha_validez')
        referencia = request.form.get('referencia', '').strip()
        notas = request.form.get('notas', '').strip()
        estado = request.form.get('estado', 'Borrador')
        metodo_pago_id = request.form.get('metodo_pago_id')
        cliente = Contacto.query.get(cliente_id)
        if not cliente:
            flash('Debe seleccionar un cliente', 'danger')
            return render_template('presupuesto_form.html', contactos=contactos, metodos_pago=metodos_pago, lineas=[])

        lineas, total_base, total_impuestos, total_presupuesto, line_count = parse_presupuesto_lineas(request.form)
        if not any(linea.get('tipo') != 'titulo' for linea in lineas):
            flash('Debes añadir al menos una línea de concepto para crear el presupuesto.', 'danger')
            return render_template('presupuesto_form.html', contactos=contactos, lineas=lineas)

        presupuesto = Presupuesto(
            numero_presupuesto=request.form.get('numero_presupuesto') or generate_budget_number(),
            contacto_id=cliente.id,
            fecha_emision=datetime.strptime(fecha_emision, '%Y-%m-%d').date() if fecha_emision else date.today(),
            fecha_validez=datetime.strptime(fecha_validez, '%Y-%m-%d').date() if fecha_validez else date.today(),
            referencia=referencia,
            total_base_imponible=total_base,
            total_impuestos=total_impuestos,
            total_presupuesto=total_presupuesto,
            estado=estado,
            notas=notas,
            linea_items=json.dumps(lineas),
            metodo_pago_id=int(metodo_pago_id) if metodo_pago_id else None
        )
        db.session.add(presupuesto)
        db.session.commit()
        flash('Presupuesto creado', 'success')
        return redirect(url_for('presupuestos'))

    return render_template('presupuesto_form.html', contactos=contactos, metodos_pago=metodos_pago, numero_presupuesto=generate_budget_number(), lineas=[])


@app.route('/presupuestos/<int:presupuesto_id>/editar', methods=['GET', 'POST'])
def presupuesto_editar(presupuesto_id):
    presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
    contactos = Contacto.query.order_by(Contacto.nombre_fiscal).all()
    metodos_pago = MetodoPago.query.all()
    if request.method == 'POST':
        cliente_id = request.form.get('contacto_id')
        fecha_emision = request.form.get('fecha_emision')
        fecha_validez = request.form.get('fecha_validez')
        referencia = request.form.get('referencia', '').strip()
        notas = request.form.get('notas', '').strip()
        estado = request.form.get('estado', 'Borrador')
        metodo_pago_id = request.form.get('metodo_pago_id')
        cliente = Contacto.query.get(cliente_id)
        if not cliente:
            flash('Debe seleccionar un cliente', 'danger')
            return render_template('presupuesto_form.html', contactos=contactos, metodos_pago=metodos_pago, lineas=presupuesto.lineas_json(), selected_contacto_id=presupuesto.contacto_id)

        lineas, total_base, total_impuestos, total_presupuesto, line_count = parse_presupuesto_lineas(request.form)
        if not any(linea.get('tipo') != 'titulo' for linea in lineas):
            flash('Debes añadir al menos una línea de concepto para actualizar el presupuesto.', 'danger')
            return render_template('presupuesto_form.html', contactos=contactos, lineas=lineas, selected_contacto_id=cliente.id)

        presupuesto.contacto_id = cliente.id
        presupuesto.fecha_emision = datetime.strptime(fecha_emision, '%Y-%m-%d').date() if fecha_emision else date.today()
        presupuesto.fecha_validez = datetime.strptime(fecha_validez, '%Y-%m-%d').date() if fecha_validez else date.today()
        presupuesto.referencia = referencia
        presupuesto.notas = notas
        presupuesto.estado = estado
        presupuesto.total_base_imponible = total_base
        presupuesto.total_impuestos = total_impuestos
        presupuesto.total_presupuesto = total_presupuesto
        presupuesto.linea_items = json.dumps(lineas)
        presupuesto.metodo_pago_id = int(metodo_pago_id) if metodo_pago_id else None
        db.session.commit()
        flash('Presupuesto actualizado', 'success')
        return redirect(url_for('presupuestos'))

    return render_template(
        'presupuesto_form.html',
        contactos=contactos,
        metodos_pago=metodos_pago,
        numero_presupuesto=presupuesto.numero_presupuesto,
        fecha_emision=presupuesto.fecha_emision.isoformat(),
        fecha_validez=presupuesto.fecha_validez.isoformat(),
        referencia=presupuesto.referencia,
        estado=presupuesto.estado,
        notas=presupuesto.notas,
        lineas=presupuesto.lineas_json(),
        selected_contacto_id=presupuesto.contacto_id,
        selected_metodo_pago_id=presupuesto.metodo_pago_id,
    )


@app.route('/presupuestos/<int:presupuesto_id>/convertir', methods=['POST'])
def presupuesto_convertir(presupuesto_id):
    presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
    factura = Factura(
        numero_factura=generate_invoice_number(),
        tipo_pestana='Borrador',
        contacto_id=presupuesto.contacto_id,
        referencia=presupuesto.referencia,
        fecha_factura=date.today(),
        fecha_vencimiento=None,
        porcentaje_iva=Decimal('21.00'),
        total_base_imponible=presupuesto.total_base_imponible,
        total_cuota_iva=presupuesto.total_impuestos,
        total_recargo_equivalencia=Decimal('0.00'),
        total_factura=presupuesto.total_presupuesto,
        estado_pago='Borrador',
        linea_items=presupuesto.linea_items,
        metodo_pago_id=presupuesto.metodo_pago_id,
        referencia_presupuesto=presupuesto.numero_presupuesto,
    )
    db.session.add(factura)
    db.session.commit()
    flash('Presupuesto convertido a factura borrador', 'success')
    return redirect(url_for('factura_editar', factura_id=factura.id))


@app.route('/presupuestos/<int:presupuesto_id>/enviar', methods=['POST'])
def presupuesto_enviar(presupuesto_id):
    presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
    presupuesto.estado = 'Enviado'
    db.session.commit()
    flash('Presupuesto marcado como enviado', 'success')
    return redirect(url_for('presupuestos'))


@app.route('/presupuestos/<int:presupuesto_id>/rechazar', methods=['POST'])
def presupuesto_rechazar(presupuesto_id):
    presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
    presupuesto.estado = 'Rechazado'
    db.session.commit()
    flash('Presupuesto marcado como rechazado', 'success')
    return redirect(url_for('presupuestos'))


@app.route('/presupuestos/<int:presupuesto_id>/borrador', methods=['POST'])
def presupuesto_volver_borrador(presupuesto_id):
    presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
    presupuesto.estado = 'Borrador'
    db.session.commit()
    flash('Presupuesto vuelto a borrador', 'success')
    return redirect(url_for('presupuestos'))


@app.route('/presupuestos/<int:presupuesto_id>/aceptar', methods=['POST'])
def presupuesto_aceptar(presupuesto_id):
    presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
    presupuesto.estado = 'Aceptado'
    db.session.commit()
    flash('Presupuesto marcado como aceptado', 'success')
    return redirect(url_for('presupuestos'))


@app.route('/presupuestos/<int:presupuesto_id>/eliminar', methods=['POST'])
def presupuesto_eliminar(presupuesto_id):
    presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
    db.session.delete(presupuesto)
    db.session.commit()
    return jsonify({'status': 'ok'})

import io
import base64
from xhtml2pdf import pisa

@app.route('/presupuestos/<int:id>/descargar')
def presupuesto_descargar(id):
    presupuesto = db.session.get(Presupuesto, id)
    if not presupuesto:
        abort(404)
        
    config = Configuracion.query.first()
    cliente = db.session.get(Contacto, presupuesto.contacto_id)
    lineas_data = presupuesto.lineas_json()

    # 1. LOGOTIPO ROBUSTO (Igual que en previsualizar)
    logo_html = f'<div style="font-size: 20pt; font-weight: bold; color: #d58a1d;">{config.nombre_empresa if config and config.nombre_empresa else "Mi Empresa"}</div>'
    if config and config.logo_path:
        logo_path = os.path.join(app.root_path, 'static', 'uploads', os.path.basename(config.logo_path))
        if os.path.exists(logo_path):
            try:
                with open(logo_path, "rb") as image_file:
                    encoded = base64.b64encode(image_file.read()).decode('utf-8')
                    logo_html = f'<img src="data:image/png;base64,{encoded}" width="150" />'
            except Exception:
                pass

    # 2. CONSTRUCCIÓN DE LÍNEAS
    lineas_html = ""
    for item in lineas_data:
        lineas_html += f"""
        <tr>
            <td style="padding: 6px 10px; font-size: 9pt; border-bottom: 1px solid #e5e7eb;">{item.get('concepto', 'Concepto')}</td>
            <td style="padding: 6px 10px; font-size: 9pt; text-align: right; border-bottom: 1px solid #e5e7eb;">{item.get('unidades', 1)}</td>
            <td style="padding: 6px 10px; font-size: 9pt; text-align: right; border-bottom: 1px solid #e5e7eb;">{float(item.get('precio_ud', 0)):.2f} €</td>
            <td style="padding: 6px 10px; font-size: 9pt; text-align: right; border-bottom: 1px solid #e5e7eb;">{item.get('impuesto', '21%')}</td>
            <td style="padding: 6px 10px; font-size: 9pt; text-align: right; font-weight: bold; border-bottom: 1px solid #e5e7eb;">{float(item.get('total', 0)):.2f} €</td>
        </tr>"""

    # 3. HTML COMPLETO (Mismo diseño que previsualizar)
    html_content = f"""
    <html>
    <head><style>
        body {{ font-family: Helvetica; font-size: 11pt; }}
        .header-table, .details-table {{ width: 100%; margin-bottom: 20px; }}
        .details-box {{ width: 48%; vertical-align: top; }}
        .box-title {{ font-size: 10pt; color: #6b7280; text-transform: uppercase; font-weight: bold; }}
        .concepts-table {{ width: 100%; border-collapse: collapse; }}
        .concepts-table th {{ background-color: #f3f4f6; padding: 5px; text-align: left; border-bottom: 2px solid #d1d5db; }}
    </style></head>
    <body>
        <table class="header-table">
            <tr>
                <td style="width: 15%; text-align: left; vertical-align: top;">{logo_html}</td>
                <td style="width: 80%; text-align: right; vertical-align: top;">
                    <h1 style="color: #d58a1d; margin: 0;">PRESUPUESTO</h1>
                    <strong>Nº:</strong> {presupuesto.numero_presupuesto}<br>
                    <strong>Fecha:</strong> {presupuesto.fecha_emision.strftime('%d/%m/%Y')}<br>
                    <strong>Validez:</strong> {presupuesto.fecha_validez.strftime('%d/%m/%Y')}
                </td>
            </tr>
        </table>

        <table class="details-table">
            <tr>
                <td class="details-box">
                    <div class="box-title">Emisor</div>
                    <strong>{config.nombre_empresa if config else ''}</strong><br>
                    CIF/NIF: {config.cif_nif if config else ''}<br>
                    {config.direccion_fiscal if config else ''}<br>
                    {config.codigo_postal if config else ''} {config.ciudad if config else ''}<br>
                    {config.telefono if config else ''}<br>
                    {config.email if config else ''}
                </td>
                <td class="details-box">
                    <div class="box-title">Cliente</div>
                    <strong>{cliente.nombre_fiscal if cliente else ''}</strong><br>
                    CIF/NIF: {cliente.numero_documento if cliente else ''}<br>
                    {cliente.direccion_fiscal if cliente else ''}<br>
                    {cliente.codigo_postal if cliente else ''} {cliente.ciudad if cliente else ''}<br>
                    {cliente.telefono if cliente else ''}<br>
                    
                </td>
            </tr>
        </table>

        <table class="concepts-table">
            <thead><tr><th>Concepto</th><th>Uds.</th><th>Precio</th><th>Impuesto</th><th>Total</th></tr></thead>
            <tbody>{lineas_html}</tbody>
        </table>

        <div style="text-align: right; margin-top: 20px;">
            <p>Base Imponible: {float(presupuesto.total_base_imponible):.2f} €</p>
            <p>Impuestos: {float(presupuesto.total_impuestos):.2f} €</p>
            <h2 style="color: #1a2232;">TOTAL: {float(presupuesto.total_presupuesto):.2f} €</h2>
        </div>
    </body>
    </html>
    """

    pdf_buffer = io.BytesIO()
    pisa.CreatePDF(io.StringIO(html_content), dest=pdf_buffer)
    pdf_buffer.seek(0)
    
    response = make_response(pdf_buffer.read())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=Presupuesto_{presupuesto.numero_presupuesto}.pdf'
    return response


@app.route('/metodos-pago/nuevo', methods=['POST'])
def metodo_pago_nuevo():
    nombre = request.form.get('nombre') or request.form.get('mp_nombre')
    tipo = request.form.get('tipo') or request.form.get('mp_tipo')
    entidad = request.form.get('entidad') or request.form.get('mp_entidad')
    iban = request.form.get('iban') or request.form.get('mp_iban')
    
    if not nombre or not tipo:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': 'Nombre y tipo son obligatorios'}), 400
        flash('Nombre y tipo son obligatorios para el método de pago', 'danger')
        return redirect(request.referrer or url_for('configuracion'))

    nuevo_mp = MetodoPago(nombre=nombre, tipo=tipo, entidad=entidad, cuenta_iban=iban)
    db.session.add(nuevo_mp)
    db.session.commit()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'id': nuevo_mp.id,
            'nombre': nuevo_mp.nombre,
            'tipo': nuevo_mp.tipo
        })
    
    flash('Método de pago añadido', 'success')
    return redirect(request.referrer or url_for('configuracion'))


@app.route('/configuracion', methods=['GET', 'POST'])
def configuracion():
    config_obj = Configuracion.query.first()
    metodos_pago = MetodoPago.query.all()
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add_metodo_pago':
            return metodo_pago_nuevo()

        if action == 'delete_metodo_pago':
            mp_id = request.form.get('mp_id')
            mp = MetodoPago.query.get(mp_id)
            if mp:
                db.session.delete(mp)
                db.session.commit()
                flash('Método de pago eliminado', 'info')
            return redirect(url_for('configuracion'))

        if not config_obj:
            config_obj = Configuracion()
            db.session.add(config_obj)
        config_obj.nombre_empresa = request.form.get('nombre_empresa', config_obj.nombre_empresa)
        config_obj.serie_factura = request.form.get('serie_factura', config_obj.serie_factura)
        config_obj.numero_inicial_factura = int(request.form.get('numero_inicial_factura') or config_obj.numero_inicial_factura or 1)
        config_obj.cif_nif = request.form.get('cif_nif', config_obj.cif_nif)
        config_obj.direccion_fiscal = request.form.get('direccion_fiscal', config_obj.direccion_fiscal)
        config_obj.codigo_postal = request.form.get('codigo_postal', config_obj.codigo_postal)
        config_obj.ciudad = request.form.get('ciudad', config_obj.ciudad)
        config_obj.provincia = request.form.get('provincia', config_obj.provincia)
        config_obj.pais = request.form.get('pais', config_obj.pais)
        config_obj.telefono = request.form.get('telefono', config_obj.telefono)
        config_obj.email = request.form.get('email', config_obj.email)
        config_obj.website = request.form.get('website', config_obj.website)
        logo_file = request.files.get('logo')
        if logo_file and logo_file.filename:
            if allowed_file(logo_file.filename):
                upload_folder = os.path.join(app.root_path, 'static', 'uploads')
                os.makedirs(upload_folder, exist_ok=True)
                filename = secure_filename(logo_file.filename)
                file_path = os.path.join(upload_folder, filename)
                logo_file.save(file_path)
                config_obj.logo_path = os.path.join('uploads', filename).replace('\\', '/')
            else:
                flash('Formato de logo no válido. Usa PNG o JPG.', 'danger')
        config_obj.metodo_pago_defecto = request.form.get('metodo_pago_defecto', config_obj.metodo_pago_defecto)
        config_obj.moneda_defecto = request.form.get('moneda_defecto', config_obj.moneda_defecto)
        config_obj.impuesto_defecto = request.form.get('impuesto_defecto', config_obj.impuesto_defecto)
        config_obj.recargo_equivalencia_default = bool(request.form.get('recargo_equivalencia_default'))
        config_obj.nota_legal = request.form.get('nota_legal', config_obj.nota_legal)
        db.session.commit()
        flash('Configuración guardada', 'success')
        return redirect(url_for('configuracion'))
    return render_template('configuracion.html', configuracion=config_obj, metodos_pago=metodos_pago)


@app.route('/productos')
def productos():
    items = Producto.query.order_by(Producto.nombre).all()
    return render_template('productos.html', productos=items)


@app.route('/productos/nuevo', methods=['GET', 'POST'])
def producto_nuevo():
    if request.method == 'POST':
        producto = Producto(
            codigo=request.form.get('codigo', '').strip(),
            nombre=request.form.get('nombre', '').strip(),
            descripcion=request.form.get('descripcion', '').strip(),
            precio_unitario_base=Decimal(request.form.get('precio_unitario_base', '0') or '0'),
            impuesto_defecto=request.form.get('impuesto_defecto', '21% IVA'),
        )
        if not producto.nombre or producto.precio_unitario_base <= 0:
            flash('Nombre y precio base son obligatorios', 'danger')
        else:
            db.session.add(producto)
            db.session.commit()
            flash('Producto añadido', 'success')
            return redirect(url_for('productos'))
    return render_template('producto_form.html')


@app.route('/pagos', methods=['GET', 'POST'])
def pagos():
    if request.method == 'POST':
        tipo_movimiento = request.form.get('tipo_movimiento', 'Ingreso')
        factura_id = request.form.get('factura_id')
        gasto_id = request.form.get('gasto_id')
        importe = Decimal(request.form.get('importe', '0') or '0')
        cuenta = request.form.get('cuenta_bancaria_destino', '').strip()
        fecha_pago = request.form.get('fecha_pago') or ''
        pago = Pago(
            fecha_pago=datetime.strptime(fecha_pago, '%Y-%m-%d').date() if fecha_pago else date.today(),
            tipo_movimiento=tipo_movimiento,
            factura_id=int(factura_id) if factura_id else None,
            gasto_id=int(gasto_id) if gasto_id else None,
            metodo_pago=request.form.get('metodo_pago', '').strip(),
            importe=importe,
            cuenta_bancaria_destino=cuenta,
            estado='Conciliado',
        )
        db.session.add(pago)
        if pago.factura_id:
            factura = Factura.query.get(pago.factura_id)
            if factura and factura.total_factura == importe:
                factura.estado_pago = 'Cobrada'
        if pago.gasto_id:
            gasto = Gasto.query.get(pago.gasto_id)
            if gasto and gasto.total_factura == importe:
                gasto.estado_pago = 'Pagada'
        db.session.commit()
        flash('Pago registrado', 'success')
        return redirect(url_for('pagos'))
    facturas = Factura.query.order_by(Factura.fecha_factura.desc()).all()
    gastos = Gasto.query.order_by(Gasto.fecha_factura.desc()).all()
    pagos = Pago.query.order_by(Pago.fecha_pago.desc()).all()
    return render_template('pagos.html', pagos=pagos, facturas=facturas, gastos=gastos)


@app.route('/api/productos')
def api_productos():
    term = request.args.get('q', '').strip().lower()
    productos = Producto.query.order_by(Producto.nombre).all()
    results = [
        {'id': p.id, 'nombre': p.nombre, 'precio': str(p.precio_unitario_base), 'impuesto': p.impuesto_defecto}
        for p in productos if term in p.nombre.lower()
    ]
    return jsonify(results)


@app.context_processor
def inject_statistics():
    total_ingresos = sum([float(f.total_factura) for f in Factura.query.filter(Factura.estado_pago == 'Cobrada').all()])
    total_gastos = sum([float(g.total_factura) for g in Gasto.query.filter(Gasto.estado_pago == 'Pagada').all()])
    return {'total_ingresos': total_ingresos, 'total_gastos': total_gastos}


@app.route('/gastos/ocr', methods=['POST'])
def gastos_ocr():
    file = request.files.get('documento')
    if not file or not file.filename:
        return jsonify({'error': 'No se recibió archivo'}), 400
    
    upload_dir = os.path.join(app.root_path, 'static', 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    filename = secure_filename(file.filename or "gasto.pdf")
    filepath = os.path.join(upload_dir, filename)
    file.save(filepath)
    
    texto_extraido = ""
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            texto_extraido += page.extract_text() or ""
            
    print("TEXTO EXTRAÍDO:", texto_extraido)

    # --- FUNCIONES DE EXTRACCIÓN ---

    def buscar_factura(texto):
        # El \n? permite capturar aunque haya un salto de línea tras el prefijo
        patrones = [
            r'Factura\s*/\s*Fecha\s*\n\s*([A-Z0-9/-]+)', 
            r'N[º°]\s*(?:de\s*)?Factura[:\s]*\n?([A-Z0-9/-]+)', 
            r'Factura\s*[:\s]*\n?([A-Z0-9/-]+)',
            r'Factura\s*N[º°]\s*([A-Z0-9/-]+)'
        ]
        for p in patrones:
            m = re.search(p, texto, re.IGNORECASE)
            if m: return m.group(1).strip()
        return "N/A"

    def buscar_fecha(texto):
        prefijos = [r'fecha\s*factura', r'fecha\s*de\s*emisión', r'fecha\s*emisión', r'fecha']
        formato = r'(\d{2}[./]\d{2}[./]\d{4})'
        for prefijo in prefijos:
            m = re.search(f"{prefijo}[:\\s]*\n?{formato}", texto, re.IGNORECASE)
            if m: return m.group(1).replace('.', '-').replace('/', '-')
        m_fallback = re.search(formato, texto)
        return m_fallback.group(1).replace('.', '-').replace('/', '-') if m_fallback else date.today().isoformat()

    def buscar_nif(texto):
        m = re.search(r'N\.?I\.?F\.?\s*([A-Z0-9-]+)', texto, re.IGNORECASE)
        return m.group(1) if m else ""

    def buscar_total(texto):
        # Busca el último valor que parece un total
        matches = re.findall(r'(?:Importe total|Total|Neto total)\s*[^0-9]*([\d.,]+)', texto, re.IGNORECASE)
        return matches[-1].replace(',', '.') if matches else "0.00"

    # --- PROCESAMIENTO ---

    total_final = buscar_total(texto_extraido)
    
    # Extracción de nombre fiscal (busca palabras en mayúsculas seguidas de tipo de sociedad)
    match_nombre = re.search(r'([A-ZÁÉÍÓÚ\s]+(?:S\.A\.|S\.L\.|S\.L\.U\.|SL|SA))', texto_extraido)
    
    data = {
        'numero_factura_proveedor': buscar_factura(texto_extraido),
        'nombre_fiscal': match_nombre.group(1).strip() if match_nombre else "Proveedor Desconocido",
        'nif': buscar_nif(texto_extraido),
        'fecha_factura': buscar_fecha(texto_extraido),
        'base_imponible': str(round(float(total_final) / 1.07, 2)), 
        'porcentaje_iva': '7',
        'total_factura': total_final,
        'tipo_gasto': 'Compras operativas'
    }
    
    return jsonify(data)
    
    


if __name__ == '__main__':
    with app.app_context():
        init_db(app)
    app.run(debug=True)