import os
from app.factory import create_app

def test_create_app_testing_mode():
    """
    Test unitario para comprobar que la factoría crea la aplicación 
    y aplica correctamente la configuración de pruebas.
    """
    # --- 1. SETUP / PREPARACIÓN ---
    os.environ['PYTEST_CURRENT_TEST'] = 'True'

    # --- 2. EJECUCIÓN ---
    app = create_app()

    # --- 3. COMPROBACIONES / ASSERTS ---
    assert app is not None, "La factoría debería devolver una instancia de Flask."
    assert app.config['TESTING'] is True, "La configuración de pruebas debería estar activa."
    # Comprobamos que la variable 'date' se ha registrado en Jinja
    assert 'date' in app.jinja_env.globals

def test_blueprints_registered():
    """
    Test unitario para verificar que los Blueprints se registran correctamente.
    """
    # 1. SETUP
    os.environ['PYTEST_CURRENT_TEST'] = 'True'

    # 2. EJECUCIÓN
    app = create_app()

    # 3. COMPROBACIONES
    # Flask guarda los blueprints registrados en un diccionario (app.blueprints)
    registered_blueprints = app.blueprints

    assert 'auth' in registered_blueprints, "El Blueprint 'auth' debería estar registrado."
    assert 'contacts' in registered_blueprints, "El Blueprint 'contacts' debería estar registrado."
    assert 'invoices' in registered_blueprints, "El Blueprint 'invoices' debería estar registrado."
    assert 'expenses' in registered_blueprints, "El Blueprint 'expenses' debería estar registrado."
    assert 'budgets' in registered_blueprints, "El Blueprint 'budgets' debería estar registrado."
    assert 'products' in registered_blueprints, "El Blueprint 'products' debería estar registrado."
    assert 'payments' in registered_blueprints, "El Blueprint 'payments' debería estar registrado."
    assert 'config' in registered_blueprints, "El Blueprint 'config' debería estar registrado."
    assert 'delivery_notes' in registered_blueprints, "El Blueprint 'delivery_notes' debería estar registrado." 
    
def test_index_redirect(client):
    """
    Test unitario para comprobar que la ruta raíz (/) 
    redirige al login si no hay sesión iniciada.
    """
    response = client.get('/')
    assert response.status_code == 302
    assert '/login' in response.headers.get('Location', '')

from models import db, Producto  # Asegúrate de tener la importación arriba
from decimal import Decimal

def test_api_productos_legacy(auth_client):
    """
    Test unitario para comprobar que la ruta legacy /api/productos 
    devuelve los productos correctamente en formato JSON.
    """
    # --- 1. ARRANGE (Preparación) ---
    # Creamos un producto de prueba directamente en la base de datos en memoria
    producto_test = Producto(
        nombre="Taladro Percutor",
        precio_unitario_base=Decimal("150.00"),
        impuesto_defecto="21% IVA",
        descripcion_adicional="De prueba"
    )
    db.session.add(producto_test)
    db.session.commit()

    # --- 2. ACT (Ejecución) ---
    response = auth_client.get('/api/productos')

    # --- 3. ASSERT (Comprobaciones) ---
    assert response.status_code == 200
    assert response.is_json, "La respuesta debería ser JSON."
    
    # Comprobamos que el JSON contiene el producto que acabamos de crear
    data = response.get_json()
    assert len(data) > 0
    assert data[0]['nombre'] == "Taladro Percutor"

def test_guardar_gasto_legacy(auth_client):
    """
    Test unitario para comprobar que la ruta legacy /gasto/guardar 
    procesa el formulario y redirige correctamente a la vista de gastos.
    """
    # --- 1. ACT (Ejecución de la petición POST) ---
    response = auth_client.post('/gasto/guardar', data={
        'numero_factura_proveedor': 'FACT-001',
        'contacto_id': '1',
        'referencia': 'Compra de material',
        'tipo_gasto': 'Gasto operativa',
        'total_factura': '100.00'
    }, follow_redirects=True)

    # --- 2. ASSERT (Comprobaciones) ---
    assert response.status_code == 200
    # Comprobamos que tras la redirección aparece el mensaje flash de éxito
    assert b'Gasto guardado correctamente' in response.data
    
