# Changelog

## V0.3.1.1 — Smart Label Scanner
- Cámara de recepción ampliada casi a pantalla completa.
- `object-fit: contain` para evitar el recorte visual que parecía zoom.
- Solicitud de cámara trasera 4:3 de alta resolución.
- Consulta de capacidades del track y solicitud de zoom mínimo cuando el navegador lo permite.
- Solicitud de enfoque continuo cuando el dispositivo/navegador expone esa capacidad.
- Selector para cambiar de cámara cuando hay varias cámaras traseras disponibles.
- Linterna opcional cuando la cámara expone `torch`.
- OpenCV.js en el cliente para detectar la superficie rectangular de la etiqueta.
- Marco dinámico que sigue los bordes/área impresa de la etiqueta.
- Estado `Aléjate un poco` cuando la etiqueta ocupa casi toda la imagen y no se ven sus bordes.
- Suavizado temporal del marco para evitar saltos.
- Estimación de nitidez y estabilidad antes de la autocaptura.
- Autocaptura después de 5 frames estables; captura manual siempre disponible.
- Recorte y corrección de perspectiva antes de enviar la imagen a Google Vision.
- El OCR recibe el recorte de la etiqueta y no el fondo completo cuando la detección es válida.
- Barcode/QR sigue funcionando en paralelo.
- Beep/vibración de confirmación cuando el navegador lo permite.
- Mantiene Multi-Carrier Intake, clasificación, contadores, trazabilidad y reoptimización incremental.

## V0.3.1 — Multi-Carrier Intake
- iMile / Ecoscooting / tercera operadora.
- OCR opcional con Google Vision.
- Recepción por cámara y normalización de etiquetas.
