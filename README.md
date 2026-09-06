# RouteOps V0.3.1.2 — Embedded Vision Engine

Actualización de RouteOps V0.3.1.1 centrada en eliminar el fallo de carga de OpenCV/CDN y mantener el Smart Label Scanner operativo incluso con conectividad irregular.

## Cambio principal

V0.3.1.1 dependía de un `opencv.js` externo. En V0.3.1.2 el seguimiento básico de etiquetas se ejecuta con un **motor de visión local incluido dentro de RouteOps**:

- `/static/smart_vision.js`
- `/static/smart_label_scanner.js`

No necesita descargar OpenCV desde `docs.opencv.org` al abrir el escáner.

## Flujo

`Cámara → detectar región de etiqueta → seguir bordes → medir nitidez/estabilidad → autocaptura → enderezado local → QR/barcode + OCR → carrier → guardar → reoptimizar`.

## Qué hace el Embedded Vision Engine

1. Reduce cada frame a una resolución de análisis ligera.
2. Calcula luminancia y contraste local.
3. Busca superficies claras y regiones con densidad de texto/barcodes.
4. Agrupa regiones localmente.
5. Selecciona una región rectangular compatible con una etiqueta.
6. Estima cuatro esquinas y las suaviza entre frames.
7. Calcula nitidez y estabilidad.
8. Cuando la etiqueta está estable puede autocapturar.
9. En la captura realiza un enderezado local aproximado antes del OCR.

## Fallback

El botón **Capturar ahora** nunca depende del motor de bordes.

Si el motor no encuentra una etiqueta:

`Cámara → Capturar ahora → foto completa → Google Vision OCR → revisión si hace falta`.

Por lo tanto, un fallo del seguimiento no bloquea la recepción de paquetes.

## Diagnóstico nuevo

El repartidor ve en pantalla:

- Motor local
- Cámara
- Seguimiento
- QR / barcode
- Google Vision OCR

Cada componente muestra estado disponible, esperando o error. Esto permite saber exactamente qué parte falla en un teléfono real.

## Cámara

- vídeo con `object-fit: contain` para evitar recorte visual;
- visor más grande;
- cámara trasera preferida;
- zoom mínimo cuando el dispositivo lo expone;
- enfoque continuo solicitado cuando el navegador lo permite;
- linterna y cambio de cámara cuando están disponibles.

## Google Vision

Mantén en Render:

`GOOGLE_VISION_API_KEY=<tu clave>`

También:

`AUTO_OPTIMIZE_INTAKE=1`

Nunca subas estas claves a GitHub.

## Caché/PWA

El Service Worker se actualizó a `routeops-v0312-shell-v1` y elimina caches anteriores al activarse. Esto evita que un móvil siga usando JavaScript viejo después del deploy.

Después del primer deploy de V0.3.1.2 conviene cerrar y volver a abrir RouteOps en el teléfono. Si estaba instalada como PWA, también se puede cerrar completamente la app y abrirla de nuevo.

## Prueba piloto

Primero probar:

- 3–5 iMile
- 3–5 Ecoscooting
- 3–5 tercera operadora

Registrar:

- segundos por paquete;
- porcentaje con marco detectado;
- porcentaje autocapturado;
- porcentaje OCR correcto;
- paquetes enviados a `Revisar`;
- duplicados detectados.

## Limitación conocida

El detector local está optimizado para etiquetas claras con texto/barcodes sobre paquetes de color contrastante. Una etiqueta blanca sobre un paquete muy blanco, una etiqueta muy arrugada o parcialmente tapada puede requerir **Capturar ahora**. El OCR y el registro siguen funcionando en modo manual.
