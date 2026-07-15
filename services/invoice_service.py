# services/invoice_service.py
from models import FacturaLinea
from decimal import Decimal, ROUND_HALF_UP
from utils.tax_calculations import (
    parse_impuesto_porcentaje, 
    get_recargo_porcentaje, 
    calculate_invoice_totals,
    TWOPLACES
)

class InvoiceService:
    @staticmethod
    def procesar_lineas_form(form, cliente, pestana, tipo_factura='Ordinaria'):
        """
        Extrae, valida y calcula las líneas de factura a partir del formulario.
        Gestiona índices dinámicos para prevenir desajustes por filas borradas
        en el frontend, mapea los tipos y delega el cálculo matemático riguroso.

        Devuelve una tupla (instancias_lineas, totales_calculados, error).
        Si no hay líneas válidas, `instancias_lineas` es una lista vacía y
        `error` contiene el mensaje de error para mostrar al usuario.
        """
        indices = set()
        for key in form.keys():
            if key.startswith('concepto_'):
                try:
                    indices.add(int(key.split('_')[1]))
                except ValueError:
                    continue

        instancias_lineas = []
        lineas_para_calculo = []

        # Procesamos los índices del formulario secuencialmente
        for index in sorted(list(indices)):
            concepto = form.get(f'concepto_{index}', '').strip()
            if not concepto:
                continue

            informacion_adicional = form.get(f'informacion_{index}', '').strip() or None

            try:
                unidades = Decimal(form.get(f'unidades_{index}', '1') or '1')
                precio = Decimal(form.get(f'precio_{index}', '0') or '0')
                descuento = Decimal(form.get(f'descuento_{index}', '0') or '0')
            except (ValueError, TypeError):
                unidades = Decimal('1')
                precio = Decimal('0')
                descuento = Decimal('0')

            # --- VALIDACIÓN Y CONTROL DE SIGNOS SEGÚN TIPO DE FACTURA ---
            if tipo_factura == 'Rectificativa':
                # En rectificativas se fuerza que las unidades resten de la facturación global
                unidades = -abs(unidades)
            else:
                if unidades < 0:
                    return [], {}, 'Las cantidades no pueden ser negativas en facturas ordinarias.'

            impuesto = form.get(f'impuesto_{index}', cliente.impuesto_defecto or '21% IVA').strip()
            porcentaje_iva = parse_impuesto_porcentaje(impuesto)

            # Estructura ligera para pasarle a nuestro motor matemático en utils
            lineas_para_calculo.append({
                'cantidad': unidades,
                'precio_unitario': precio,
                'descuento': descuento,
                'iva_porcentaje': porcentaje_iva
            })

            # Calculamos de manera temporal el subtotal de la línea para instanciar el modelo físico
            base_bruta = (unidades * precio).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
            valor_descuento = (base_bruta * descuento / Decimal('100')).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
            
            if tipo_factura == 'Rectificativa':
                subtotal_linea = base_bruta - valor_descuento
            else:
                subtotal_linea = max(Decimal('0'), base_bruta - valor_descuento)

            # Recargo de equivalencia dinámico según la tasa de IVA del cliente
            porcentaje_recargo = Decimal('0.00')
            if cliente.recargo_equivalencia:
                porcentaje_recargo = get_recargo_porcentaje(porcentaje_iva)

            instancias_lineas.append(FacturaLinea(
                concepto=concepto,
                informacion=informacion_adicional,
                unidades=unidades,
                precio_unitario=precio,
                descuento_porcentaje=descuento,
                impuesto_tipo=impuesto,
                porcentaje_iva=porcentaje_iva,
                porcentaje_recargo=porcentaje_recargo,
                subtotal_linea=subtotal_linea,
            ))

        if not instancias_lineas:
            return [], {}, 'Debes añadir al menos una línea de concepto para crear la factura.'

        # --- DELEGACIÓN DEL CÁLCULO ---
        # Enviamos las estructuras al motor centralizado en tax_calculations
        totales_calculados = calculate_invoice_totals(
            lineas=lineas_para_calculo,
            recargo=cliente.recargo_equivalencia,
            porcentaje_retencion=Decimal('0.00')  # Se asocia y calcula con el IRPF en la persistencia final
        )

        return instancias_lineas, totales_calculados, None
    
    @staticmethod
    def preparar_lineas_para_pdf(lineas):
        """
        Convierte una lista de objetos FacturaLinea en diccionarios serializados
        manteniendo precisión matemática Decimal estricta de principio a fin.
        """
        datos_lineas = []
        tipos_impuestos = set()
        
        for linea in lineas:
            base = Decimal(linea.subtotal_linea or '0.00')
            porcentaje = Decimal(linea.porcentaje_iva or '0.00')
            
            # Cuota de IVA de la línea en Decimal
            cuota_iva = (base * (porcentaje / Decimal('100'))).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
            total_linea = base + cuota_iva
            
            if linea.impuesto_tipo:
                tipos_impuestos.add(linea.impuesto_tipo)
            
            # Serializamos a strings de dos decimales para evitar floating-point issues en el template
            datos_lineas.append({
                'concepto': linea.concepto,
                'informacion': linea.informacion or '',
                'unidades': f"{linea.unidades:.2f}",
                'precio': f"{linea.precio_unitario:.2f}",
                'impuesto': linea.impuesto_tipo,
                'cuota_iva': f"{cuota_iva:.2f}",
                'total': f"{total_linea:.2f}"
            })
            
        resumen_impuestos = ' / '.join(sorted(tipos_impuestos)) if tipos_impuestos else 'Impuestos'
        
        return datos_lineas, resumen_impuestos
    
    @staticmethod
    def generar_qr_verifactu(factura, configuracion):
        """
        Genera el código QR oficial de Veri*Factu para la AEAT en formato Base64.
        """
        import io
        import base64
        import qrcode

        if not factura or not configuracion:
            return ''

        estado_directo = getattr(factura, 'verifactu_estado', None) == 'Aceptado'
        registro = getattr(factura, 'verifactu_registro', None)
        estado_registro = registro and getattr(registro, 'estado_envio', None) == 'Enviado_Aceptado'

        if not (estado_directo or estado_registro):
            return ''

        try:
            url_aeat = (
                f"https://www2.agenciatributaria.gob.es/wlpl/SSHA-ITCS/G301/CVeriFactuGR"
                f"?nif={str(configuracion.cif_nif or '').strip().upper()}"
                f"&num_serie={str(factura.numero_factura).strip()}"
                f"&fecha={factura.fecha_factura.strftime('%d-%m-%Y')}"
                f"&total={abs(float(factura.total_factura)):.2f}"
            )
            
            qr = qrcode.make(url_aeat)
            buffer_qr = io.BytesIO()
            qr.save(buffer_qr, kind='PNG')
            
            return base64.b64encode(buffer_qr.getvalue()).decode('utf-8')
            
        except Exception as e:
            print(f"[ERROR QR] No se pudo generar el QR para la factura ID {factura.id}: {e}")
            return ''
        
    @staticmethod
    def reconstruir_lineas_pantalla(form):
        """
        Reconstruye dinámicamente las líneas del formulario a partir del request.form
        manteniendo la consistencia visual si falla alguna validación en el POST.
        """
        indices = set()
        for key in form.keys():
            if key.startswith('concepto_'):
                try:
                    indices.add(int(key.split('_')[1]))
                except ValueError:
                    continue

        lineas_en_pantalla = []
        for index in sorted(list(indices)):
            concepto_pantalla = form.get(f'concepto_{index}', '').strip()
            if concepto_pantalla:
                lineas_en_pantalla.append({
                    'concepto': concepto_pantalla,
                    'informacion': form.get(f'informacion_{index}', '').strip(),
                    'unidades': float(form.get(f'unidades_{index}', '1') or '1'),
                    'precio': float(form.get(f'precio_{index}', '0') or '0'),
                    'impuesto': form.get(f'impuesto_{index}', '21% IVA'),
                    'descuento': float(form.get(f'descuento_{index}', '0') or '0'),
                    'total': float(form.get(f'total_{index}', '0') or '0')
                })
        return lineas_en_pantalla