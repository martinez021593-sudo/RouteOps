# RouteOps V0.3.1.3 — Carrier Label Profiles

Calibración del intake con las etiquetas reales del piloto.

## Perfiles
- **iMile / SHN**: detecta iMile, SHN, ALC7, R-3, CP 03700, barcode de envío, G.W y bloque TO.
- **Ecoscooting**: detecta MAD-ALC1, LP..., ALICxxA, CP 03013, Claim weight y dirección.
- **TIPSA / agencia**: detecta el template ALICANTE CENTRO 10, BULTOS, REEMBOLSO, RTE/DES/CAL y códigos de expedición. Algunas etiquetas pueden llevar branding de partner/cliente; se identifica el perfil logístico, no solamente el logo.

## Cambio crítico de READY
`READY` ahora significa **operadora + tracking + dirección**. Nombre, teléfono, peso, zona y ruta son campos complementarios y no bloquean el intake.

La geocodificación queda separada de la clasificación. Si falta `GOOGLE_MAPS_API_KEY`, el paquete puede quedar READY pero todavía no entra a la optimización por coordenadas.

## Diagnóstico OCR
Durante el piloto `INTAKE_OCR_DEBUG=1` muestra, solo en el dispositivo autenticado y sin persistirlo en la base, el texto recibido de Google Vision y el perfil usado por el parser. Esto permite distinguir:
- OCR leyó mal;
- OCR leyó bien pero el parser no interpretó el campo.

## Variables Render
- `GOOGLE_VISION_API_KEY` — OCR.
- `GOOGLE_MAPS_API_KEY` — geocodificación (opcional para clasificación, necesaria para ruta automática por coordenadas).
- `AUTO_OPTIMIZE_INTAKE=1`
- `INTAKE_OCR_DEBUG=1` durante calibración; cambiar a `0` después del piloto.

## Despliegue
Sube el contenido a la raíz del mismo repositorio RouteOps, commit y push. Render conservará URL/base de datos. Cierra/reabre la PWA después del deploy para descartar cache anterior.
