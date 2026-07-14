# services/budget_service.py
from decimal import Decimal
from datetime import datetime, date
from models import db, Presupuesto, PresupuestoLinea, Contacto
from utils.tax_calculations import parse_impuesto_porcentaje
from utils.sequence_generators import generate_budget_number

class BudgetService:
    @staticmethod
    def parse_form_lines(form):
        """Analiza las líneas del formulario y devuelve la estructura de datos junto a los totales."""
        indices = set()
        for key in form.keys():
            if key.startswith('tipo_'):
                try:
                    indices.add(int(key.split('_')[1]))
                except ValueError:
                    continue
        
        lineas = []
        total_base = Decimal('0')
        total_impuestos = Decimal('0')

        for index in sorted(list(indices)):
            tipo = form.get(f'tipo_{index}', 'linea')
            if tipo == 'titulo':
                texto = form.get(f'titulo_{index}', '').strip()
                if texto:
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

            lineas.append({
                'tipo': 'linea',
                'concepto': concepto,
                'informacion': form.get(f'informacion_{index}', '').strip(),
                'unidades': str(unidades),
                'precio': str(precio),
                'descuento': str(descuento),
                'impuesto': impuesto,
                'total': str(total_linea),
            })
            total_base += linea_base
            total_impuestos += impuesto_val

        total_presupuesto = (total_base + total_impuestos).quantize(Decimal('0.01'))
        return lineas, total_base, total_impuestos, total_presupuesto

    @classmethod
    def create_budget(cls, form_data):
        """Encapsula la validación de negocio y persistencia al crear un presupuesto."""
        cliente_id = form_data.get('contacto_id')
        cliente = Contacto.query.get(int(cliente_id)) if cliente_id else None
        if not cliente:
            raise ValueError("Debe seleccionar un cliente")

        lineas, total_base, total_impuestos, total_presupuesto = cls.parse_form_lines(form_data)
        if not any(linea.get('tipo') != 'titulo' for linea in lineas):
            raise ValueError("Debes añadir al menos una línea de concepto para crear el presupuesto.")

        num_presupuesto = form_data.get('numero_presupuesto') or generate_budget_number()
        f_emision = form_data.get('fecha_emision')
        f_validez = form_data.get('fecha_validez')

        presupuesto = Presupuesto(
            numero_presupuesto=num_presupuesto,
            contacto_id=cliente.id,
            fecha_emision=datetime.strptime(f_emision, '%Y-%m-%d').date() if f_emision else date.today(),
            fecha_validez=datetime.strptime(f_validez, '%Y-%m-%d').date() if f_validez else date.today(),
            referencia=form_data.get('referencia', '').strip(),
            total_base_imponible=total_base,
            total_impuestos=total_impuestos,
            total_presupuesto=total_presupuesto,
            estado=form_data.get('estado', 'Borrador'),
            notas=form_data.get('notas', '').strip(),
            metodo_pago_id=int(form_data.get('metodo_pago_id')) if form_data.get('metodo_pago_id') else None
        )

        cls._populate_lines(presupuesto, lineas)
        db.session.add(presupuesto)
        db.session.commit()
        return presupuesto

    @classmethod
    def update_budget(cls, presupuesto, form_data):
        """Encapsula la actualización del presupuesto."""
        cliente_id = form_data.get('contacto_id')
        cliente = Contacto.query.get(int(cliente_id)) if cliente_id else None
        if not cliente:
            raise ValueError("Debe seleccionar un cliente")

        lineas, total_base, total_impuestos, total_presupuesto = cls.parse_form_lines(form_data)
        if not any(linea.get('tipo') != 'titulo' for linea in lineas):
            raise ValueError("Debes añadir al menos una línea de concepto para actualizar el presupuesto.")

        f_emision = form_data.get('fecha_emision')
        f_validez = form_data.get('fecha_validez')

        presupuesto.numero_presupuesto = form_data.get('numero_presupuesto') or presupuesto.numero_presupuesto
        presupuesto.contacto_id = cliente.id
        presupuesto.fecha_emision = datetime.strptime(f_emision, '%Y-%m-%d').date() if f_emision else date.today()
        presupuesto.fecha_validez = datetime.strptime(f_validez, '%Y-%m-%d').date() if f_validez else date.today()
        presupuesto.referencia = form_data.get('referencia', '').strip()
        presupuesto.notas = form_data.get('notas', '').strip()
        presupuesto.estado = form_data.get('estado', 'Borrador')
        presupuesto.total_base_imponible = total_base
        presupuesto.total_impuestos = total_impuestos
        presupuesto.total_presupuesto = total_presupuesto
        metodo_id = form_data.get('metodo_pago_id')
        presupuesto.metodo_pago_id = int(metodo_id) if metodo_id else None

        presupuesto.lineas.clear()
        cls._populate_lines(presupuesto, lineas)
        db.session.commit()
        return presupuesto

    @staticmethod
    def _populate_lines(presupuesto, lineas_data):
        """Helper privado para mapear diccionarios a modelos ORM."""
        for item in lineas_data:
            if item.get('tipo') == 'linea':
                nueva_linea = PresupuestoLinea(
                    concepto=item.get('concepto', ''),
                    informacion=item.get('informacion') or None,
                    unidades=Decimal(item.get('unidades', '1')),
                    precio_unitario=Decimal(item.get('precio', '0')),
                    descuento_porcentaje=Decimal(item.get('descuento', '0')),
                    impuesto_tipo=item.get('impuesto', '21% IVA'),
                    subtotal_linea=Decimal(item.get('total', '0'))
                )
                presupuesto.lineas.append(nueva_linea)
            elif item.get('tipo') == 'titulo':
                nueva_linea = PresupuestoLinea(
                    concepto=f"--- {item.get('texto', '')} ---",
                    informacion=None,
                    unidades=Decimal('0'),
                    precio_unitario=Decimal('0'),
                    subtotal_linea=Decimal('0')
                )
                presupuesto.lineas.append(nueva_linea)