# Changelog

## V0.3.1.2 — Embedded Vision Engine

- Eliminada la dependencia de OpenCV.js externo para el Smart Label Scanner.
- Nuevo `static/smart_vision.js` servido por RouteOps.
- Nuevo `static/smart_label_scanner.js` separado del template.
- Seguimiento local de regiones de etiqueta por luminancia + densidad de bordes/texto.
- Estimación y suavizado de cuatro esquinas.
- Nitidez, estabilidad y confianza de detección.
- Autocaptura conservada.
- Enderezado local aproximado del recorte antes del OCR.
- Captura manual independiente del motor de visión.
- Panel diagnóstico: motor, cámara, seguimiento, barcode y OCR.
- Visor de cámara ampliado y `object-fit: contain` conservado.
- Service Worker actualizado a cache V0.3.1.2 y limpieza automática de caches anteriores.
- Google Vision y Multi-Carrier Intake se mantienen sin cambios de credenciales.
