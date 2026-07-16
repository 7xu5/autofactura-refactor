import xml.etree.ElementTree as ET
from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from models import Factura, FacturaLinea, Configuracion

# Namespaces oficiales AEAT Veri*Factu
NS_SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
NS_LR   = "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroLR.xsd"
NS_SI   = "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroInformacion.xsd"
NS_XSI  = "http://www.w3.org/2001/XMLSchema-instance"

# Registrar prefijos oficiales para que la AEAT los reconozca sin problemas
ET.register_namespace("soapenv", NS_SOAP)
ET.register_namespace("lr",      NS_LR)
ET.register_namespace("sf",      NS_SI)
ET.register_namespace("xsi",     NS_XSI)

def _lr(tag: str) -> str:
    return f"{{{NS_LR}}}{tag}"

def _si(tag: str) -> str:
    return f"{{{NS_SI}}}{tag}"

class VerifactuXmlBuilder:

    @staticmethod
    def _sub(padre: ET.Element, etiqueta: str, texto: Optional[str]) -> ET.Element:
        el = ET.SubElement(padre, etiqueta)
        el.text = str(texto) if texto is not None else ""
        return el

    @classmethod
    def construir_xml_alta(
        cls,
        factura: Factura,
        config: Configuracion,
        hash_actual: str,
        es_primer_registro: bool,  # <-- NUEVO: Control estricto de inicio de cadena
        hash_anterior: Optional[str] = None,
        factura_anterior: Optional[Factura] = None,
        fecha_registro: Optional[datetime] = None,
    ) -> bytes:
        """
        Genera el sobre SOAP completo que contiene el Registro de Alta de Factura.
        Sigue de manera milimétrica el orden secuencial exigido por el esquema XSD de la AEAT.
        """
        # 1. Crear el sobre SOAP Envelope como Raíz
        envelope = ET.Element(f"{{{NS_SOAP}}}Envelope")
        ET.SubElement(envelope, f"{{{NS_SOAP}}}Header")
        body = ET.SubElement(envelope, f"{{{NS_SOAP}}}Body")

        # 2. Insertar el elemento principal de Verifactu dentro del Body
        root = ET.SubElement(
            body, 
            f"{{{NS_LR}}}RegFactuSistemaFacturacion",
            {f"{{{NS_XSI}}}schemaLocation": f"{NS_LR} SuministroLR.xsd"}
        )

        # ── Cabecera ──
        cabecera = ET.SubElement(root, _lr("Cabecera"))
        obligado = ET.SubElement(cabecera, _si("ObligadoEmision"))
        cls._sub(obligado, _si("NombreRazon"), config.nombre_empresa)
        cls._sub(obligado, _si("NIF"), config.cif_nif)
        remision = ET.SubElement(cabecera, _si("RemisionVoluntaria"))
        cls._sub(remision, _si("Incidencia"), "N")
        
        # ── Registro de Factura ──
        registro = ET.SubElement(root, _lr("RegistroFactura"))
        alta     = ET.SubElement(registro, _si("RegistroAlta"))

        # (1) IDVersion
        cls._sub(alta, _si("IDVersion"), "1.0")

        # (2) IDFactura
        id_factura = ET.SubElement(alta, _si("IDFactura"))
        cls._sub(id_factura, _si("IDEmisorFactura"), config.cif_nif)
        cls._sub(id_factura, _si("NumSerieFactura"),        factura.numero_factura)
        cls._sub(id_factura, _si("FechaExpedicionFactura"), factura.fecha_factura.strftime("%d-%m-%Y"))

        # (3) NombreRazonEmisor
        cls._sub(alta, _si("NombreRazonEmisor"), config.nombre_empresa)
        
        # (4) TipoFactura
        es_ordinaria = (factura.tipo_factura == "Ordinaria")
        cls._sub(alta, _si("TipoFactura"), "F1" if es_ordinaria else "R1")

        # (5) TipoRectificativa & (6) ImporteRectificacion (Solo si no es F1)
        if not es_ordinaria:
            # Dado que tu modal genera un abono de importes invertidos, la norma de la AEAT
            # exige obligatoriamente usar tipo "I" (Por diferencias).
            cls._sub(alta, _si("TipoRectificativa"), "I")
            
            # Al ser tipo "I", el bloque <sf:ImporteRectificacion> está terminantemente prohibido por la AEAT.
            # Por lo tanto, no lo creamos aquí.

        # (7) DescripcionOperacion dinámica capturando el motivo real seleccionado en tu UI
        # Recuperamos el motivo si tu modelo Factura lo almacena (asumiendo que guardas el string del select)
        motivo_ui = getattr(factura, 'motivo_rectificacion', None)
        
        if not es_ordinaria and motivo_ui:
            descripcion_final = f"Factura Rectificativa. Motivo: {motivo_ui}"
        elif not es_ordinaria:
            descripcion_final = "Factura Rectificativa por diferencias / Abono"
        else:
            descripcion_final = "Venta de servicios/productos"

        # (7) DescripcionOperacion
        cls._sub(alta, _si("DescripcionOperacion"), descripcion_final[:250])

        # (8) Destinatarios -> EXIGIDO AQUÍ POR EL XSD ANTES DEL DESGLOSE
        nombre_cliente = factura.contacto.nombre_fiscal   if factura.contacto else "CLIENTE DESCONOCIDO"
        nif_cliente    = factura.contacto.numero_documento if factura.contacto else ""

        destinatarios = ET.SubElement(alta, _si("Destinatarios"))
        id_dest       = ET.SubElement(destinatarios, _si("IDDestinatario"))
        cls._sub(id_dest, _si("NombreRazon"), nombre_cliente)
        cls._sub(id_dest, _si("NIF"),         nif_cliente)

        # (9) Desglose
        lineas_factura: List[FacturaLinea] = factura.lineas  # type: ignore
        impuestos_agrupados = {}
        for linea in lineas_factura:
            clave = (linea.impuesto_tipo, linea.porcentaje_iva)
            if clave not in impuestos_agrupados:
                impuestos_agrupados[clave] = {"base": Decimal("0.00"), "cuota": Decimal("0.00")}
            base_linea = Decimal(str(linea.subtotal_linea))
            porcentaje = Decimal(str(linea.porcentaje_iva)) / Decimal("100")
            impuestos_agrupados[clave]["base"]  += base_linea
            impuestos_agrupados[clave]["cuota"] += base_linea * porcentaje

        desglose = ET.SubElement(alta, _si("Desglose"))
        for (tipo, porcentaje), totales in impuestos_agrupados.items():
            detalle = ET.SubElement(desglose, _si("DetalleDesglose"))
            
            # --- 1. DETECCIÓN DINÁMICA DE IMPUESTO (IVA / IGIC) ---
            tipo_upper = str(tipo or '').upper()
            if "IGIC" in tipo_upper:
                cls._sub(detalle, _si("Impuesto"), "03")  # 03 = IGIC
            else:
                cls._sub(detalle, _si("Impuesto"), "01")  # 01 = IVA (Península/Baleares)
                
            cls._sub(detalle, _si("ClaveRegimen"), "01")
            
            # --- 2. GESTIÓN DINÁMICA DE SUJECIÓN (EXENTA S2 / NO EXENTA S1) ---
            # Si el porcentaje es 0 y contiene la palabra "EXENTA" o similar en la UI
            if porcentaje == Decimal('0') or "EXENTA" in tipo_upper:
                cls._sub(detalle, _si("CalificacionOperacion"), "S2")  # S2 = Sujeta - Exenta
            else:
                cls._sub(detalle, _si("CalificacionOperacion"), "S1")  # S1 = Sujeta - No Exenta
            
            # --- 3. FORMATEO ESTRICTO DE TIPO IMPOSITIVO (ENTERO EN STRING) ---
            # Pasamos de Decimal('21') o Decimal('7') directamente a "21" o "7" sin puntos ni decimales
            tipo_impositivo_str = str(int(porcentaje))
            cls._sub(detalle, _si("TipoImpositivo"), tipo_impositivo_str)
            
            cls._sub(detalle, _si("BaseImponibleOimporteNoSujeto"), f"{totales['base']:.2f}")
            cls._sub(detalle, _si("CuotaRepercutida"), f"{totales['cuota']:.2f}")

        # (10) CuotaTotal
        cls._sub(alta, _si("CuotaTotal"),    f"{factura.total_cuota_iva:.2f}")
        # (11) ImporteTotal
        cls._sub(alta, _si("ImporteTotal"),  f"{factura.total_factura:.2f}")

        # (12) Encadenamiento
        encadenamiento = ET.SubElement(alta, _si("Encadenamiento"))
        if es_primer_registro:
            # Defensa simétrica a la del bloque 'else': si alguien declara
            # explícitamente "soy el primer registro" pero a la vez aporta
            # un hash_anterior real, hay una inconsistencia entre el flag
            # y el dato. Preferimos abortar a ignorar el hash_anterior en
            # silencio y falsificar la cadena marcando como génesis un
            # registro que en realidad tiene un eslabón previo.
            if hash_anterior:
                raise ValueError(
                    f"Fallo crítico en VerifactuXmlBuilder: se indicó "
                    f"es_primer_registro=True para la factura "
                    f"{factura.numero_factura}, pero se proporcionó un "
                    f"hash_anterior ('{hash_anterior[:10]}...'). Esto es "
                    f"una inconsistencia entre el flag y el dato real: "
                    f"o la factura no es el primer registro, o no debería "
                    f"viajar un hash_anterior. Revisa el llamador."
                )
            cls._sub(encadenamiento, _si("PrimerRegistro"), "S")

        else:
            # Si declaramos que NO es el primer registro, es MANDATORIO que existan los datos previos
            if not hash_anterior or not factura_anterior:
                raise ValueError(
                    f"Fallo crítico en VerifactuXmlBuilder: Se indicó que la factura {factura.numero_factura} "
                    f"NO es el primer registro, pero la huella o el objeto de la factura anterior no fueron "
                    f"proporcionados correctamente por el orquestador de base de datos."
                )

            registro_ant = ET.SubElement(encadenamiento, _si("RegistroAnterior"))
            cls._sub(registro_ant, _si("IDEmisorFactura"), config.cif_nif)
            cls._sub(registro_ant, _si("NumSerieFactura"), factura_anterior.numero_factura)
            cls._sub(registro_ant, _si("FechaExpedicionFactura"), factura_anterior.fecha_factura.strftime("%d-%m-%Y"))
            cls._sub(registro_ant, _si("Huella"), hash_anterior.upper())

        # (13) Sistema Informático
        sistema = ET.SubElement(alta, _si("SistemaInformatico"))
        cls._sub(sistema, _si("NombreRazon"),          config.nombre_empresa)
        cls._sub(sistema, _si("NIF"),                  config.cif_nif)
        cls._sub(sistema, _si("NombreSistemaInformatico"), "AutoFactura-V9")
        cls._sub(sistema, _si("IdSistemaInformatico"), "01")
        cls._sub(sistema, _si("Version"),              "1.0")
        cls._sub(sistema, _si("NumeroInstalacion"),    "001")
        cls._sub(sistema, _si("TipoUsoPosibleSoloVerifactu"), "S")
        cls._sub(sistema, _si("TipoUsoPosibleMultiOT"),       "N")
        cls._sub(sistema, _si("IndicadorMultiplesOT"),         "N")

        # (14) FechaHoraHusoGenRegistro
        registro_ts = fecha_registro or datetime.now()
        xml_ts_str = registro_ts.astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
        if len(xml_ts_str) > 22 and xml_ts_str[-5] in ['+', '-'] and ":" not in xml_ts_str[-3:]:
            xml_ts_str = xml_ts_str[:-2] + ":" + xml_ts_str[-2:]
            
        cls._sub(alta, _si("FechaHoraHusoGenRegistro"), xml_ts_str)
        
        # (15) TipoHuella
        cls._sub(alta, _si("TipoHuella"), "01")  # SHA-256
        
        # (16) Huella
        cls._sub(alta, _si("Huella"), hash_actual)

        # Retornar todo el árbol XML serializado de golpe
        return ET.tostring(envelope, encoding="utf-8", xml_declaration=True)