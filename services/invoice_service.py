# services/invoice_service.py
from models import FacturaLinea
from decimal import Decimal
from utils.tax_calculations import parse_impuesto_porcentaje

class InvoiceService:
    @staticmethod
    def procesar_lineas_form(form, cliente, pestana, tipo_factura='Ordinaria'):
        """
        Extrae, valida y calcula las líneas de factura a partir del formulario.
        Gestiona índices dinámicos (evita errores por líneas salteadas en el frontend)
        y procesa descuentos con precisión matemática estricta Decimal.

        Devuelve una tupla (instancias_lineas, total_base, total_iva, error).
        Si no hay líneas válidas, `instancias_lineas` es una lista vacía y
        `error` contiene el mensaje de flash correspondiente.
        """
        # 1. Detectar índices dinámicos presentes en el formulario para evitar huecos vacíos
        indices = set()
        for key in form.keys():
            if key.startswith('concepto_'):
                try:
                    indices.add(int(key.split('_')[1]))
                except ValueError:
                    continue

        instancias_lineas = []
        total_base = Decimal('0')
        total_iva = Decimal('0')

        # Procesamos los índices en orden secuencial real
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
                # En rectificativas, forzamos que las unidades sean negativas para restar de la contabilidad
                unidades = -abs(unidades)
                if unidades > 0:
                    unidades = unidades * Decimal('-1')
            else:
                # En facturas ordinarias, mantenemos la seguridad de que no metan negativos por error
                if unidades < 0:
                    return [], Decimal('0'), Decimal('0'), 'Las cantidades no pueden ser negativas en facturas ordinarias.'

            impuesto = form.get(f'impuesto_{index}', cliente.impuesto_defecto or '21% IVA').strip()

            # Usamos siempre parse_impuesto_porcentaje (unifica crear y editar)
            porcentaje = parse_impuesto_porcentaje(impuesto)

            # --- CÁLCULO ESTRICTO CON DESCUENTOS POR LÍNEA ---
            base_bruta = (unidades * precio).quantize(Decimal('0.01'))
            valor_descuento = (base_bruta * descuento / Decimal('100')).quantize(Decimal('0.01'))
            
            # Al ser las unidades negativas en rectificativas, los valores se vuelven negativos automáticamente
            if tipo_factura == 'Rectificativa':
                linea_base = base_bruta - valor_descuento
            else:
                linea_base = max(Decimal('0'), base_bruta - valor_descuento)

            iva = (linea_base * porcentaje / Decimal('100')).quantize(Decimal('0.01'))

            porcentaje_recargo = (
                Decimal('5.20')
                if (cliente.recargo_equivalencia and pestana != 'Borrador' and porcentaje == 21)
                else Decimal('0.00')
            )

            total_base += linea_base
            total_iva += iva

            instancias_lineas.append(FacturaLinea(
                concepto=concepto,
                informacion=informacion_adicional,
                unidades=unidades,
                precio_unitario=precio,
                descuento_porcentaje=descuento,
                impuesto_tipo=impuesto,
                porcentaje_iva=porcentaje,
                porcentaje_recargo=porcentaje_recargo,
                subtotal_linea=linea_base,
            ))

        error = None if instancias_lineas else 'Debes añadir al menos una línea de concepto para crear la factura.'
        return instancias_lineas, total_base, total_iva, error
    
    @staticmethod
    def preparar_lineas_para_pdf(lineas):
        """
        Convierte una lista de objetos FacturaLinea en diccionarios serializados.
        Esto elimina la necesidad de construir HTML en las vistas.
        """
        datos_lineas = []
        tipos_impuestos = set() # Usamos un set para que no se repitan
        
        for linea in lineas:
            base = float(linea.subtotal_linea or 0.0)
            porcentaje = float(linea.porcentaje_iva or 0.0)
            cuota_iva = base * (porcentaje / 100)
            
            # Guardamos el tipo de impuesto para el resumen final
            if linea.impuesto_tipo:
                tipos_impuestos.add(linea.impuesto_tipo)
            
            datos_lineas.append({
                'concepto': linea.concepto,
                'informacion': linea.informacion or '',
                'unidades': float(linea.unidades),
                'precio': float(linea.precio_unitario),
                'impuesto': linea.impuesto_tipo,
                'cuota_iva': cuota_iva,
                'total': base + cuota_iva
            })
            
        # Generamos el texto aquí: "21% IVA / 4% IVA"
        resumen_impuestos = ' / '.join(sorted(tipos_impuestos)) if tipos_impuestos else 'Impuestos'
        
        return datos_lineas, resumen_impuestos
    
    @staticmethod
    def generar_qr_verifactu(factura, configuracion):
        """
        Genera el código QR oficial de Veri*Factu para la AEAT en formato Base64.
        Devuelve un string vacío si la factura no está aceptada o no hay configuración.
        """
        import io
        import base64
        import qrcode

        if not factura or not configuracion:
            return ''

        # --- COMPROBACIÓN INTELIGENTE Y COMPATIBLE ---
        # 1. Comprobamos el estado directo en la factura
        estado_directo = getattr(factura, 'verifactu_estado', None) == 'Aceptado'
        
        # 2. Comprobamos a través de la relación 'verifactu_registro' (tu lógica original)
        registro = getattr(factura, 'verifactu_registro', None)
        estado_registro = registro and getattr(registro, 'estado_envio', None) == 'Enviado_Aceptado'

        # Si ninguna de las dos condiciones se cumple, no se genera el QR
        if not (estado_directo or estado_registro):
            return ''

        try:
            # Construcción de la URL oficial con los parámetros requeridos por la AEAT
            url_aeat = (
                f"https://www2.agenciatributaria.gob.es/wlpl/SSHA-ITCS/G301/CVeriFactuGR"
                f"?nif={str(configuracion.cif_nif or '').strip().upper()}"
                f"&num_serie={str(factura.numero_factura).strip()}"
                f"&fecha={factura.fecha_factura.strftime('%d-%m-%Y')}"
                f"&total={abs(float(factura.total_factura)):.2f}"
            )
            
            # Generación de la imagen del código QR
            qr = qrcode.make(url_aeat)
            buffer_qr = io.BytesIO()
            qr.save(buffer_qr, kind='PNG')
            
            # Codificación a Base64 listo para usar en plantillas HTML e imágenes
            return base64.b64encode(buffer_qr.getvalue()).decode('utf-8')
            
        except Exception as e:
            print(f"[ERROR QR] No se pudo generar el QR para la factura ID {factura.id}: {e}")
            return ''
        
    @staticmethod
    def reconstruir_lineas_pantalla(form):
        """
        Reconstruye dinámicamente las líneas del formulario a partir del request.form
        para evitar que el usuario pierda los datos si falla alguna validación en el POST.
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