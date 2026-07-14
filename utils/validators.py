import re

class BaseValidator:
    """Utilidades comunes de validación para reutilizar en cualquier formulario."""
    
    @staticmethod
    def validar_cif_nif(cif_nif: str) -> bool:
        # Validación básica de longitud y caracteres para España (9 caracteres alfanuméricos)
        if not cif_nif:
            return False
        return bool(re.match(r"^[A-Z0-9]{9}$", cif_nif.upper()))

    @staticmethod
    def validar_email(email: str) -> bool:
        if not email:
            return True  # Si es opcional, pasa la validación vacía
        return bool(re.match(r"^[^@]+@[^@]+\.[^@]+$", email))

    @staticmethod
    def validar_codigo_postal(cp: str) -> bool:
        if not cp:
            return True  # Si es opcional
        return bool(re.match(r"^[0-9]{5}$", cp))


class EmpresaValidator(BaseValidator):
    """Validaciones específicas para el formulario de Configuración de la Empresa."""
    
    @classmethod
    def validar(cls, form_data) -> list:
        errores = []
        
        if not form_data.get('nombre_empresa', '').strip():
            errores.append("El nombre de la empresa es obligatorio.")
            
        if not form_data.get('serie_factura', '').strip():
            errores.append("La serie de facturación es obligatoria.")
            
        cif = form_data.get('cif_nif', '').strip()
        if not cls.validar_cif_nif(cif):
            errores.append("El CIF/NIF debe tener 9 caracteres alfanuméricos válidos.")
            
        if not cls.validar_email(form_data.get('email', '')):
            errores.append("El correo electrónico corporativo no es válido.")
            
        if not cls.validar_codigo_postal(form_data.get('codigo_postal', '')):
            errores.append("El código postal debe tener exactamente 5 dígitos.")
            
        return errores


class ContactoValidator(BaseValidator):
    """Validaciones compartidas/especificas para Crear Clientes y Proveedores."""
    
    @classmethod
    def validar(cls, form_data) -> list:
        errores = []
        
        # Reglas comunes para Clientes / Proveedores
        nombre = form_data.get('nombre', '').strip() or form_data.get('razon_social', '').strip()
        if not nombre:
            errores.append("El nombre o razón social es obligatorio.")
            
        cif = form_data.get('cif_nif', '').strip()
        if cif and not cls.validar_cif_nif(cif):
            errores.append("El CIF/NIF del contacto no tiene un formato válido.")
            
        if not cls.validar_email(form_data.get('email', '')):
            errores.append("El correo electrónico del contacto no es válido.")
            
        if not cls.validar_codigo_postal(form_data.get('codigo_postal', '')):
            errores.append("El código postal debe ser de 5 dígitos.")
            
        return errores