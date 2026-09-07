# Deploy — RouteOps V0.3.1.4 Intelligent OCR Pipeline

## Recomendado para tu instalación actual

Usa el ZIP `PATCH_ONLY`.

1. Descomprímelo.
2. Copia **el contenido interno** sobre tu carpeta local `RouteOps`.
3. Acepta `Reemplazar archivos en el destino`.
4. Abre GitHub Desktop.
5. Confirma que aparecen archivos modificados, especialmente:
   - `app.py`
   - `db_layer.py`
   - `intake_engine.py`
   - `templates/driver_intake.html`
   - `static/smart_label_scanner.js`
   - `static/style.css`
   - `static/sw.js`
6. Commit: `RouteOps V0.3.1.4 Intelligent OCR Pipeline`.
7. `Push origin`.
8. Espera el redeploy automático de Render.

## Después del deploy

Cierra completamente RouteOps/PWA en el móvil y vuelve a abrirlo para recibir el Service Worker V0.3.1.4.

No borres PostgreSQL y no crees otro servicio Render.

## Variables Render

Obligatoria para OCR:

`GOOGLE_VISION_API_KEY=...`

Recomendadas:

`AUTO_OPTIMIZE_INTAKE=1`

`INTAKE_OCR_WORKERS=2`

`OCR_MULTI_PASS=1`

`OCR_TARGET_LONG_SIDE=2200`

No publiques ninguna API key en GitHub.
