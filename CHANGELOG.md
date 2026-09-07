# Changelog

## V0.3.1.4 — Intelligent OCR Pipeline

- OCR migrado de `TEXT_DETECTION` a `DOCUMENT_TEXT_DETECTION`.
- Preprocesamiento de etiqueta en servidor con Pillow.
- Segundo pase OCR inteligente en alto contraste cuando faltan campos.
- Perfiles iMile / Ecoscooting / TIPSA actualizados a V2.
- Separación real entre barcode/QR y tracking.
- `tracking_source` para auditar por qué se eligió un tracking.
- Cola persistente `intake_jobs` en SQLite/PostgreSQL.
- OCR asíncrono con `ThreadPoolExecutor`.
- Recuperación de trabajos queued/processing después de reinicio del web worker.
- Captura móvil continua: el usuario no espera a Google Vision.
- Hasta 2 subidas simultáneas desde el navegador.
- Panel de cola: local, servidor, procesando, terminados.
- Fotos de intake eliminadas de la base al completar/error.
- Texto OCR completo solo en cache temporal de diagnóstico.
- Reoptimización de ruta con debounce después de ráfagas de escaneo.
- PWA cache actualizada a `routeops-v0314-shell-v1`.
