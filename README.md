![logo](static/logo2.svg)

# AutoFactura — Sistema de Facturación para Autónomos

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-2.x/3.x-000000?style=for-the-badge&logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![SQLite](https://img.shields.io/badge/SQLite-3-003B57?style=for-the-badge&logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![License: CC BY-NC-SA 4.0](https://img.shields.io/badge/License-CC_BY--NC--SA_4.0-lightgrey?style=for-the-badge)](https://creativecommons.org/licenses/by-nc-sa/4.0/deed.es)
[![AEAT VeriFactu](https://img.shields.io/badge/AEAT-VERI*FACTU-Hacienda?style=for-the-badge&labelColor=FFD700&color=B22222)](https://sede.agenciatributaria.gob.es/)

Aplicación web de facturación y control de gastos orientada a autónomos, construida con **Python / Flask** siguiendo una arquitectura modular basada en Blueprints (patrón MVC). Cubre el ciclo comercial completo: emisión de facturas, control de gastos, presupuestos, albaranes y cumplimiento fiscal en tiempo real con la AEAT a través del sistema **VERI\*FACTU**.

## Tabla de contenidos

- [Resumen rápido](#resumen-rápido)
- [¿Por qué nace AutoFactura?](#por-qué-nace-autofactura)
- [Características principales](#características-principales)
- [Inicio rápido](#inicio-rápido)
- [Primer usuario y primer acceso](#primer-usuario-y-primer-acceso)
- [Copias de seguridad y restauración](#copias-de-seguridad-y-restauración)
- [Flujo de negocio recomendado](#flujo-de-negocio-recomendado)
- [Ejemplo mínimo de uso](#ejemplo-mínimo-de-uso)
- [Resolución de problemas habituales](#resolución-de-problemas-habituales)
- [Instalación](#instalación)
- [Arquitectura](#arquitectura)
- [Esquema de base de datos](#esquema-de-base-de-datos)
- [Tests](#tests)
- [Notas y limitaciones](#notas-y-limitaciones)
- [Distribución y licencia](#distribución-y-licencia)
- [Disclaimer / exención de responsabilidad](#disclaimer--exención-de-responsabilidad)

## Resumen rápido

AutoFactura es una herramienta pensada para cubrir el día a día de un autónomo o pequeño negocio que necesita gestionar facturación, gastos, presupuestos, albaranes y pagos sin depender de herramientas propietarias o de suscripciones. La app combina una interfaz web sencilla con una lógica de negocio orientada a la realidad fiscal española.

## ¿Por qué nace AutoFactura?

Este proyecto surgió por una necesidad real de independencia y control de costes en la gestión del día a día.

Como usuario de herramientas tradicionales de contabilidad (como *Contasol*), me vi afectado por un cambio en su modelo de negocio: el software decidió separar la funcionalidad de facturación en una plataforma externa e independiente (*Billin*). Lo que inicialmente se ofreció como un módulo gratuito, pronto se convirtió en un servicio de suscripción de pago obligatorio, a pesar de que el programa principal seguía manteniendo prácticamente el mismo precio.

Ante esta situación de costes duplicados y fragmentación de herramientas, decidí desarrollar mi propia alternativa unificada:

- **Todo en un mismo lugar:** una única herramienta ágil que cubre el ciclo completo (presupuestos, albaranes, facturas y gastos) sin necesidad de módulos externos ni cuotas mensuales.
- **Adaptado a la ley actual:** se integra de forma nativa con el sistema de registro de facturación **VERI\*FACTU** exigido por la AEAT.
- **Control y simplicidad:** un software ligero, adaptado a dispositivos móviles y pensado para cubrir las necesidades reales de un autónomo, sin la complejidad de los grandes programas genéricos.

## Características principales

### Módulos funcionales

- **Autenticación** — login/logout con control de acceso por sesión.
- **Contactos (clientes y proveedores)** — base de datos unificada con soporte para NIF/CIF, rol comercial (Cliente, Proveedor o Ambas), condiciones fiscales (IVA / IGIC) y enriquecimiento automático de datos desde el BORME vía `OpenMercantilService`.
- **Facturas emitidas** — creación, edición (solo borradores), previsualización PDF y descarga. Estados: `Borrador`, `Emitida`, `Cobrada`, `Vencida`. Soporte para facturas rectificativas (serie `R26-XXX`).
- **Gastos recibidos** — registro manual con subida de documentos. Cálculo automático de base imponible, cuotas y retenciones. Control de duplicados por proveedor y número de factura.
- **Presupuestos** — flujo completo con estados (`Borrador`, `Enviado`, `Aceptado`, `Rechazado`). Conversión directa a factura con trazabilidad de origen.
- **Albaranes** — numeración secuencial automática (`ALB26-0001`). Conversión a factura ordinaria con actualización de estado a `Facturado`.
- **Catálogo de productos y servicios** — autocompletado predictivo en líneas de factura vía `/api/productos`.
- **Registro de pagos** — conciliación automática de estado (`Cobrada` / `Pagada`) al registrar un abono por el importe total.
- **Configuración** — serie de factura, moneda, método de pago por defecto, impuesto predeterminado y configuración del certificado digital para VeriFactu.

### Motores de cálculo fiscal

Cálculo automatizado de bases imponibles, cuotas de IVA (`4%`, `10%`, `21%`) e IGIC (`3%`, `7%`, `9%`, `13%`), retenciones de IRPF, tanto en ventas como en gastos. El tipo `Exento` / `0%` se trata sin errores.

### Cumplimiento VERI\*FACTU (Ley Antifraude)

Implementación nativa contra la AEAT sin dependencias de terceros de pago:

- **Hash SHA-256 encadenado** — cada factura emitida calcula su `hash_actual` a partir de sus campos fiscales clave y el `hash_anterior`, formando una cadena inmutable auditable. La primera factura de la serie actúa como bloque génesis (`hash_anterior = ""`).
- **Construcción XML** — `VerifactuXmlBuilder` genera el árbol XML conforme a los esquemas oficiales `SuministroLR.xsd` y `SuministroInformacion.xsd` con los namespaces y metadatos del sistema homologado (`AutoFactura-V8`, versión `1.0`).
- **Firma XAdES-BES** — `VerifactuSigner` extrae la clave privada del certificado PKCS#12 (`.p12` / `.pfx`) en memoria y aplica firma criptográfica asimétrica `rsa-sha256`.
- **Transmisión mTLS** — `VerifactuClient` abre un túnel TLS con autenticación mutua hacia el endpoint de la AEAT (`/VerifactuSOAP`). Los ficheros PEM temporales se destruyen inmediatamente tras el envío.
- **Ciclo de vida del registro** — `Pendiente → Enviado_Aceptado / Rechazado`. El CSV devuelto por Hacienda se almacena en `csv_aeat`. Los rechazos se registran en `registro_eventos` con tipo `Error_Critico` y se muestran con badge de alerta en el listado de facturas.
- **Log de auditoría inmutable** — tabla `registro_eventos` requerida por la Ley Antifraude, con tipos de evento fijos: `Alta_Factura`, `Anulacion_Factura`, `Acceso_Sistema`, `Error_Critico`.
- **Código QR en PDF** — el PDF descargado incluye el QR de verificación de la AEAT y el literal `VERI*FACTU` en la posición reglamentaria.
- **Facturas rectificativas** — las facturas emitidas son inmutables. Para subsanar errores se genera una factura rectificativa (serie `R26-XXX`) con `motivo_rectificacion` obligatorio, que encadena correctamente en la cadena de hashes sin alterar el registro original.

## Inicio rápido

### Requisitos

- Python 3.10 o superior
- pip
- Entorno virtual recomendado

### Instalación en Windows

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Instalación en Linux/macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Ejecutar la aplicación

```bash
python app.py
```

Abre tu navegador en:

```text
http://127.0.0.1:5000
```

### Primeros pasos

1. Accede a la interfaz y autentícate.
2. Configura los datos de tu empresa.
3. Añade contactos, productos y tus primeros gastos/facturas.
4. Explora los módulos de facturas, presupuestos, pagos y albaranes.

> La primera ejecución genera automáticamente un archivo `.env` con claves seguras si no existe.

## Primer usuario y primer acceso

La primera vez que arrancas la aplicación no habrá usuarios registrados. En ese caso, la pantalla de login mostrará un asistente de primer arranque con un formulario para crear el usuario principal.

Pasos recomendados:

1. Arranca la app con `python app.py`.
2. Entra en `http://127.0.0.1:5000`.
3. Rellena `Nuevo Usuario` y `Contraseña del Usuario` en el formulario visible al abrir la app por primera vez.
4. Inicia sesión con esas credenciales.
5. Desde la sección de configuración, rellena los datos de tu empresa y, si vas a usar VeriFactu, sube un certificado `.p12` o `.pfx`.

> Si la base de datos ya tiene un usuario creado, la pantalla mostrará directamente el formulario de login y no volverá a aparecer el asistente.

## Copias de seguridad y restauración

La aplicación incluye un subsistema simple de copias de seguridad y restauración. Su funcionamiento es el siguiente:

- En la sección de configuración puedes indicar una carpeta local de destino para guardar los backups.
- El sistema genera archivos cifrados con nombres del tipo `backup_cifrado_YYYYMMDD_HHMMSS.enc`.
- La restauración se puede hacer desde la interfaz de configuración o desde la línea de comandos en caso de emergencia.

### Restauración desde la interfaz

1. Ve a Configuración.
2. Define una ruta válida y con permisos de escritura.
3. Desde la tabla de backups, selecciona el archivo que quieras restaurar.
4. Introduce la clave Fernet usada al crear el backup y confirma.

### Restauración desde consola

Si necesitas recuperar la base de datos desde un backup sin abrir la interfaz, puedes ejecutar:

```bash
flask --app app restore-emergency --file ruta/al/backup.enc --key tu-clave-fernet
```

Si no pasas `--key`, el comando te pedirá la clave de forma interactiva. El comando usa la ruta de base de datos configurada en la app y deja un backup temporal en la carpeta `instance/temp_backups` mientras valida el archivo.

## Flujo de negocio recomendado

AutoFactura está pensada para cubrir el ciclo comercial completo, no solo para emitir facturas aisladas. Un flujo útil es el siguiente:

1. Crear un presupuesto.
2. Convertirlo en albarán si el cliente lo acepta y se realiza la entrega.
3. Convertir el albarán en factura o emitir la factura directamente.
4. Registrar el pago o abono cuando el cliente pague.

Este recorrido encaja bien con los módulos de `presupuestos`, `albaranes`, `facturas` y `pagos`.

## Ejemplo mínimo de uso

Un primer ejemplo de prueba muy sencillo sería:

1. Crear un contacto de tipo cliente con un NIF/CIF válido.
2. Crear un producto o servicio como `Consultoría` con un precio de ejemplo.
3. Ir a Facturas y crear una factura nueva usando ese cliente y ese producto.
4. Guardarla como borrador o emitirla según el estado que quieras probar.
5. Registrar un pago posterior para cerrar el ciclo.

Este recorrido permite comprobar que la app responde correctamente sin necesidad de empezar por un caso complejo.

## Resolución de problemas habituales

### El navegador muestra “Address already in use”

Significa que el puerto `5000` ya está ocupado. Cierra el proceso anterior o cambia el puerto desde la configuración de ejecución.

### No aparece el formulario para crear el primer usuario

Eso suele pasar cuando la base de datos ya tiene al menos un usuario. En ese caso, entra directamente con las credenciales existentes.

### No veo los backups en la pantalla de configuración

Comprueba que la ruta introducida exista, que el servidor tenga permisos de escritura y que los archivos terminen en `.enc`.

### La restauración falla por clave o formato

Verifica que estás usando la misma clave Fernet con la que se generó el backup. Si el fichero está corrupto o fue alterado, la restauración se abortará.

### VeriFactu no responde o no se envía la factura

Revisa que el certificado `.p12`/`.pfx` esté correctamente subido y que la configuración de la empresa y el certificado sea válida antes de intentar el envío.

## Uso básico

AutoFactura está pensada para cubrir el flujo diario de un autónomo:

- Crear y gestionar contactos
- Emitir facturas y rectificativas
- Registrar gastos y adjuntar documentos
- Gestionar presupuestos y albaranes
- Registrar pagos y conciliarlos
- Generar PDFs y preparar la integración con VeriFactu

## Instalación

```bash
# 1. Crear entorno virtual
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Ejecutar la aplicación (Levanta el servidor WSGI Waitress)
python app.py
```

Abrir `http://127.0.0.1:5000` en el navegador.

### Consejos útiles para Waitress

- **Para apagar el servidor:** en la terminal abierta, pulsa `Ctrl + C`.
- **Ojo con los cambios en caliente:** Waitress está pensado para producción. Si modificas un archivo `.py`, los cambios no se verán reflejados hasta que cierres y vuelvas a arrancar el servidor.

## Arquitectura

```text
app.py                              ← Orquestador: inicializa Flask, SQLAlchemy y registra Blueprints
models.py                           ← Entidades ORM (Factura, Contacto, Gasto, Presupuesto, Albaran…)
config.py                           ← Configuración de entornos

blueprints/
  auth/views.py                     ← Controlador de autenticación (login / logout)
  invoices/views.py                 ← Controlador de facturas emitidas
  contacts/views.py                 ← Controlador de contactos (clientes y proveedores)
  expenses/views.py                 ← Controlador de gastos recibidos
  budgets/views.py                  ← Controlador de presupuestos
  delivery_notes/views.py           ← Controlador de albaranes
  payments/views.py                 ← Controlador de pagos y movimientos de caja
  products/views.py                 ← Controlador del catálogo de productos y servicios
  config/views.py                   ← Controlador de configuración de la empresa y VeriFactu

services/
  invoice_service.py                ← Lógica de negocio de facturas (cálculos, líneas, emisión)
  budget_service.py                 ← Lógica de negocio de presupuestos y conversión a factura
  delivery_note_service.py          ← Lógica de negocio de albaranes y conversión a factura
  verifactu_service.py              ← VerifactuOrchestrator: coordina hash, XML, firma y envío SOAP
  borme_service.py                  ← OpenMercantilService: enriquecimiento de contactos desde BORME

utils/
  tax_calculations.py               ← Cálculo de IVA, IGIC, IRPF
  pdf_generator.py                  ← Generación de PDFs con xhtml2pdf (facturas, presupuestos, albaranes)
  sequence_generators.py            ← Numeración secuencial de facturas, presupuestos y albaranes
  file_handlers.py                  ← Gestión de archivos adjuntos (gastos, documentos subidos)
  validators.py                     ← Validación de NIF/CIF y campos fiscales
  verifactu_hash.py                 ← VerifactuHashMotor: cálculo y encadenamiento SHA-256
  verifactu_xml.py                  ← VerifactuXmlBuilder: construcción del XML conforme a XSD oficial
  verifactu_signer.py               ← VerifactuSigner: firma XAdES-BES con certificado PKCS#12
  verifactu_client.py               ← VerifactuClient: transmisión SOAP sobre canal mTLS

templates/
  base.html                         ← Layout global con navegación
  facturas.html / factura_form.html
  gastos.html / gasto_form.html
  presupuestos.html / presupuesto_form.html
  albaranes.html / albaran_form.html
  contactos.html / contacto_form.html
  productos.html / producto_form.html
  pagos.html / pagos_form.html
  configuracion.html
  login.html
  pdf_templates/                    ← Plantillas HTML para generación de PDFs

static/
  logo2.svg                         ← Logotipo de la aplicación
  style.css                         ← Estilos globales
  uploads/                          ← Documentos subidos por el usuario

certs/
  firma_test_verifactu.pfx          ← Certificado de pruebas VeriFactu (.pfx / PKCS#12)
  Kit_Certificados_PRODUCCIÓN_DNIe/ ← Certificados de producción (DNIe activo/revocado)
  Set_Certificados_Pruebas_DNIE2/   ← Set completo de certificados de prueba (activo/caducado/revocado)

tests/
  conftest.py                       ← Fixtures compartidas (SQLite en memoria, mocks transversales)
  test_invoice_line_parsing.py
  test_invoices_routes.py
  test_verifactu_xml.py
  test_verifactu_integracion.py
  xsd/                              ← Esquemas XSD oficiales de la AEAT para validación
    SuministroLR.xsd
    SuministroInformacion.xsd
    RegFactuSistemaFacturacion.xsd
    RespuestaSuministro.xsd
    xmldsig-core-schema.xsd
```

**Flujo de una petición:**

1. El usuario realiza una petición web.
2. El Blueprint correspondiente la intercepta en su `views.py`.
3. El controlador consulta el Modelo o delega en servicios/utilidades (PDF, hash VeriFactu).
4. El sistema devuelve una plantilla Jinja2 renderizada o una respuesta JSON.

## Esquema de base de datos

Base de datos SQLite (`facturacion_db.sqlite`) gestionada con SQLAlchemy ORM.

| Entidad | Descripción |
|---|---|
| `contacto` | Clientes, proveedores o ambos. Incluye NIF, condiciones fiscales |
| `factura` | Facturas emitidas con hash encadenado, estado de pago y estado VeriFactu. |
| `factura_verifactu` | Registro satélite inmutable: XML firmado, hashes SHA-256, CSV de la AEAT y glosa de error. |
| `gasto` | Facturas recibidas de proveedores con adjunto y estado de pago. |
| `presupuesto` | Ofertas comerciales con fecha de validez y estado de aceptación. |
| `albaran` | Albaranes de entrega con conversión a factura y trazabilidad de origen. |
| `albaran_linea` | Líneas de concepto de un albarán (concepto, unidades, precio, impuesto, descuento). |
| `producto` | Catálogo de productos y servicios con precio base e impuesto predeterminado. |
| `pago` | Movimientos de caja vinculados a facturas o gastos con estado de conciliación. |
| `configuracion` | Ajustes globales de la empresa, serie de factura y credenciales del certificado VeriFactu. |
| `registro_eventos` | Log de auditoría inalterable requerido por la Ley Antifraude española. |

Campos VeriFactu destacados en `factura`: `hash_actual` (SHA-256, inmutable tras emisión), `hash_anterior`, `estado_verifactu` (`Pendiente` / `Enviado_Aceptado` / `Rechazado`), `csv_aeat`, `fecha_hora_alta`.

## Tests

Tests automatizados con `pytest` bajo filosofía de **tests de caracterización** — congelan el comportamiento actual del sistema como red de seguridad ante refactorizaciones.

| Fichero | Alcance y Aspectos Evaluados |
|---|---|
| `test_invoice_line_parsing.py` | Motor de cálculo fiscal: Tipos de IVA, retenciones de IRPF, validación de importes negativos y gestión de facturas rectificativas/abono. |
| `test_invoices_routes.py` | Rutas HTTP: Códigos de estado (200/302/400), flujos CRUD completos y generación/descarga de PDFs (`Content-Type: application/pdf`). |
| `test_verifactu_xml.py` | Árbol XML estructurado campo a campo: Namespaces obligatorios, constantes homologadas de Veri*Factu y desglose de bloques fiscales. |
| `test_verifactu_integracion.py` | Validación estructural contra el esquema XSD oficial de la AEAT (`lxml`) e integridad del encadenamiento (hash chain) con y sin registro génesis. |

### Cómo ejecutar las pruebas

Gracias a la configuración centralizada en `pytest.ini`, no es necesario pasar la ruta del esquema XSD manualmente en cada ejecución; el entorno lo gestiona de fondo automáticamente.

* **Ejecución rápida (detener en el primer fallo):**
  ```bash
  pytest tests/ -x

### Configuración global (`tests/conftest.py`)

- Base de datos SQLite efímera en memoria (`StaticPool`).
- Mocks transversales para QR y peticiones HTTP externas.
- Flag `--xsd` para acoplar el esquema XSD oficial en local o CI.

### Comandos

```bash
# Suite completa con detalle
pytest tests/ -v

# Ejecución paralela (todos los núcleos)
pytest tests/ -n auto

# Parar al primer fallo
pytest tests/ -x

# Validación XSD de VeriFactu
pytest tests/test_verifactu_integracion.py --xsd=tests/xsd/SuministroLR.xsd
```

### Test de rutas de facturas

```bash
pytest tests/test_invoice_line_parsing.py tests/test_invoices_routes.py -q
```

## Notas y limitaciones

- El proyecto usa SQLite de forma local, por lo que no está pensado como backend multiusuario complejo.
- Algunas funciones fiscales o de integración con VeriFactu requieren configuración adicional.
- El uso de este software es responsabilidad del usuario y debe revisarse con asesoramiento profesional cuando sea necesario.

## Distribución y licencia

AutoFactura es un proyecto de **libre distribución**. Puedes descargar, usar, modificar y adaptar el código de forma totalmente gratuita para tu gestión personal o el uso privado de tu negocio.

El proyecto está protegido bajo la licencia **Creative Commons Atribución-NoComercial-CompartirIgual 4.0 Internacional (CC BY-NC-SA 4.0)**.

- **Permitido:** uso privado, copia, modificación y distribución gratuita del código, siempre dando crédito al autor original.
- **Compartir Igual:** si distribuyes una versión modificada o un trabajo derivado, debe publicarse bajo esta misma licencia (CC BY-NC-SA 4.0).
- **Prohibido:** no está permitida la comercialización, venta o explotación lucrativa de esta aplicación ni de sus derivados por parte de terceros (por ejemplo, ofrecerla como servicio de pago o revenderla).
- **Aclaración:** usar el software internamente para gestionar la facturación de tu propia actividad como autónomo o negocio **sí está permitido** y no se considera explotación comercial del software en sí, ya que no estás vendiendo ni comercializando la aplicación, sino usándola como herramienta de gestión.

Puedes consultar el texto completo de la licencia en: [https://creativecommons.org/licenses/by-nc-sa/4.0/deed.es](https://creativecommons.org/licenses/by-nc-sa/4.0/deed.es)

## Stack técnico

- **Backend:** Python 3.10+, Flask, Flask-SQLAlchemy, Werkzeug, Jinja2
- **Base de datos:** SQLite (`facturacion_db.sqlite`) vía SQLAlchemy ORM
- **Servidor de producción:** Waitress (WSGI)
- **VeriFactu:** `lxml` (construcción y validación XSD), `signxml` (firma XAdES-BES), `cryptography` (PKCS#12), `pyHanko` (firma avanzada PDF), `qrcode` (QR AEAT), `hashlib` (SHA-256, stdlib)
- **Generación de documentos:** `xhtml2pdf`, `reportlab`, `pypdf`, `pillow`
- **HTTP / red:** `requests`
- **Tests:** `pytest`
- **Diseño:** responsive (CSS moderno), compatible con tabletas y smartphones

> **Nota de seguridad:** el proyecto no guarda contraseñas de certificados en la base de datos ni de ninguna otra manera por motivos de seguridad.

## Disclaimer / exención de responsabilidad

Este software es un **proyecto personal desarrollado mientras aprendo programación** y se proporciona "tal cual" (*as is*), sin garantías de ningún tipo, ya sean expresas o implícitas, incluyendo pero no limitado a garantías de comerciabilidad, idoneidad para un propósito particular o no infracción.

El autor **no se hace responsable** de:

- errores, fallos, pérdidas de datos o interrupciones del servicio derivados del uso de esta aplicación;
- el incumplimiento de obligaciones fiscales, tributarias o normativas (incluida la normativa VERI\*FACTU y cualquier otra exigida por la AEAT u otro organismo) que pueda derivarse del uso, mal uso o configuración incorrecta del software;
- sanciones, multas, perjuicios económicos o de cualquier otra índole que pueda sufrir el usuario o terceros como consecuencia del uso de este software;
- la exactitud, vigencia o adecuación de los cálculos fiscales (IVA, IGIC, IRPF) generados por la aplicación.

El uso de este software es **responsabilidad exclusiva del usuario**, quien debe verificar por su cuenta el cumplimiento de sus obligaciones legales y fiscales, y se recomienda contar con el asesoramiento de un profesional (gestor, asesor fiscal o similar) antes de utilizarlo en un entorno de producción real.

Al descargar, instalar o utilizar este software, el usuario acepta los términos de esta exención de responsabilidad.

