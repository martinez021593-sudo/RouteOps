# RouteOps V0.3.1.1 — Smart Label Scanner

Actualización de RouteOps V0.3.1 enfocada en recepción rápida de paquetes por cámara.

## Objetivo

Que el repartidor pueda pasar paquetes frente al teléfono con mínima interacción:

`Etiqueta → detectar borde → estabilizar/enfocar → autocapturar → corregir perspectiva → OCR → clasificar carrier → guardar → reoptimizar → siguiente paquete`.

## Qué cambia en la cámara

- Vista vertical grande.
- El vídeo usa `object-fit: contain`; no recorta los laterales para llenar el visor.
- RouteOps solicita la cámara trasera y una resolución 4:3 alta.
- Si la cámara expone zoom, RouteOps solicita el zoom mínimo.
- Si expone `focusMode=continuous`, RouteOps lo solicita; si no, se usa el autofocus nativo del teléfono.
- Si hay varias cámaras, aparece `Cambiar cámara`.
- Si existe control de linterna, aparece `Linterna`.

## Seguimiento de etiqueta

La página carga OpenCV.js desde la documentación oficial de OpenCV. El procesamiento se hace en el navegador:

1. Canny / bordes.
2. Morfología para unir texto, códigos y borde exterior.
3. Contornos.
4. Convex hull + cuadrilátero cuando es posible.
5. `minAreaRect` como fallback para etiquetas arrugadas.
6. Suavizado temporal de las 4 esquinas.
7. Medición de estabilidad y nitidez.

Cuando la etiqueta llena prácticamente todo el frame, RouteOps pide `Aléjate un poco` en vez de capturar sin bordes.

## Autocaptura

Por defecto está activa. Requiere:
- etiqueta detectada;
- nitidez mínima;
- movimiento bajo;
- 5 frames estables.

Siempre existe `Capturar ahora` como fallback.

## Corrección de perspectiva

Cuando hay un cuadrilátero válido, RouteOps usa `getPerspectiveTransform` + `warpPerspective` para generar un recorte frontal de la etiqueta. Solo ese JPEG se envía al endpoint de intake/Google Vision.

Si OpenCV no carga o no logra detectar el borde, la captura manual usa el frame completo y el flujo de V0.3.1 sigue funcionando.

## Google Vision

En Render:

`GOOGLE_VISION_API_KEY=<tu clave>`

Mantén la clave restringida a Cloud Vision API.

## Actualizar la web existente

No crees otro servicio Render.

1. Descomprime esta carpeta.
2. Sube su contenido a la raíz del repositorio GitHub `RouteOps` reemplazando los archivos anteriores.
3. Haz commit.
4. Render hará redeploy automático. Si no, `Manual Deploy → Deploy latest commit`.
5. Conserva la misma URL pública.

## Prueba recomendada

Antes de 100 paquetes:
- 5 iMile
- 5 Ecoscooting
- 5 tercera operadora

Registrar:
- detección correcta de bordes;
- % autocapturado sin tocar botón;
- % de OCR correcto;
- segundos por paquete;
- cuántos requieren revisión manual.

## Compatibilidad

Las capacidades físicas de zoom, enfoque continuo y linterna dependen del teléfono y del navegador. RouteOps consulta `getCapabilities()` y solo intenta aplicar controles que el dispositivo expone.

OpenCV.js se carga desde Internet. Si no carga, RouteOps conserva captura manual + QR/barcode + OCR del frame completo.
