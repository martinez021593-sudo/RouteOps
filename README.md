# RouteOps V0.3.1.4 — Intelligent OCR Pipeline

Versión enfocada en dos problemas del piloto real:

1. Google Vision leía texto, pero RouteOps no extraía con suficiente precisión nombre/dirección/tracking.
2. El repartidor tenía que esperar al OCR antes de colocar el siguiente paquete.

## Arquitectura nueva

`Etiqueta → detección local → captura → cola local → upload → cola OCR en PostgreSQL → OCR background → parser carrier → paquete → geocodificación → ruta`

La cámara vuelve a quedar disponible apenas toma la foto. El OCR ya no bloquea el escáner.

## Mejoras OCR

- Google Vision usa `DOCUMENT_TEXT_DETECTION`.
- Preprocesado en servidor con Pillow:
  - corrección EXIF;
  - aumento/reducción a resolución OCR objetivo;
  - autocontraste;
  - contraste moderado;
  - nitidez / Unsharp Mask.
- Segundo pase automático en escala de grises y alto contraste **solo** cuando faltan campos importantes.
- Perfiles carrier V2 para:
  - iMile / SHN;
  - Ecoscooting;
  - TIPSA / agencia Alicante Centro.
- Nombre y dirección se extraen usando estructura propia de cada formato.
- Barcode/QR y tracking se separan. Que el navegador detecte un código primero **no significa** que ese código sea el tracking.

### Tracking

- iMile: prioriza el código de envío de 13 dígitos observado en el formato del piloto.
- Ecoscooting: prioriza `LP...`; `AP...` queda como fallback.
- TIPSA: prioriza referencia/expedición del perfil antes de usar un barcode genérico.

RouteOps guarda también `tracking_source` para saber de dónde salió el tracking.

## Background OCR

La captura se inserta primero en `intake_jobs` con estado:

- `queued`
- `processing`
- `done`
- `duplicate`
- `error`

La foto se elimina de `intake_jobs` cuando termina el procesamiento. El texto OCR completo no se persiste: el modo debug usa memoria temporal.

El piloto usa 2 workers OCR por defecto. Se puede ajustar con:

`INTAKE_OCR_WORKERS=2`

## Cola continua en el móvil

La pantalla muestra:

- por subir;
- en cola;
- procesando;
- terminados.

El navegador permite hasta 2 uploads simultáneos y mantiene una cola local limitada para evitar consumir demasiada memoria.

## Optimización de ruta

Las nuevas paradas geocodificadas no fuerzan una optimización completa por cada OCR individual. RouteOps aplica **debounce** y recalcula la ruta local después de una ráfaga de lecturas.

## Variables

Mantén en Render:

- `GOOGLE_VISION_API_KEY`
- `AUTO_OPTIMIZE_INTAKE=1`

Opcionales:

- `INTAKE_OCR_WORKERS=2`
- `OCR_MULTI_PASS=1`
- `OCR_TARGET_LONG_SIDE=2200`
- `INTAKE_OCR_DEBUG=1`

Si quieres geocodificación automática también necesitas `GOOGLE_MAPS_API_KEY`.

## Migración

`bootstrap.py` / `init_schema()` crea automáticamente `intake_jobs` y añade a `packages`:

- `tracking_source`
- `ocr_confidence`
- `ocr_passes`
- `intake_job_id`

No hay que borrar PostgreSQL.

## Prueba recomendada

Primero prueba 15 paquetes:

- 5 iMile;
- 5 Ecoscooting;
- 5 TIPSA/agencia.

Mide:

- tracking correcto;
- nombre correcto;
- dirección correcta;
- porcentaje READY;
- tiempo físico entre paquete y paquete;
- profundidad máxima de la cola OCR.
