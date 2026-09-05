# RouteOps V0.3.1 — Multi-Carrier Intake + Camera Intake

## Qué añade
- Recepción continua con cámara del repartidor.
- QR/barcode prioritario.
- OCR opcional de etiqueta completa con Google Cloud Vision.
- Detección iMile / Ecoscooting / tercera operadora.
- Extracción y normalización de tracking, dirección, CP, zona/ruta, peso y cantidad.
- El paquete queda asignado al repartidor que lo escaneó.
- Contadores por empresa y por repartidor.
- Registro del repartidor que finalmente entregó cada paquete.
- Estado `ready` / `review`; nunca inventa una dirección faltante.
- Geocodificación y reoptimización local tras cada lectura válida.
- Panel admin Multi-Carrier Intake.

## OCR
Para leer la información impresa completa configura en Render `GOOGLE_VISION_API_KEY`. Sin esa clave el QR/barcode sigue funcionando, pero la dirección puede requerir revisión.

## Por qué la ruta se optimiza localmente durante la recepción
No conviene llamar Google Route Optimization después de cada paquete porque genera una solicitud de pago por cada escaneo. V0.3.1 reordena localmente en tiempo real y permite ejecutar Google Road al terminar el lote.

## Privacidad
Las etiquetas contienen datos personales. Esta versión no guarda el texto OCR completo ni la foto de intake por defecto; conserva solamente los campos necesarios para reparto.

## Deploy
Sube todos los archivos de esta carpeta a la raíz del mismo repositorio GitHub. Render redeployará la URL existente.
