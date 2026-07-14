import hashlib
from datetime import datetime
from typing import Optional
from models import Factura, FacturaVerifactu

class VerifactuHashMotor:
    """
    Motor encargado de la normalización estricta de datos y la generación
    del Hash encadenado (SHA-256) exigido por la normativa Veri*Factu.
    """

    @staticmethod
    def obtener_hash_anterior() -> Optional[str]:
        """
        Busca el último registro consolidado en la tabla inmutable de VeriFactu
        para extraer su huella digital y encadenar el nuevo registro.
        """
        ultimo_registro = FacturaVerifactu.query.order_by(FacturaVerifactu.fecha_hora_alta.desc()).first()
        if ultimo_registro:
            return ultimo_registro.hash_actual
        return None # Primer registro del sistema (bloque génesis)

    @classmethod
    def generar_hash_registro(cls, factura: Factura, fecha_registro: Optional[datetime] = None) -> tuple[str, Optional[str]]:
        """
        Genera el SHA-256 definitivo de la factura combinando sus datos
        en el formato oficial QueryString (Clave=Valor&Clave=Valor) exigido por la AEAT.
        
        Retorna:
            tuple: (hash_actual_hex, hash_anterior_hex)
        """
        # 1. Recuperar la configuración para el NIF del Emisor
        from models import Configuracion
        config = Configuracion.query.first()
        emisor_nif = str(config.cif_nif).strip().upper() if (config and config.cif_nif) else "NIF_EMISOR_FALTANTE"

        # 2. Extraer y formatear datos igual que en el XML/XSD
        num_serie = str(factura.numero_factura).strip()
        fecha_exp = factura.fecha_factura.strftime("%d-%m-%Y")
        tipo_factura = "F1" if factura.tipo_factura == "Ordinaria" else "R1"
        
        cuota_total = f"{factura.total_cuota_iva:.2f}"
        importe_total = f"{factura.total_factura:.2f}"
        
        # 3. Recuperar el eslabón anterior de la cadena (minúsculas tal como lo refleja el log de la AEAT)
        hash_anterior = cls.obtener_hash_anterior()
        huella_ant = str(hash_anterior).strip().upper() if hash_anterior else ""
        
        # 4. Establecer la marca de tiempo exacta (debe ser idéntica a la que se use en el XML)
        ts = fecha_registro or datetime.now()
        fecha_huso = ts.astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
        if len(fecha_huso) > 22 and fecha_huso[-5] in ['+', '-'] and ":" not in fecha_huso[-3:]:
            fecha_huso = fecha_huso[:-2] + ":" + fecha_huso[-2:]

        # 5. Construir la cadena plana con el orden secuencial EXACTO legal
        partes = [
            f"IDEmisorFactura={emisor_nif}",
            f"NumSerieFactura={num_serie}",
            f"FechaExpedicionFactura={fecha_exp}",
            f"TipoFactura={tipo_factura}",
            f"CuotaTotal={cuota_total}",
            f"ImporteTotal={importe_total}",
            f"Huella={huella_ant}",
            f"FechaHoraHusoGenRegistro={fecha_huso}"
        ]
        
        cadena_plana = "&".join(partes)
        
        # 6. Calcular el Hash SHA-256 en MAYÚSCULAS (Hacienda lo calcula y devuelve en mayúsculas)
        hash_sha256 = hashlib.sha256(cadena_plana.encode('utf-8')).hexdigest().upper()
        
        return hash_sha256, hash_anterior