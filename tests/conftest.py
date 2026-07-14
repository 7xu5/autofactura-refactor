"""
tests/conftest.py
==================
Fixtures compartidas para los tests de caracterización de blueprints/invoices.

Filosofía: estos tests describen el comportamiento ACTUAL de views.py,
incluyendo sus inconsistencias conocidas (ver comentarios "DIVERGENCIA").
Sirven de red de seguridad para el refactor: si algo cambia sin querer,
un test se rompe aquí antes de llegar a producción.

Cómo correrlos:
    pip install pytest --break-system-packages   # si no lo tienes ya
    - Para ver el detalle de cada test (saber cuál pasa y cuál falla uno a uno): pytest tests/ -v
    - Para ejecutar los tests en paralelo usando todos los núcleos de tu procesador (más rápido): pytest tests/ -n auto
    - Para detener la ejecución inmediatamente en el primer test que falle (muy útil para depurar): pytest tests/ -x
    - Para ver los mensajes de print() o logs que tengas en el código mientras se ejecutan los tests: pytest tests/ -s
    - Para lanzar los test que necesitan la ruta xsd:
    pytest tests/test_verifactu_integracion.py -x --xsd=tests/xsd/SuministroLR.xsd
    - Para lanzar todos incluidos los de las rustas xsd:
    pytest tests/ -x -v --xsd=tests/xsd/SuministroLR.xsd

TODO
    Crear pytest.ini para añadir las rutas y solo tener que ejcutar con pytest tests/ -x, se inyectará el XSD entre bastidores y verás el 100% de tus pruebas ejecutadas sin un solo skip.
    
    # pytest.ini
    [pytest]
    addopts = --xsd=tests/xsd/SuministroLR.xsd
"""
import os

os.environ["PYTEST_CURRENT_TEST"] = "True"
import sys
from datetime import date
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app as flask_app  # noqa: E402
from models import (  # noqa: E402
    db,
    Contacto,
    Configuracion,
    MetodoPago,
    Factura,
    FacturaLinea,
)


@pytest.fixture()
def app():
    """App Flask configurada para ignorar cualquier otra DB y usar memoria."""
    
    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def auth_client(client):
    """Cliente con sesión ya autenticada (bypassa el login real de auth_bp)."""
    with client.session_transaction() as sess:
        sess["user_id"] = 1
    return client


@pytest.fixture()
def configuracion(app):
    """
    NIF en minúscula a propósito: ver TestDivergenciaQR en
    test_invoices_routes.py, que comprueba que una ruta lo normaliza
    (.strip().upper()) y la otra no.
    """
    cfg = Configuracion(
        nombre_empresa="Empresa Test S.L.",
        serie_factura="F26-",
        numero_inicial_factura=1,
        serie_rectificativa="R26-",
        numero_inicial_rectificativa=1,
        serie_presupuesto="PR26-",
        numero_inicial_presupuesto=1,
        cif_nif="b12345678",
        impuesto_defecto="21% IVA",
        ruta_certificado=None,
    )
    db.session.add(cfg)
    db.session.commit()
    return cfg


@pytest.fixture()
def cliente(app, configuracion):
    c = Contacto(
        nombre_fiscal="Cliente Test S.L.",
        numero_documento="B87654321",
        tipo_documento="CIF",
        impuesto_defecto="21% IVA",
        recargo_equivalencia=False,
    )
    db.session.add(c)
    db.session.commit()
    return c


@pytest.fixture()
def cliente_recargo(app, configuracion):
    """Cliente con recargo de equivalencia activo, para tests de ese cálculo."""
    c = Contacto(
        nombre_fiscal="Autónomo Recargo S.L.",
        numero_documento="B11122233",
        tipo_documento="CIF",
        impuesto_defecto="21% IVA",
        recargo_equivalencia=True,
    )
    db.session.add(c)
    db.session.commit()
    return c


@pytest.fixture()
def metodo_pago(app):
    m = MetodoPago(nombre="Transferencia", tipo="Transferencia", defecto=True)
    db.session.add(m)
    db.session.commit()
    return m


def crear_factura_db(
    cliente,
    numero="F26-001",
    unidades=Decimal("2"),
    precio=Decimal("100"),
    tipo_factura="Ordinaria",
    estado_ui="Emitida",
    verifactu_estado="Pendiente",
):
    """Helper para insertar una Factura + 1 línea directamente en BD,
    sin pasar por HTTP. Útil para tests que parten de un estado ya creado
    (rectificar, eliminar, cobrar, descargar, QR...)."""
    base = (unidades * precio).quantize(Decimal("0.01"))
    iva = (base * Decimal("21") / Decimal("100")).quantize(Decimal("0.01"))
    factura = Factura(
        numero_factura=numero,
        tipo_factura=tipo_factura,
        tipo_pestana="Emitida" if estado_ui == "Emitida" else "Borrador",
        estado_ui=estado_ui,
        estado_contable="Pendiente",
        contacto_id=cliente.id,
        referencia="Ref",
        fecha_factura=date(2026, 6, 1),
        total_base_imponible=base,
        total_cuota_iva=iva,
        total_recargo_equivalencia=Decimal("0.00"),
        total_factura=(base + iva).quantize(Decimal("0.01")),
        verifactu_estado=verifactu_estado,
        lineas=[
            FacturaLinea(
                concepto="Servicio de prueba",
                unidades=unidades,
                precio_unitario=precio,
                descuento_porcentaje=Decimal("0.00"),
                impuesto_tipo="21% IVA",
                porcentaje_iva=Decimal("21.00"),
                porcentaje_recargo=Decimal("0.00"),
                subtotal_linea=base,
            )
        ],
    )
    db.session.add(factura)
    db.session.commit()
    return factura


def pytest_addoption(parser):
    """Registra la opción --xsd para que pytest la reconozca."""
    parser.addoption(
        "--xsd", 
        action="store", 
        default=None, 
        help="Ruta a los archivos XSD para validación"
    )

def pytest_configure(config):
    """
    Cuando se inicia pytest, si se pasó --xsd, actualizamos la variable
    XSD_PATH en el módulo de integración.
    """
    xsd_path = config.getoption("--xsd")
    if xsd_path:
        from tests import test_verifactu_integracion
        test_verifactu_integracion.XSD_PATH = xsd_path