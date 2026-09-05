# RouteOps V0.3.0 — Internet Pilot

Versión enfocada exclusivamente en resolver la distancia Colombia ↔ España.

## Estado
- ✅ Web pública preparada para HTTPS.
- ✅ PostgreSQL en cloud mediante `DATABASE_URL`.
- ✅ SQLite como fallback para ejecutar localmente.
- ✅ Login administrador/repartidor.
- ✅ Jornadas.
- ✅ Paquetes CSV/XLSX.
- ✅ Asignación a repartidores.
- ✅ Rutas locales / Google opcional.
- ✅ QR/barcode.
- ✅ Tracking GPS.
- ✅ Entrega/incidencia.
- ✅ Evidencia fotográfica persistida en DB para el piloto.
- ✅ Liquidaciones.
- ✅ PWA.
- ✅ `render.yaml` para desplegar Web + PostgreSQL.
- ✅ Dockerfile como alternativa de hosting.

## No es todavía producción
V0.3.0 es un Internet Pilot de una sola organización. Se ha evitado añadir nuevas funciones logísticas para aislar y validar conectividad remota.

## Probar localmente en Windows
1. Ejecuta `install_and_run.bat`.
2. Abre `http://127.0.0.1:5000`.
3. Sin `DATABASE_URL`, se utiliza `routeops_v030.db` SQLite.

## Publicar en Internet
Lee `README_DEPLOY_RENDER.md`.

## Datos demo locales
Admin:
- `admin@routeops.local`
- `demo123`

Repartidor:
- `carlos`
- `1234`

En Render las contraseñas iniciales se establecen como secretos al crear el Blueprint.

## Seguridad del piloto
- cookies `HttpOnly` y `SameSite=Lax`;
- `Secure` activado en cloud;
- contraseña hasheada;
- credenciales fuera del repositorio;
- `ProxyFix` para HTTPS detrás del proxy de Render;
- fotos accesibles únicamente con sesión de la misma organización.

Pendiente antes de comercializar: CSRF completo, cambio obligatorio de contraseña, recuperación de cuenta, MFA opcional, auditoría, rate limiting y política de retención de GPS/evidencias.
