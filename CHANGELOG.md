# Changelog RouteOps

## V0.3 — Cloud-ready + Smart Dispatch
- Modelo de clasificación previa al ruteo.
- Nuevos atributos: país/origen, empresa, zona, tipo, peso, prioridad, características.
- Tabla `dispatch_rules`.
- Tabla `dispatch_history`.
- Motor de reglas con prioridad.
- Explicación de cada asignación automática.
- Excepciones sin regla.
- Clasificación conservadora o sobrescritura total.
- Asignación manual auditada.
- Sugerencias de reglas a partir de patrones manuales consistentes.
- CSV V0.3 de prueba.
- Base separada `routeops_v03.db`.
- Directorio de datos configurable para disco persistente cloud.
- Docker/Gunicorn para pilot cloud single-instance.

## V0.2.1 — LAN Pilot
- Acceso PC + móviles en Wi-Fi.
- HTTPS LAN y certificado local.
- QR de incorporación.

## V0.2
- Jornadas.
- QR/barcode.
- Tracking.
- Optimización local/Google Road.
- Liquidaciones por jornada.
