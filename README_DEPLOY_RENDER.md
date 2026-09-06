# Deploy V0.3.1.1 sobre el RouteOps existente

La URL y la base PostgreSQL existentes se mantienen.

1. Sube a GitHub todos los archivos de `RouteOps_V0.3.1.1_Smart_Label_Scanner`.
2. Confirma que estén `app.py`, `db_layer.py`, `intake_engine.py`, `templates/`, `static/`, `bootstrap.py`, `wsgi.py`, `render.yaml`.
3. En Render confirma estas variables:
   - `DATABASE_URL`
   - `SECRET_KEY`
   - `GOOGLE_VISION_API_KEY`
   - `AUTO_OPTIMIZE_INTAKE=1`
4. Deploy latest commit.
5. Prueba en HTTPS desde el teléfono del repartidor.

No subas API keys a GitHub.
