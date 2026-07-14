from decimal import Decimal
from datetime import datetime, date
from models import db, Albaran, AlbaranLinea

class DeliveryNoteService:
    @staticmethod
    def parse_form_lines(form_data):
        """
        Extrae y calcula dinámicamente las líneas desde el formulario dinámico.
        Es compatible tanto con previsualización como con guardado.
        """
        lineas = []
        total_base = Decimal('0.00')
        total_impuestos = Decimal('0.00')
        total_albaran = Decimal('0.00')

        # Buscamos claves de tipo 'concepto_X' en el formulario enviado por la UI
        for key in form_data.keys():
            if key.startswith('concepto_'):
                suffix = key.split('_')[1]
                concepto = form_data.get(f'concepto_{suffix}')
                if not concepto:
                    continue

                informacion = form_data.get(f'informacion_{suffix}', '')
                unidades = Decimal(form_data.get(f'unidades_{suffix}', '1.00') or '1.00')
                precio = Decimal(form_data.get(f'precio_{suffix}', '0.00') or '0.00')
                descuento = Decimal(form_data.get(f'descuento_{suffix}', '0.00') or '0.00')
                impuesto_tipo = form_data.get(f'impuesto_{suffix}', '21% IVA')
                producto_id_raw = form_data.get(f'articulo_id_{suffix}', '')

                # Cálculo de subtotal con descuento
                subtotal = unidades * precio
                if descuento > 0:
                    subtotal -= subtotal * (descuento / Decimal('100.00'))
                
                # Cálculo aproximado de cuota de impuesto para los totales agregados
                porcentaje_iva = Decimal('21.00')
                if '21' in impuesto_tipo: porcentaje_iva = Decimal('21.00')
                elif '10' in impuesto_tipo: porcentaje_iva = Decimal('10.00')
                elif '4' in impuesto_tipo: porcentaje_iva = Decimal('4.00')
                elif '0' in impuesto_tipo or 'Exento' in impuesto_tipo: porcentaje_iva = Decimal('0.00')

                cuota_iva = subtotal * (porcentaje_iva / Decimal('100.00'))

                linea_dict = {
                    'producto_id': int(producto_id_raw) if producto_id_raw and producto_id_raw.isdigit() else None,
                    'concepto': concepto,
                    'informacion': informacion,
                    'unidades': unidades,
                    'precio_unitario': precio,
                    'descuento_porcentaje': descuento,
                    'impuesto_tipo': impuesto_tipo,
                    'subtotal_linea': subtotal
                }
                lineas.append(linea_dict)

                total_base += subtotal
                total_impuestos += cuota_iva
                total_albaran += (subtotal + cuota_iva)

        return lineas, total_base, total_impuestos, total_albaran

    @staticmethod
    def create_delivery_note(form_data):
        contacto_id = form_data.get('contacto_id')
        if not contacto_id:
            raise ValueError("Debe seleccionar un cliente.")

        lineas_parsed, total_base, total_impuestos, total_albaran = DeliveryNoteService.parse_form_lines(form_data)
        if not lineas_parsed:
            raise ValueError("El albarán debe contener al menos una línea.")

        f_emision = form_data.get('fecha_emision')
        f_entrega = form_data.get('fecha_entrega')

        albaran = Albaran(
            numero_albaran=form_data.get('numero_albaran'),
            contacto_id=int(contacto_id),
            metodo_pago_id=int(form_data.get('metodo_pago_id')) if form_data.get('metodo_pago_id') else None,
            referencia=form_data.get('referencia'),
            referencia_presupuesto=form_data.get('referencia_presupuesto'),
            fecha_emision=datetime.strptime(f_emision, '%Y-%m-%d').date() if f_emision else date.today(),
            fecha_entrega=datetime.strptime(f_entrega, '%Y-%m-%d').date() if f_entrega else None,
            total_base_imponible=total_base,
            total_impuestos=total_impuestos,
            total_albaran=total_albaran,
            estado=form_data.get('estado', 'Borrador'),
            notas=form_data.get('notas')
        )

        for l in lineas_parsed:
            linea_obj = AlbaranLinea(**l)
            albaran.lineas.append(linea_obj)

        db.session.add(albaran)
        db.session.commit()
        return albaran

    @staticmethod
    def update_delivery_note(albaran, form_data): 
        contacto_id = form_data.get('contacto_id')
        if not contacto_id:
            raise ValueError("Debe seleccionar un cliente.")

        lineas_parsed, total_base, total_impuestos, total_albaran = DeliveryNoteService.parse_form_lines(form_data)
        if not lineas_parsed:
            raise ValueError("El albarán debe contener al menos una línea.")

        f_emision = form_data.get('fecha_emision')
        f_entrega = form_data.get('fecha_entrega')

        albaran.contacto_id = int(contacto_id)
        albaran.metodo_pago_id = int(form_data.get('metodo_pago_id')) if form_data.get('metodo_pago_id') else None
        albaran.referencia = form_data.get('referencia')
        albaran.referencia_presupuesto = form_data.get('referencia_presupuesto')
        albaran.fecha_emision = datetime.strptime(f_emision, '%Y-%m-%d').date() if f_emision else date.today()
        albaran.fecha_entrega = datetime.strptime(f_entrega, '%Y-%m-%d').date() if f_entrega else None
        albaran.total_base_imponible = total_base
        albaran.total_impuestos = total_impuestos
        albaran.total_albaran = total_albaran
        albaran.estado = form_data.get('estado', 'Borrador')
        albaran.notas = form_data.get('notas')

        # Reemplazar líneas viejas de forma atómica
        AlbaranLinea.query.filter_by(albaran_id=albaran.id).delete()
        for l in lineas_parsed:
            linea_obj = AlbaranLinea(**l)
            albaran.lineas.append(linea_obj)

        db.session.commit()