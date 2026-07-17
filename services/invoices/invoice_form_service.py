from datetime import datetime, date
from decimal import Decimal
from werkzeug.datastructures import ImmutableMultiDict
from models import db, Contacto, Factura, MetodoPago, Configuracion, Producto
from services.invoice_service import InvoiceService
from utils.sequence_generators import generate_invoice_number, generate_draft_number, generate_rectificative_number
from utils.tax_calculations import calculate_invoice_totals

class InvoiceFormService:

    @staticmethod
    def get_productos_lista() -> list[dict]:
        """Devuelve la lista de productos serializada como diccionarios para el frontend."""
        return [
            {
                'nombre': p.nombre,
                'precio_unitario_base': float(p.precio_unitario_base),
                'impuesto_defecto': p.impuesto_defecto,
                'descripcion_adicional': p.descripcion_adicional,
            }
            for p in Producto.query.order_by(Producto.nombre).all()
        ]

    @staticmethod
    def get_form_context() -> dict:
        """Devuelve los recursos comunes que necesitan los formularios de factura."""
        return {
            'contactos': Contacto.query.filter(Contacto.tipo_contacto.in_(['Cliente', 'Ambas'])).order_by(Contacto.nombre_fiscal).all(),
            'productos': InvoiceFormService.get_productos_lista(),
            'metodos_pago': MetodoPago.query.all(),
            'configuracion': Configuracion.query.first(),
        }

    @classmethod
    def procesar_guardado_factura(cls, form_data: ImmutableMultiDict, factura_existente: Factura | None = None) -> tuple[Factura | None, dict | None, str | None]:
        """
        Procesa y valida los datos de un formulario tanto para creación como para edición.
        Devuelve una tupla con (factura_instancia, contexto_error, mensaje_error).
        """
        ctx = cls.get_form_context()
        
        cliente_id = form_data.get('contacto_id')
        cliente_id = int(cliente_id) if cliente_id and cliente_id.isdigit() else None
        metodo_pago_id = form_data.get('metodo_pago_id')
        selected_metodo_pago_id = int(metodo_pago_id) if metodo_pago_id and metodo_pago_id.isdigit() else None
        es_borrador = bool(form_data.get('guardar_borrador'))
        pestana = 'Borrador' if es_borrador else 'Emitida'

        cliente = db.session.get(Contacto, cliente_id) if cliente_id else None
        
        # Determinar si estamos en modo edición
        edit_mode = factura_existente is not None
        tipo_factura = factura_existente.tipo_factura if (edit_mode and factura_existente) else 'Ordinaria'

        # Preparar contexto de retorno en caso de error de validación
        contexto_error = {
            **ctx,
            'edit_mode': edit_mode,
            'factura': factura_existente,
            'lineas': InvoiceService.reconstruir_lineas_pantalla(form_data),
            'selected_contacto_id': cliente_id if not edit_mode else (factura_existente.contacto_id if factura_existente else None),
            'selected_metodo_pago_id': selected_metodo_pago_id
        }

        if not cliente:
            if not edit_mode:
                num_error = form_data.get('numero_factura', '').strip()
                if not num_error:
                    num_error = generate_draft_number() if es_borrador else generate_invoice_number()
                contexto_error['numero_factura'] = num_error
            return None, contexto_error, 'Debe seleccionar un cliente válido.'

        # Gestión del número de factura
        form_num = form_data.get('numero_factura', '').strip()
        if edit_mode and factura_existente:
            era_borrador = factura_existente.estado_ui == 'Borrador'
            if not form_num or form_num.startswith('BORR') or form_num.startswith('B-'):
                if pestana == 'Emitida':
                    numero_factura = generate_rectificative_number() if tipo_factura == 'Rectificativa' else generate_invoice_number()
                else:
                    numero_factura = factura_existente.numero_factura or form_num
            else:
                numero_factura = form_num
        else:
            if es_borrador:
                numero_factura = generate_draft_number()
            elif not form_num or form_num.startswith('BORR') or form_num.startswith('B-'):
                numero_factura = generate_invoice_number()
            else:
                numero_factura = form_num

        # Validar duplicados de número de factura
        query_duplicado = Factura.query.filter(Factura.numero_factura == numero_factura)
        if edit_mode and factura_existente:
            query_duplicado = query_duplicado.filter(Factura.id != factura_existente.id)
        
        if query_duplicado.first():
            contexto_error['numero_factura'] = numero_factura
            return None, contexto_error, 'Ya existe una factura con ese número.'

        # Procesar líneas con el servicio existente
        instancias_lineas, totales, error = InvoiceService.procesar_lineas_form(
            form_data, cliente, pestana, tipo_factura=tipo_factura
        )
        if error:
            contexto_error['numero_factura'] = numero_factura
            return None, contexto_error, error

        # Inyectar retención de IRPF al cálculo matemático unificado
        porcentaje_irpf = Decimal(form_data.get('porcentaje_irpf', '0')).quantize(Decimal('0.01'))
        
        lineas_para_totales = [
            {
                'cantidad': l.unidades,
                'precio_unitario': l.precio_unitario,
                'descuento': l.descuento_porcentaje,
                'iva_porcentaje': l.porcentaje_iva
            } for l in instancias_lineas
        ]
        
        totales = calculate_invoice_totals(
            lineas=lineas_para_totales,
            recargo=cliente.recargo_equivalencia,
            porcentaje_retencion=porcentaje_irpf
        )

        fecha_factura = form_data.get('fecha_factura')
        fecha_vencimiento = form_data.get('fecha_vencimiento')

        # Asignar o construir la instancia de Factura
        factura = factura_existente if (edit_mode and factura_existente) else Factura()

        if edit_mode and factura_existente:
            factura.lineas.clear()
            for linea in instancias_lineas:
                factura.lineas.append(linea)
            if era_borrador and pestana == 'Emitida':
                factura.fecha_factura = date.today()
            else:
                factura.fecha_factura = datetime.strptime(fecha_factura, '%Y-%m-%d').date() if fecha_factura else date.today()
        else:
            factura.tipo_factura = 'Ordinaria'
            factura.lineas = instancias_lineas
            factura.fecha_factura = datetime.strptime(fecha_factura, '%Y-%m-%d').date() if fecha_factura else date.today()

        factura.numero_factura = numero_factura
        factura.tipo_pestana = pestana
        factura.estado_ui = pestana
        factura.estado_contable = 'Emitida' if pestana != 'Borrador' else 'Borrador'
        factura.contacto_id = cliente.id
        factura.referencia = form_data.get('referencia', '').strip()
        factura.fecha_vencimiento = datetime.strptime(fecha_vencimiento, '%Y-%m-%d').date() if fecha_vencimiento else None
        
        factura.total_base_imponible = totales['base_imponible']
        factura.total_cuota_iva = totales['iva_total']
        factura.total_recargo_equivalencia = totales['recargo_total']
        factura.porcentaje_irpf = porcentaje_irpf
        factura.total_retencion_irpf = totales['retencion_total']
        factura.total_factura = totales['total']
        factura.metodo_pago_id = selected_metodo_pago_id

        if not edit_mode:
            db.session.add(factura)
            
        db.session.flush()
        return factura, None, None