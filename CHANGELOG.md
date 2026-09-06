# Changelog

## V0.3.1.3 — Carrier Label Profiles
- Parsers específicos iMile, Ecoscooting y TIPSA/agencia.
- Ranking de tracking por formato para evitar confundir QR/ruta/CP con tracking.
- Extracción de dirección tolerante a etiquetas sin palabra Calle/Avenida.
- READY = carrier + tracking + dirección.
- Fallo/ausencia de geocodificación ya no convierte automáticamente un paquete en REVIEW.
- Diagnóstico OCR/parser en el móvil (no persistente).
- Diagnóstico separado de Google Vision y Google Geocoding.
- Conteo TIPSA/agencia por repartidor.
- Cache PWA actualizada a v0313.
