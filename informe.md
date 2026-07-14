# Informe de Análisis: Arquitectura y SOLID (AutoFactura-Python)

Este informe presenta un análisis técnico detallado de la arquitectura de software y el cumplimiento de los principios de diseño **SOLID** en la aplicación web de facturación y control de gastos para autónomos.

---

## 1. Análisis de la Arquitectura del Proyecto

El sistema está estructurado bajo un patrón de diseño **MVC (Modelo-Vista-Controlador) modular**, implementado en **Flask** con un mapeo relacional de datos a través de **SQLAlchemy ORM**.

### 1.1 Diagrama de Capas del Sistema

A continuación, se detalla el flujo de información y la comunicación entre los componentes principales del sistema:

┌───────────────────────────────────────────────────────────────┐
│                    Usuario (Navegador Web)                    │
└───────────────────────────────┬───────────────────────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │   Core Flask (app.py)   │
                    └────────────┬────────────┘
                                 │
                                 ▼
                ┌─────────────────────────────────┐
                │  Controladores (blueprints/)     │
                └────────────────┬─────────────────┘
                                 │
         ┌──────────────┬────────┼────────┬──────────────┐
         ▼              ▼        ▼        ▼              ▼
   ┌─────────┐   ┌───────────┐  ...  ┌──────────┐  ┌──────────────┐
   │  auth   │   │ invoices  │       │ budgets  │  │ Otros        │
   │ (Auten- │   │ (Facturas)│       │(Presup.) │  │ (contacts,   │
   │  ticac.)│   │           │       │          │  │ products,    │
   └─────────┘   └─────┬─────┘       └────┬─────┘  │ payments,    │
                       │                  │        │ config)      │
                       ▼                  │        └──────────────┘
              ┌────────────────────┐      │
              │ Servicios          │      │
              │ (services/)        │      │
              │                    │      │
              │ VerifactuOrch.     │      │
              └─────────┬──────────┘      │
                        │                 │
                        ▼                 ▼
        ┌─────────────────────────────────────────┐
        │       Utilidades (utils/)               │
        ├─────────────────────────────────────────┤
        │ • tax_calculations.py                   │
        │ • sequence_generators.py                │
        │ • pdf_generator.py                      │
        │ • validators.py                         │
        │ • verifactu_hash.py                     │
        │ • verifactu_xml.py                      │
        │ • verifactu_signer.py                   │
        │ • verifactu_client.py                   │
        └─────────────────────────────────────────┘

   ┌─────────────────────────┐       ┌─────────────────────────┐
   │  Modelos ORM (models.py)│◄──────│  Blueprints / Servicios │
   └────────────┬────────────┘       └─────────────────────────┘
                │
                ▼
   ┌─────────────────────────────────┐
   │ Base de Datos                   │
   │ (facturacion_db.sqlite)         │
   └─────────────────────────────────┘

### 1.2 Responsabilidades por Capa

1. **Orquestación Central (`app.py`):** Inicializa la aplicación Flask, carga la configuración de `config.py`, vincula SQLAlchemy y registra cada Blueprint.
2. **Modelo de Dominio (`models.py`):** Define el esquema de la base de datos `facturacion_db.sqlite`. Maneja relaciones complejas (como la autoreferencial de facturas rectificativas y las satélites como `FacturaVerifactu`).
3. **Controladores (`blueprints/`):** Aísla la lógica de enrutamiento web por dominio. Se encargan de procesar las peticiones HTTP y devolver las plantillas Jinja2 o respuestas JSON.
4. **Capa de Servicios (`services/`):** Contiene lógica de negocio de alta complejidad. Por ejemplo, `VerifactuOrchestrator` coordina el ciclo completo de reporte fiscal sin acoplarse al protocolo HTTP de Flask.
5. **Capa de Utilidades (`utils/`):** Funciones puras e independientes de infraestructura para firma digital, formateo XML, cálculo de hashes criptográficos, validación de formularios y generación de PDFs.

---

## 2. Evaluación de los Principios SOLID

El codebase muestra un esfuerzo consciente de modularización, aunque presenta áreas de mejora significativas en el acoplamiento y la consistencia.

### 2.1 Single Responsibility Principle (SRP) - Principio de Responsabilidad Única
> *Un módulo o clase debe tener una sola razón para cambiar.*

* **Puntos Fuertes (Cumplimiento):**
  * **Módulo Veri\*Factu:** El flujo de envío fiscal se dividió de manera ejemplar en subcomponentes con responsabilidades únicas:
    * [verifactu_hash.py](file:///c:/Users/Txus/Programacion%20VisualStudio/Entorno/Software%20Facturacion%20Autonomos/utils/verifactu_hash.py) calcula hashes criptográficos normalizados.
    * [verifactu_xml.py](file:///c:/Users/Txus/Programacion%20VisualStudio/Entorno/Software%20Facturacion%20Autonomos/utils/verifactu_xml.py) construye el documento conforme al XSD de la AEAT.
    * [verifactu_signer.py](file:///c:/Users/Txus/Programacion%20VisualStudio/Entorno/Software%20Facturacion%20Autonomos/utils/verifactu_signer.py) gestiona la firma XAdES-BES.
    * [verifactu_client.py](file:///c:/Users/Txus/Programacion%20VisualStudio/Entorno/Software%20Facturacion%20Autonomos/utils/verifactu_client.py) abre la conexión segura mTLS y gestiona el envío.
  * **Validadores:** [validators.py](file:///c:/Users/Txus/Programacion%20VisualStudio/Entorno/Software%20Facturacion%20Autonomos/utils/validators.py) separa las reglas de validación de los formularios de las vistas de Flask.
* **Puntos Débiles (Violaciones):**
  * **Vistas Sobrecargadas:** En [budgets/views.py](file:///c:/Users/Txus/Programacion%20VisualStudio/Entorno/Software%20Facturacion%20Autonomos/blueprints/budgets/views.py), el controlador se encarga de:
    1. Atender solicitudes web.
    2. Construir filas HTML específicas para el PDF (`_build_lineas_html_for_pdf`).
    3. Analizar datos del formulario (`parse_presupuesto_lineas`).
    4. Generar bytes PDF con `xhtml2pdf`.
  * **Sugerencia de Refactorización:** Estas responsabilidades deberían extraerse a un servicio de presupuestos (`BudgetService`) y una utilidad unificada de generación de PDF.

### 2.2 Open/Closed Principle (OCP) - Principio de Abierto/Cerrado
> *Las entidades de software deben estar abiertas para la extensión, pero cerradas para la modificación.*

* **Puntos Fuertes (Cumplimiento):**
  * La clase `BaseValidator` y sus herederas (`EmpresaValidator`, `ContactoValidator`) demuestran una extensión limpia. Si se añade una nueva entidad al sistema, basta con crear una nueva subclase sin modificar el código base de validación.
* **Puntos Débiles (Violaciones):**
  * **Cálculos de Totales y Tasas:** En [tax_calculations.py](file:///c:/Users/Txus/Programacion%20VisualStudio/Entorno/Software%20Facturacion%20Autonomos/utils/tax_calculations.py) y [calculations.py](file:///c:/Users/Txus/Programacion%20VisualStudio/Entorno/Software%20Facturacion%20Autonomos/utils/calculations.py), las funciones operan con valores quemados (como el recargo de equivalencia del `5.20%`). Si cambia la normativa tributaria o se incorporan nuevos recargos/impuestos especiales, el código de las funciones debe modificarse manualmente en lugar de extenderse mediante configuración o polimorfismo.

### 2.3 Liskov Substitution Principle (LSP) - Principio de Sustitución de Liskov
> *Los objetos de una clase heredera deben poder reemplazar a los objetos de la clase base sin alterar el comportamiento correcto del programa.*

* **Cumplimiento:**
  * En Python, al ser un lenguaje de tipado dinámico ("duck typing"), el LSP se manifiesta principalmente en la consistencia de las interfaces. Los modelos de base de datos heredan correctamente de `db.Model` y `ModelInitMixin` sin romper el contrato implícito de SQLAlchemy.
  * Los validadores derivados de `BaseValidator` implementan el método `validar` de manera que conservan la firma y el tipo de retorno esperado (listas de errores), permitiendo un uso seguro.

### 2.4 Interface Segregation Principle (ISP) - Principio de Segregación de Interfaces
> *Los clientes no deberían verse obligados a depender de interfaces que no utilizan.*

* **Cumplimiento:**
  * Dado que Python no posee interfaces nativas (abstractas) de forma estricta (salvo por el módulo `abc`), este principio se cumple a través de interfaces de clase cohesivas.
  * Los módulos de utilidades como `VerifactuSigner` o `VerifactuHashMotor` ofrecen interfaces estrechas y bien orientadas a su dominio específico (métodos estáticos altamente enfocados), evitando que los clientes tengan que arrastrar dependencias innecesarias de métodos de otras funcionalidades no relacionadas.

### 2.5 Dependency Inversion Principle (DIP) - Principio de Inversión de Dependencia
> *Los módulos de alto nivel no deben depender de módulos de bajo nivel. Ambos deben depender de abstracciones.*

* **Puntos Débiles (Violaciones):**
  * **Acoplamiento Directo:** Los controladores y servicios importan directamente clases e implementaciones concretas en lugar de interfaces. Por ejemplo, `VerifactuOrchestrator` está directamente acoplado a la base de datos de SQLAlchemy (`models.py`) y a implementaciones de bajo nivel como `VerifactuClient`.
  * **Inyectabilidad:** Para realizar pruebas unitarias, se depende en gran medida de `unittest.mock` para parchear las importaciones dinámicas, en lugar de poder inyectar dependencias configuradas (por ejemplo, inyectar un `XmlBuilderInterface` o un `HttpClientInterface`).
  * **Sugerencia de Refactorización:** Implementar un contenedor simple de Inyección de Dependencias o pasar las dependencias requeridas (como el motor de firma o el cliente AEAT) en el constructor de `VerifactuOrchestrator`.

---

## 3. Hallazgos Adicionales y Deuda Técnica (Higiene del Código)

Durante el análisis profundo del código, se identificaron varios problemas críticos de arquitectura, mantenibilidad y seguridad:

### 3.1 Duplicidad de Código (Violación de DRY)
Existe una duplicación masiva entre dos archivos de utilidades:
* [calculations.py](file:///c:/Users/Txus/Programacion%20VisualStudio/Entorno/Software%20Facturacion%20Autonomos/utils/calculations.py)
* [tax_calculations.py](file:///c:/Users/Txus/Programacion%20VisualStudio/Entorno/Software%20Facturacion%20Autonomos/utils/tax_calculations.py) e [sequence_generators.py](file:///c:/Users/Txus/Programacion%20VisualStudio/Entorno/Software%20Facturacion%20Autonomos/utils/sequence_generators.py)

Las funciones `calculate_totals` y `parse_impuesto_porcentaje` están duplicadas palabra por palabra. Además:
* Las facturas ordinarias y rectificativas consumen la lógica moderna de `tax_calculations.py` y `sequence_generators.py`.
* Los presupuestos ([budgets/views.py:L13](file:///c:/Users/Txus/Programacion%20VisualStudio/Entorno/Software%20Facturacion%20Autonomos/blueprints/budgets/views.py#L13)) todavía importan y consumen el archivo obsoleto `calculations.py`.

### 3.2 Inconsistencia en la Generación de PDFs
El proyecto implementa dos mecanismos totalmente distintos para generar archivos PDF:
1. **Facturas (`utils/pdf_generator.py`):** Genera el PDF mediante manipulación manual de bytes a bajo nivel (`%PDF-1.4`, objetos de flujos de texto `BT ... ET` comprimidos con `zlib`). Esto minimiza dependencias externas pero es propenso a errores y extremadamente complejo de mantener.
2. **Presupuestos (`budgets/views.py`):** Utiliza la librería de renderizado HTML-a-PDF `xhtml2pdf` a partir de una plantilla de Jinja2 (`pdf_templates/budget_pdf.html`). Es mucho más amigable, pero introduce fragmentación técnica y dependencias pesadas no alineadas.

> [!WARNING]
> Esta falta de unificación incrementa el coste de mantenimiento, ya que cualquier cambio en la identidad corporativa (logo, tipografía, colores) requiere modificar tanto el renderizador de bytes manual como las plantillas HTML de Jinja2.

### 3.3 Dependencias No Registradas en `requirements.txt`
El archivo [requirements.txt](file:///c:/Users/Txus/Programacion%20VisualStudio/Entorno/Software%20Facturacion%20Autonomos/requirements.txt) declara únicamente:
* `Flask`
* `Flask-WTF`
* `Flask-SQLAlchemy`
* `Werkzeug`

Sin embargo, el sistema importa y hace uso activo de las siguientes librerías de terceros adicionales:
1. `lxml` (utilizada en `verifactu_signer.py` para parseo y manipulación XML)
2. `signxml` (utilizada en `verifactu_signer.py` para firmas XAdES)
3. `cryptography` (utilizada en `verifactu_client.py` y `verifactu_signer.py` para manipulación de certificados PKCS#12)
4. `requests` (utilizada en `verifactu_client.py` para enviar peticiones a la AEAT)
5. `qrcode` (utilizada en `blueprints/invoices/views.py` para generar códigos QR obligatorios en las facturas emitidas)
6. `xhtml2pdf` (utilizada en `blueprints/budgets/views.py` para PDF de presupuestos)

> [!IMPORTANT]
> Un entorno limpio no podrá ejecutar la aplicación utilizando únicamente `pip install -r requirements.txt`, provocando errores inmediatos del tipo `ModuleNotFoundError`.

### 3.4 Seguridad
* **Credenciales por Defecto:** La función `init_db` en `models.py` inserta de manera automática el usuario `admin` con la contraseña en texto plano `'admin'` si no existe.
* **Cifrado de Certificados:** La configuración permite almacenar rutas e información sensible del certificado Veri\*Factu. Es fundamental asegurar que la clave del certificado p12 no se almacene en texto plano en la base de datos en entornos de producción.

---

## 4. Plan de Acción Recomendado

Para mitigar la deuda técnica y alinear el proyecto con un diseño robusto y SOLID, se sugeriría llevar a cabo la siguiente hoja de ruta:

| Fase | Tarea | Principio Relacionado | Complejidad |
|---|---|---|---|
| **Fase 1** | **Limpieza de DRY:** Modificar `blueprints/budgets/views.py` para que importe desde `utils.tax_calculations` y `utils.sequence_generators`. Eliminar el archivo redundante `utils/calculations.py`. | **SRP / DRY** | Baja |
| **Fase 2** | **Actualización de Dependencias:** Incorporar en `requirements.txt` las librerías `lxml`, `signxml`, `cryptography`, `requests`, `qrcode` y `xhtml2pdf` con sus respectivas versiones. | **Higiene Operativa** | Muy Baja |
| **Fase 3** | **Unificación de PDFs:** Encapsular la lógica de generación de presupuestos PDF en `utils/pdf_generator.py` o crear un servicio unificado de renderizado de documentos que maneje tanto facturas como presupuestos mediante plantillas HTML (preferiblemente unificando el motor a `xhtml2pdf` para facilitar el diseño, o delegando a un motor de bajo nivel robusto). | **SRP / DRY** | Media |
| **Fase 4** | **Inversión de Dependencias (DIP):** Modificar `VerifactuOrchestrator` para recibir mediante su constructor (o como parámetros) el cliente de red, el generador XML y el firmador. Esto facilitará enormemente las pruebas unitarias y de integración sin necesidad de parchear métodos. | **DIP** | Media |
