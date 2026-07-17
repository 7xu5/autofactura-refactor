from datetime import date
from decimal import Decimal
from sqlalchemy import select, func
from models import db, Factura, FacturaLinea
from utils.sequence_generators import generate_invoice_number

class InvoiceManagementService:

    @staticmethod
    def cobrar_factura(factura_id: int) -> tuple[dict | None, str | None]:
        """Cambia el estado contable de una factura a 'Cobrada'."""
        factura = db.session.get(Factura, factura_id)
        if not factura:
            return None, "Factura no encontrada."
        
        factura.estado_contable = 'Cobrada'
        db.session.commit()
        return {'status': 'ok', 'estado_pago': factura.estado_contable}, None

    @staticmethod
    def eliminar_factura(factura_id: int) -> tuple[dict | None, str | None]:
        """Elimina físicamente una factura del sistema."""
        factura = db.session.get(Factura, factura_id)
        if not factura:
            return None, "Factura no encontrada."
            
        db.session.delete(factura)
        db.session.commit()
        return {'status': 'ok'}, None

    @staticmethod
    def duplicar_factura(factura_id: int) -> tuple[dict | None, str | None]:
        """
        Duplica una factura existente como un nuevo borrador.
        Implementa reintento automático si colisiona el número oficial generado.
        """
        original = db.session.get(Factura, factura_id)
        if not original:
            return None, "Factura original no encontrada."

        lineas_relacion: list[FacturaLinea] = original.lineas  # type: ignore[assignment]
        nuevas_lineas = [
            FacturaLinea(
                concepto=l.concepto,
                informacion=l.informacion,
                unidades=l.unidades,
                precio_unitario=l.precio_unitario,
                descuento_porcentaje=l.descuento_porcentaje,
                impuesto_tipo=l.impuesto_tipo,
                porcentaje_iva=l.porcentaje_iva,
                porcentaje_recargo=l.porcentaje_recargo,
                subtotal_linea=l.subtotal_linea,
            )
            for l in lineas_relacion
        ]

        numero_oficial = generate_invoice_number()

        nueva = Factura(
            numero_factura=numero_oficial,
            tipo_pestana='Borrador',
            estado_ui='Borrador',
            estado_contable='Borrador',
            contacto_id=original.contacto_id,
            referencia=original.referencia,
            fecha_factura=date.today(),
            fecha_vencimiento=original.fecha_vencimiento,
            total_base_imponible=original.total_base_imponible,
            total_cuota_iva=original.total_cuota_iva,
            total_recargo_equivalencia=original.total_recargo_equivalencia,
            porcentaje_irpf=original.porcentaje_irpf,
            total_retencion_irpf=original.total_retencion_irpf,
            total_factura=original.total_factura,
            metodo_pago_id=original.metodo_pago_id,
            lineas=nuevas_lineas,
        )

        try:
            db.session.add(nueva)
            db.session.commit()
            return {'new_id': nueva.id, 'new_numero': nueva.numero_factura}, None
            
        except Exception:
            db.session.rollback()
            db.session.expire_all() 
            nueva.numero_factura = generate_invoice_number()
            
            try:
                db.session.add(nueva)
                db.session.commit()
                return {'new_id': nueva.id, 'new_numero': nueva.numero_factura}, None
            except Exception as e_final:
                db.session.rollback()
                return None, f"Error de duplicidad persistente: {str(e_final)}"

    @staticmethod
    def rectificar_factura(factura_id: int, motivo: str) -> tuple[dict | None, str | None]:
        """Genera un borrador en negativo de una factura emitida para subsanación o abono."""
        original = db.session.get(Factura, factura_id)
        if not original:
            return None, "Factura original no encontrada."
        
        if original.estado_ui == 'Borrador':
            return None, "No se puede rectificar un borrador."

        if not motivo:
            motivo = 'Error material / Subsanación de datos'

        try:
            lineas_relacion: list[FacturaLinea] = original.lineas  # type: ignore[assignment]
            nuevas_lineas = [
                FacturaLinea(
                    producto_id=l.producto_id,
                    concepto=f"Rectificación {original.numero_factura}: {l.concepto}",
                    unidades=l.unidades * Decimal('-1'),
                    precio_unitario=l.precio_unitario,
                    descuento_porcentaje=l.descuento_porcentaje,
                    impuesto_tipo=l.impuesto_tipo,
                    porcentaje_iva=l.porcentaje_iva,
                    porcentaje_recargo=l.porcentaje_recargo,
                    subtotal_linea=l.subtotal_linea * Decimal('-1')
                )
                for l in lineas_relacion
            ]

            stmt = select(func.count(Factura.id)).filter_by(estado_ui='Borrador')
            conteo_borradores = (db.session.scalar(stmt) or 0) + 1
            anio_corto = str(date.today().year)[2:]
            num_provisional = f"B-R{anio_corto}-{conteo_borradores:03d}"

            rectificativa = Factura(
                numero_factura=num_provisional,
                tipo_factura='Rectificativa',
                tipo_pestana='Borrador',
                estado_ui='Borrador',
                estado_contable='Borrador',
                contacto_id=original.contacto_id,
                metodo_pago_id=original.metodo_pago_id,
                referencia=f"Abono de {original.numero_factura}",
                referencia_presupuesto=original.referencia_presupuesto,
                fecha_factura=date.today(),
                fecha_vencimiento=date.today(),
                
                total_base_imponible=original.total_base_imponible * Decimal('-1'),
                total_cuota_iva=original.total_cuota_iva * Decimal('-1'),
                total_recargo_equivalencia=original.total_recargo_equivalencia * Decimal('-1'),
                total_factura=original.total_factura * Decimal('-1'),
                
                factura_rectificada_id=original.id,
                motivo_rectificacion=motivo,
                lineas=nuevas_lineas
            )

            db.session.add(rectificativa)
            db.session.commit()
            
            return {'success': True, 'new_id': rectificativa.id}, None
            
        except Exception as e:
            db.session.rollback()
            return None, f"No se pudo generar la rectificativa: {str(e)}"