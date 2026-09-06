# Deploy — RouteOps V0.3.1.2 Embedded Vision Engine

Se actualiza el mismo repositorio y el mismo servicio Render. No crees otra URL ni otra base de datos.

## 1. GitHub

Descomprime el ZIP y entra dentro de `RouteOps_V0.3.1.2_Embedded_Vision_Engine`.

Copia **el contenido interno** a la raíz de tu repositorio RouteOps, reemplazando los archivos existentes.

Debes ver directamente en la raíz:

- `app.py`
- `db_layer.py`
- `intake_engine.py`
- `templates/`
- `static/`
- `render.yaml`
- `requirements.txt`

No debe quedar una carpeta V0.3.1.2 conteniendo otra copia del proyecto.

## 2. Archivos nuevos importantes

Confirma en GitHub:

- `static/smart_vision.js`
- `static/smart_label_scanner.js`

Y que `templates/driver_intake.html` ya NO contenga una URL hacia `docs.opencv.org/.../opencv.js`.

## 3. Render

Conserva:

- `DATABASE_URL`
- `SECRET_KEY`
- `GOOGLE_VISION_API_KEY`
- `AUTO_OPTIMIZE_INTAKE=1`

Haz `Deploy latest commit` si Auto Deploy no arranca solo.

## 4. Teléfono

Cuando Render esté `Live`:

1. Cierra RouteOps completamente.
2. Abre de nuevo la URL/PWA.
3. Entra a `Recibir`.
4. Debe aparecer `Motor local: Integrado`.
5. Abre cámara.
6. `Cámara` debe pasar a `Activa`.
7. Coloca una etiqueta delante y verifica `Seguimiento: Detectando`.

Si el seguimiento no detecta esa etiqueta concreta, usa `Capturar ahora`; el OCR sigue funcionando.
