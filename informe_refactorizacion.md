# Informe de refactorización propuesta para AutoFactura

## 1. Objetivo del informe

Este documento recoge una propuesta concreta de refactorización, archivo por archivo, para llevar esta aplicación desde un estado funcional y bastante bien estructurado hacia una arquitectura más limpia, más mantenible y más preparada para compartir, evolucionar y probar.

La idea no es rehacerlo todo de golpe, sino hacerlo de forma progresiva, priorizando los puntos que más impactan en claridad, reutilización y facilidad de mantenimiento.

---

## 2. Qué se intenta mejorar

La refactorización debería perseguir estos objetivos:

- separar claramente la lógica de negocio de las rutas y vistas;
- reducir la duplicación de código;
- homogeneizar el manejo de formularios, validación y cálculos;
- dejar el acceso a datos más aislado y testeable;
- preparar la app para crecer sin que cada nuevo módulo requiera rehacer la arquitectura.

En términos prácticos, el punto más importante es pasar de una estructura “controlador + lógica mezclada” a una estructura más parecida a:

- vistas o blueprints: solo reciben peticiones y devuelven respuestas;
- servicios: contienen la lógica de negocio;
- modelos: representan el dominio;
- utilidades: contienen lógica técnica transversal;
- repositorios o adapters: encapsulan el acceso a datos cuando haga falta.

---

## 3. Propuesta de arquitectura objetivo

Una estructura más limpia para este proyecto podría quedar así:

- app/factory.py o app_factory.py: creación de la aplicación Flask;
- app/extensions.py: inicialización de SQLAlchemy, login, etc.;
- app/blueprints/ o blueprints/: los blueprints actuales, pero más delgados;
- services/: lógica de negocio por dominio;
- domain/ o core/: reglas de negocio, validaciones y objetos de dominio;
- repositories/: si se quiere aislar aún más el acceso a datos;
- interfaces/: abstracciones para servicios externos como VeriFactu, backups o almacenamiento.

---

## 4. Informe archivo por archivo

### [app.py](app.py)

#### Problema actual

Este archivo funciona como un “orquestador” general, pero aún concentra demasiadas responsabilidades:

- creación de la app Flask;
- carga de configuración;
- registro de blueprints;
- guardado de sesión y login obligatorio;
- inyección de estadísticas globales;
- definición de comandos CLI;
- arranque del servidor.

#### Qué refactorizar

- separar la creación de la app en una función factory;
- mover la configuración a módulos más explícitos;
- extraer la lógica de autenticación global y de estadísticas a módulos secundarios;
- dejar el arranque del servidor en un punto independiente.

#### Archivos nuevos recomendados

- [app_factory.py](app_factory.py) o [app/factory.py](app/factory.py)
- [app/extensions.py](app/extensions.py)
- [app/boot.py](app/boot.py)
- [app/cli.py](app/cli.py)
- [app/security.py](app/security.py)

---

### [config.py](config.py)

#### Problema actual

El archivo de configuración mezcla varias preocupaciones:

- configuración de entorno;
- inicialización de variables de entorno;
- generación automática de secretos;
- configuración de la base de datos;
- configuración de backups.

#### Qué refactorizar

- separar configuración general, configuración de desarrollo, configuración de testing y configuración de producción;
- mover la generación de variables de entorno a un módulo específico;
- dejar la lógica de secrets en un servicio o helper dedicado.

#### Archivos nuevos recomendados

- [config/settings.py](config/settings.py)
- [config/environment.py](config/environment.py)
- [config/secrets.py](config/secrets.py)

---

### [models.py](models.py)

#### Problema actual

Este es probablemente el archivo más grande y más central del proyecto. Tiene demasiadas entidades mezcladas en un solo lugar y esto dificulta:

- entender el dominio;
- mantener el esquema;
- aplicar cambios sin riesgo;
- separar responsabilidades claras.

#### Qué refactorizar

- dividir las entidades por dominio:
  - usuarios y autenticación;
  - empresa y configuración;
  - contactos;
  - facturas;
  - gastos;
  - presupuestos;
  - albaranes;
  - pagos;
  - auditoría y backups.

#### Archivos nuevos recomendados

- [models/user.py](models/user.py)
- [models/company.py](models/company.py)
- [models/contact.py](models/contact.py)
- [models/invoice.py](models/invoice.py)
- [models/expense.py](models/expense.py)
- [models/budget.py](models/budget.py)
- [models/delivery_note.py](models/delivery_note.py)
- [models/payment.py](models/payment.py)
- [models/audit.py](models/audit.py)
- [models/backup.py](models/backup.py)
- [models/base.py](models/base.py)

> En una segunda fase, se podría incluso mover este modelo a un paquete propio como [domain/](domain/), dejando [models.py](models.py) solo como un agregador de importaciones si se desea mantener compatibilidad.

---

### [blueprints/auth/views.py](blueprints/auth/views.py)

#### Problema actual

La vista mezcla:

- lógica de autenticación;
- validación de usuario;
- generación de hash;
- control de estado de la base de datos;
- redirección y mensajes flash.

#### Qué refactorizar

- mover la lógica de login y creación del primer usuario a un servicio de autenticación;
- separar la validación del formulario del flujo de negocio;
- hacer que la vista solo coordine peticiones y respuestas.

#### Archivos nuevos recomendados

- [services/auth_service.py](services/auth_service.py)
- [services/auth_validator.py](services/auth_validator.py)

---

### [blueprints/invoices/views.py](blueprints/invoices/views.py)

#### Problema actual

Es uno de los controladores más cargados. Tiene lógica de:

- listado y filtrado;
- creación/edición de facturas;
- cálculo de totales;
- reconstrucción de líneas de formulario;
- validación; 
- envío a VeriFactu;
- generación de respuestas y flashes.

#### Qué refactorizar

- reducir este archivo a una capa de entrada HTTP;
- mover la lógica de negocio a un servicio específico de facturas;
- extraer el manejo de formularios a un servicio o helper;
- separar las operaciones de crear, actualizar, enviar y exportar.

#### Archivos nuevos recomendados

- [services/invoice_management_service.py](services/invoice_management_service.py)
- [services/invoice_form_service.py](services/invoice_form_service.py)
- [services/invoice_pdf_service.py](services/invoice_pdf_service.py)
- [services/invoice_submission_service.py](services/invoice_submission_service.py)
- [services/invoice_calculation_service.py](services/invoice_calculation_service.py)

---

### [services/invoice_service.py](services/invoice_service.py)

#### Problema actual

Aunque ya existe una separación inicial, todavía mezcla varias responsabilidades:

- parseo de líneas;
- cálculo de impuestos;
- generación de QR;
- reconstrucción de las líneas para la UI.

#### Qué refactorizar

- dividirlo en servicios más pequeños y coherentes;
- mantener una clase para la factura, pero con responsabilidades más concretas.

#### Archivos nuevos recomendados

- [services/invoice_line_service.py](services/invoice_line_service.py)
- [services/invoice_totals_service.py](services/invoice_totals_service.py)
- [services/invoice_qr_service.py](services/invoice_qr_service.py)
- [services/invoice_form_mapper.py](services/invoice_form_mapper.py)

---

### [blueprints/budgets/views.py](blueprints/budgets/views.py)

#### Problema actual

El blueprint tiene un grado de carga moderado. Aunque ya se ha movido algo de lógica a [services/budget_service.py](services/budget_service.py), aún queda cierta mezcla de:

- renderizado y redirecciones;
- previsualización;
- conversión de presupuesto a factura;
- creación de objetos simulados;
- generación de PDF.

#### Qué refactorizar

- dejar la vista casi solo con flujo HTTP;
- mover la conversión a factura a un servicio específico;
- separar la creación de previsualización del render de PDF.

#### Archivos nuevos recomendados

- [services/budget_conversion_service.py](services/budget_conversion_service.py)
- [services/budget_pdf_service.py](services/budget_pdf_service.py)
- [services/budget_preview_service.py](services/budget_preview_service.py)

---

### [services/budget_service.py](services/budget_service.py)

#### Problema actual

Este servicio ya está mejorado, pero todavía tiene una responsabilidad amplia:

- parsear formulario;
- validar presupuesto;
- crear/actualizar presupuesto;
- poblar líneas;
- persistir.

#### Qué refactorizar

- separar el parseo del formulario del guardado;
- crear una clase o módulo para cálculos del presupuesto;
- mover el llenado de líneas a su propio helper.

#### Archivos nuevos recomendados

- [services/budget_parser_service.py](services/budget_parser_service.py)
- [services/budget_calculation_service.py](services/budget_calculation_service.py)
- [services/budget_line_builder.py](services/budget_line_builder.py)

---

### [blueprints/contacts/views.py](blueprints/contacts/views.py)

#### Problema actual

Este módulo probablemente mezcla render, validación, carga de datos y operaciones de negocio.

#### Qué refactorizar

- mover la lógica de creación, edición, búsqueda y normalización al servicio de contactos;
- hacer que la vista sea solo una capa de presentación.

#### Archivos nuevos recomendados

- [services/contact_service.py](services/contact_service.py)
- [services/contact_validator.py](services/contact_validator.py)

---

### [blueprints/expenses/views.py](blueprints/expenses/views.py)

#### Problema actual

La gestión de gastos suele involucrar:

- validación de formularios;
- manejo de archivos adjuntos;
- cálculos del gasto;
- persistencia.

#### Qué refactorizar

- separar la lógica del formulario y del adjunto del flujo HTTP.

#### Archivos nuevos recomendados

- [services/expense_service.py](services/expense_service.py)
- [services/expense_file_service.py](services/expense_file_service.py)

---

### [blueprints/payments/views.py](blueprints/payments/views.py)

#### Problema actual

El registro de pagos y conciliaciones suele ser una zona muy sensible y con reglas de negocio importantes.

#### Qué refactorizar

- mover los cálculos de conciliación y el cierre de estado a un servicio dedicado;
- aislar la lógica que decide si una factura pasa a “cobrada” o “pagada”.

#### Archivos nuevos recomendados

- [services/payment_service.py](services/payment_service.py)
- [services/payment_reconciliation_service.py](services/payment_reconciliation_service.py)

---

### [blueprints/products/views.py](blueprints/products/views.py)

#### Problema actual

Seguramente mezcla lógica de listado y creación con la lógica de respuestas JSON y plantillas.

#### Qué refactorizar

- separar el acceso a productos del controlador.

#### Archivos nuevos recomendados

- [services/product_service.py](services/product_service.py)

---

### [blueprints/delivery_notes/views.py](blueprints/delivery_notes/views.py)

#### Problema actual

El módulo de albaranes está muy ligado a la lógica de facturación y probablemente debería quedarse más cercano a un caso de uso de negocio independiente.

#### Qué refactorizar

- mover la lógica de conversión a factura a un servicio de albaranes;
- separar la creación y edición del flujo web.

#### Archivos nuevos recomendados

- [services/delivery_note_service.py](services/delivery_note_service.py) — si no existe ya como capa sólida;
- [services/delivery_note_conversion_service.py](services/delivery_note_conversion_service.py)

---

### [blueprints/config/views.py](blueprints/config/views.py)

#### Problema actual

Es un controlador muy grande y hace muchas cosas distintas:

- configuración general;
- gestión de métodos de pago;
- gestión de certificados;
- gestión de backups;
- restauración;
- validación de rutas.

#### Qué refactorizar

- dividir en varios servicios claros;
- dejar la vista dedicada solo al flujo HTTP;
- mover la lógica de backup y certificado a servicios independientes.

#### Archivos nuevos recomendados

- [services/company_config_service.py](services/company_config_service.py)
- [services/certificate_service.py](services/certificate_service.py)
- [services/backup_config_service.py](services/backup_config_service.py) — ya existe, pero conviene reforzarlo;
- [services/backup_restore_service.py](services/backup_restore_service.py)

---

### [services/backup_orchestrator_service.py](services/backup_orchestrator_service.py)

#### Problema actual

Se ve bastante bien, pero todavía depende de demasiados detalles concretos y puede beneficiarse de una separación más clara entre:

- orquestación;
- cifrado;
- almacenamiento;
- restauración.

#### Qué refactorizar

- extraer las interfaces de almacenamiento y cifrado;
- separar la ejecución del backup del control de errores y del estado del sistema.

#### Archivos nuevos recomendados

- [services/backup/interfaces.py](services/backup/interfaces.py)
- [services/backup/storage_adapter.py](services/backup/storage_adapter.py)
- [services/backup/backup_runner.py](services/backup/backup_runner.py)

---

### [services/restore_service.py](services/restore_service.py)

#### Problema actual

La restauración es una parte crítica y ya tiene buena separación, pero aún puede mejorar en:

- validación del archivo;
- gestión de errores;
- selección del formato de backup;
- transacciones de restauración.

#### Qué refactorizar

- separar la validación, el desencriptado y la aplicación del respaldo en servicios distintos.

#### Archivos nuevos recomendados

- [services/restore_validator.py](services/restore_validator.py)
- [services/restore_executor.py](services/restore_executor.py)

---

### [utils/tax_calculations.py](utils/tax_calculations.py)

#### Problema actual

Este módulo tiene lógica fiscal muy importante y, además, existe una duplicidad con [utils/calculations.py](utils/calculations.py).

#### Qué refactorizar

- unificar todo el cálculo fiscal en un único módulo o servicio;
- convertir las reglas en algo más configurable y menos “quemado en código”;
- separar los cálculos de impuestos del resto de utilidades.

#### Archivos nuevos recomendados

- [domain/tax_rules.py](domain/tax_rules.py)
- [services/tax_calculation_service.py](services/tax_calculation_service.py)

---

### [utils/calculations.py](utils/calculations.py)

#### Problema actual

Si existe, debería eliminarse o convertirse en un adaptador de compatibilidad hacia el nuevo módulo central de impuestos.

#### Qué refactorizar

- eliminar el duplicado;
- mantener solo una implementación fuente de verdad.

#### Archivos nuevos recomendados

- no haría falta crear uno nuevo si se integra en [domain/tax_rules.py](domain/tax_rules.py).

---

### [utils/pdf_generator.py](utils/pdf_generator.py)

#### Problema actual

El generador de PDFs está bien como herramienta, pero la lógica responsable de preparar el contexto y la plantilla está demasiado dispersa.

#### Qué refactorizar

- centralizar la generación de documentos en un servicio de rendering;
- separar la construcción del contexto del render final.

#### Archivos nuevos recomendados

- [services/document_render_service.py](services/document_render_service.py)
- [services/pdf_context_builder.py](services/pdf_context_builder.py)

---

### [utils/validators.py](utils/validators.py)

#### Problema actual

La validación está bien aislada, pero el modelo podría mejorar si se separa por entidad o por uso.

#### Qué refactorizar

- dividir validadores de empresa, contacto, factura, gasto, presupuesto y certificado;
- dejar menos lógica genérica mezclada.

#### Archivos nuevos recomendados

- [validators/company_validator.py](validators/company_validator.py)
- [validators/contact_validator.py](validators/contact_validator.py)
- [validators/invoice_validator.py](validators/invoice_validator.py)
- [validators/expense_validator.py](validators/expense_validator.py)
- [validators/budget_validator.py](validators/budget_validator.py)

---

### [utils/sequence_generators.py](utils/sequence_generators.py)

#### Problema actual

Es una utilidad útil, pero probablemente debería estar más ligada a la configuración de la empresa que a una lógica “cruda” de números.

#### Qué refactorizar

- separar la regla de numeración de la generación de números;
- hacer el mecanismo más configurable para series, prefijos, etc.

#### Archivos nuevos recomendados

- [services/numbering_service.py](services/numbering_service.py)
- [services/sequence_policy.py](services/sequence_policy.py)

---

### [utils/file_handlers.py](utils/file_handlers.py)

#### Problema actual

Manejo de archivos y subida de documentos puede crecer con bastante rapidez.

#### Qué refactorizar

- separar la validación del tipo de archivo del almacenamiento real;
- dejar un único punto para subir y organizar archivos.

#### Archivos nuevos recomendados

- [services/file_upload_service.py](services/file_upload_service.py)

---

## 5. Archivos nuevos que conviene crear en conjunto

Si se hace una refactorización seria, estos serían los módulos nuevos más útiles para dejar el proyecto más ordenado:

- [app_factory.py](app_factory.py)
- [app/extensions.py](app/extensions.py)
- [app/boot.py](app/boot.py)
- [app/cli.py](app/cli.py)
- [config/settings.py](config/settings.py)
- [config/environment.py](config/environment.py)
- [config/secrets.py](config/secrets.py)
- [models/base.py](models/base.py)
- [models/user.py](models/user.py)
- [models/company.py](models/company.py)
- [models/contact.py](models/contact.py)
- [models/invoice.py](models/invoice.py)
- [models/expense.py](models/expense.py)
- [models/budget.py](models/budget.py)
- [models/delivery_note.py](models/delivery_note.py)
- [models/payment.py](models/payment.py)
- [models/audit.py](models/audit.py)
- [models/backup.py](models/backup.py)
- [services/auth_service.py](services/auth_service.py)
- [services/auth_validator.py](services/auth_validator.py)
- [services/invoice_management_service.py](services/invoice_management_service.py)
- [services/invoice_form_service.py](services/invoice_form_service.py)
- [services/invoice_pdf_service.py](services/invoice_pdf_service.py)
- [services/invoice_submission_service.py](services/invoice_submission_service.py)
- [services/invoice_calculation_service.py](services/invoice_calculation_service.py)
- [services/invoice_line_service.py](services/invoice_line_service.py)
- [services/invoice_totals_service.py](services/invoice_totals_service.py)
- [services/invoice_qr_service.py](services/invoice_qr_service.py)
- [services/invoice_form_mapper.py](services/invoice_form_mapper.py)
- [services/budget_conversion_service.py](services/budget_conversion_service.py)
- [services/budget_pdf_service.py](services/budget_pdf_service.py)
- [services/budget_preview_service.py](services/budget_preview_service.py)
- [services/budget_parser_service.py](services/budget_parser_service.py)
- [services/budget_calculation_service.py](services/budget_calculation_service.py)
- [services/budget_line_builder.py](services/budget_line_builder.py)
- [services/contact_service.py](services/contact_service.py)
- [services/contact_validator.py](services/contact_validator.py)
- [services/expense_service.py](services/expense_service.py)
- [services/expense_file_service.py](services/expense_file_service.py)
- [services/payment_service.py](services/payment_service.py)
- [services/payment_reconciliation_service.py](services/payment_reconciliation_service.py)
- [services/product_service.py](services/product_service.py)
- [services/company_config_service.py](services/company_config_service.py)
- [services/certificate_service.py](services/certificate_service.py)
- [services/backup_restore_service.py](services/backup_restore_service.py)
- [services/document_render_service.py](services/document_render_service.py)
- [services/pdf_context_builder.py](services/pdf_context_builder.py)
- [services/file_upload_service.py](services/file_upload_service.py)
- [services/numbering_service.py](services/numbering_service.py)
- [services/sequence_policy.py](services/sequence_policy.py)
- [domain/tax_rules.py](domain/tax_rules.py)
- [validators/company_validator.py](validators/company_validator.py)
- [validators/contact_validator.py](validators/contact_validator.py)
- [validators/invoice_validator.py](validators/invoice_validator.py)
- [validators/expense_validator.py](validators/expense_validator.py)
- [validators/budget_validator.py](validators/budget_validator.py)

---

## 6. Prioridad recomendada

### Fase 1: base de arquitectura

- [app.py](app.py)
- [config.py](config.py)
- [models.py](models.py)

### Fase 2: separación de negocio por módulo

- [blueprints/invoices/views.py](blueprints/invoices/views.py)
- [blueprints/budgets/views.py](blueprints/budgets/views.py)
- [blueprints/config/views.py](blueprints/config/views.py)
- [blueprints/auth/views.py](blueprints/auth/views.py)

### Fase 3: limpieza transversal

- [utils/tax_calculations.py](utils/tax_calculations.py)
- [utils/pdf_generator.py](utils/pdf_generator.py)
- [utils/validators.py](utils/validators.py)
- [utils/sequence_generators.py](utils/sequence_generators.py)

### Fase 4: hardening y preparación para compartir

- servicios de backup y restauración;
- servicios de autenticación y seguridad;
- separación de interfaces externas;
- mejoras de testing y documentación.

---

## 7. Recomendación final

Si el objetivo es que este proyecto sea más profesional, más fácil de mantener y más sólido para cederlo, la refactorización debería hacerse en este orden:

1. limpiar la entrada principal de la app;
2. separar la lógica de negocio de las vistas;
3. dividir los modelos por dominio;
4. unificar impuestos, numeración y PDF;
5. dejar los módulos externos (VeriFactu, backup, almacenamiento) detrás de interfaces claras.

Con ese enfoque, el proyecto ganará mucho en claridad sin perder su funcionalidad actual.
