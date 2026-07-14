import enum

class EstadoConciliacion(enum.Enum):
    ok = 'ok'
    fantasma_alta = 'fantasma_alta'
    anulada_en_aeat_no_reflejada = 'anulada_en_aeat_no_reflejada'
    pendiente_verificar = 'pendiente_verificar'

class OrigenDeteccion(enum.Enum):
    post_restauracion = 'post_restauracion'
    manual = 'manual'