# RouteOps V0.3 — Cloud-ready + Smart Dispatch Engine

V0.3 incorpora la lógica real de clasificación que ocurre **antes de optimizar rutas**. Mantiene todo lo validado en V0.2.1 LAN Pilot y añade un motor auditable de reglas para separar paquetes por empresa, país/origen, zona, tipo y características.

## Flujo V0.3

```text
Jornada
  ↓
Importar paquetes
  ↓
SMART DISPATCH
  ├─ empresa
  ├─ país/origen
  ├─ zona
  ├─ tipo
  ├─ peso
  ├─ prioridad
  └─ características
  ↓
Revisión de excepciones
  ↓
Carlos / Juan / Miguel
  ↓
Optimización vial/local
  ↓
Ruta + tracking + entrega
  ↓
Liquidación
```

## Novedades principales

- Smart Dispatch por reglas de negocio.
- Campos nuevos por paquete:
  - `pais_origen`
  - `empresa`
  - `zona`
  - `tipo_paquete`
  - `peso_kg`
  - `prioridad`
  - `caracteristicas`
- Reglas con prioridad: la primera coincidencia gana.
- Condiciones combinables: empresa + país + zona + tipo + rango de peso + prioridad + texto de característica.
- Explicación de asignación guardada por paquete.
- Historial de asignaciones manuales y automáticas.
- Excepciones: si no existe regla, RouteOps no inventa conductor.
- Opción **Clasificar sin asignados** para proteger asignaciones manuales.
- Opción **Reclasificar todo** para aplicar reglas incluso sobre asignaciones existentes.
- Sugerencias de reglas cuando las correcciones manuales muestran un patrón consistente.
- Plantilla `paquetes_ejemplo_v03.csv` sin conductor para probar el clasificador.
- Mantiene jornadas, QR/barcode, tracking LAN, evidencias, rutas y liquidaciones.
- Preparación cloud mediante `ROUTEOPS_DATA_DIR`, Docker y Gunicorn.

## Arranque normal

1. Extrae la carpeta.
2. Ejecuta `install_and_run.bat` para un solo PC, o `install_and_run_lan.bat` para PC + móviles en el mismo Wi-Fi.
3. Admin: `admin@routeops.local / demo123`.
4. Repartidores: `carlos / 1234`, `juan / 1234`, `miguel / 1234`.

## Prueba recomendada de Smart Dispatch

1. Admin → **Jornadas** → crea una nueva jornada.
2. Abre **Paquetes**.
3. Importa `paquetes_ejemplo_v03.csv`.
4. Abre **Smart Dispatch**.
5. Revisa las tres reglas demo.
6. Pulsa **Clasificar sin asignados**.
7. Observa qué paquetes se asignan y cuáles quedan como excepción.
8. Corrige manualmente las excepciones desde Paquetes.
9. Cuando las asignaciones estén correctas, entra en **Rutas** y optimiza.

### Reglas demo

- `Empresa 1 → Carlos`
- `Empresa 3 + Zona Norte → Juan`
- `Tipo voluminoso → Miguel`

Las demás combinaciones quedan como excepciones para que puedas verificar el flujo de revisión manual.

## Formato CSV/XLSX V0.3

Columnas recomendadas:

```text
codigo
barcode
cliente
telefono
direccion
pais_origen
empresa
zona
tipo_paquete
peso_kg
prioridad
caracteristicas
lat
lon
conductor   (opcional)
```

Si `conductor` viene vacío, Smart Dispatch intenta clasificarlo. Si viene informado, se considera una preasignación importada.

## Cómo se evalúa una regla

Ejemplo:

```text
Empresa = Empresa 3
Zona = Norte
→ Juan
```

Un paquete debe cumplir **todas** las condiciones no vacías de esa regla. Las reglas se prueban de menor a mayor `Prioridad regla`. La primera coincidencia se utiliza.

RouteOps guarda, por ejemplo:

```text
Asignado por: rule
Motivo: Empresa=Empresa 3 · Zona=Norte
```

## Aprendizaje de patrones

V0.3 no entrena un modelo de IA. Hace algo más seguro para esta fase: observa el historial de **asignaciones manuales**. Cuando una combinación de empresa/origen/zona/tipo aparece al menos 3 veces y termina en el mismo repartidor al menos el 80% de las veces, puede mostrar una sugerencia para convertir ese patrón en una regla. El administrador debe aprobarla.

Esto evita que el sistema “aprenda” decisiones incorrectas sin revisión.

## Cloud-ready

V0.3 incluye:

- `Dockerfile`
- `docker-compose.yml`
- `requirements-cloud.txt`
- `wsgi.py`
- variable `ROUTEOPS_DATA_DIR`
- cookies Secure configurables

Para una prueba local de Docker:

```text
docker compose up --build
```

Después abre `http://localhost:8000`.

### Importante

Esta V0.3 sigue usando **SQLite + almacenamiento de archivos en disco**. Puede desplegarse como **pilot cloud de una sola instancia con disco persistente**, pero no es la arquitectura final para cientos de empresas/conductores.

Antes de producción comercial se migrará a PostgreSQL + object storage y se añadirá una estrategia de backups/retención.

## Google Route Optimization

Se conserva la integración opcional de V0.2. El modo Local continúa funcionando sin credenciales. Google Road requiere las variables ya documentadas en `.env.example`.

## Seguridad

V0.3 es una build de piloto:

- no exponer el servidor Flask local directamente a Internet;
- para Internet usar un hosting/reverse proxy HTTPS;
- cambiar `SECRET_KEY` y las claves demo;
- el tracking solo debe activarse con conocimiento del repartidor;
- antes de clientes externos se añadirán CSRF, recuperación de cuenta, auditoría ampliada y políticas de retención.

## Base de datos

Por defecto:

`routeops_v03.db`

Para reiniciar la demo local ejecuta `reset_demo.bat`.

## Qué valida esta versión

La pregunta principal de V0.3 no es todavía “¿qué algoritmo de IA usamos?”. Es:

> ¿Podemos representar correctamente las reglas que hoy usa la persona que separa físicamente los paquetes y reducir el trabajo manual sin introducir asignaciones incorrectas?

Cuando la respuesta sea sí con datos reales, el siguiente paso será desplegar el Cloud Pilot real y validar la operación fuera del Wi-Fi.
