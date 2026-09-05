# RouteOps V0.3.0 — publicar en Internet con Render

## Objetivo
Que RouteOps funcione desde una URL HTTPS pública para que el administrador pueda entrar desde Colombia y los repartidores desde España.

## Qué cambia
- El servidor ya no depende del PC del administrador.
- PostgreSQL sustituye a SQLite cuando existe `DATABASE_URL`.
- Render proporciona HTTPS público automáticamente.
- Cámara, GPS, PWA y tracking funcionan sobre contexto HTTPS.
- Las fotos de evidencia se comprimen y guardan en PostgreSQL para este piloto, evitando depender del disco efímero del servidor.

## Despliegue recomendado

### 1. Crear un repositorio privado en GitHub
Sube el contenido de esta carpeta a un repositorio privado, por ejemplo `routeops-internet-pilot`.

No subas `.env` ni credenciales de Google. `.gitignore` ya los excluye.

### 2. Render -> New -> Blueprint
Conecta el repositorio y selecciona el `render.yaml` incluido.

El Blueprint crea:
- `routeops-internet-pilot`: servicio web.
- `routeops-pilot-db`: PostgreSQL.

### 3. Contraseñas iniciales
Render te pedirá los secretos marcados `sync: false`:

- `BOOTSTRAP_ADMIN_PASSWORD`: elige una contraseña fuerte.
- `BOOTSTRAP_DRIVER_PASSWORD`: contraseña temporal para Carlos/Juan/Miguel.

### 4. Aplicar Blueprint
Render instalará dependencias, inicializará la base y arrancará Gunicorn.

Al finalizar tendrás una URL parecida a:

`https://routeops-internet-pilot.onrender.com`

### 5. Prueba Colombia <-> España
1. Tú abres la URL en Colombia e inicias como administrador.
2. Tu amigo abre la misma URL desde España.
3. Puede entrar como `carlos`, `juan` o `miguel` con la contraseña temporal elegida.
4. Crea/activa una jornada.
5. Asigna un paquete al repartidor.
6. El repartidor lo abre, activa tracking y registra la entrega.
7. El administrador debe verla sin refrescar infraestructura ni estar en la misma red.

## Acceso inicial
El correo administrador por defecto es:

`admin@routeops.local`

El usuario de administrador también es:

`admin`

Los usuarios repartidor por defecto son:
- `carlos`
- `juan`
- `miguel`

Las contraseñas se definen en Render durante el primer Blueprint.

## Limitación del plan gratuito de Render
El Blueprint está configurado en `free` para hacer la primera prueba remota con el menor coste posible.

Para un piloto continuo, cambia el servicio/base de datos a un plan de pago. La base PostgreSQL gratuita de Render es temporal y no debe usarse como almacenamiento permanente de producción.

## Evidencias fotográficas
Para resolver primero el problema de distancia sin añadir otro proveedor, V0.3.0 guarda la foto comprimida dentro de PostgreSQL.

Esto es correcto para pruebas pequeñas. Antes de operar miles de entregas/mes moveremos evidencias a almacenamiento de objetos (S3/R2/Cloudinary/Supabase Storage).

## Actualizaciones
Una vez el repositorio esté conectado:

1. actualizas el código;
2. haces `git push`;
3. Render detecta el cambio;
4. genera un nuevo deploy;
5. España y Colombia reciben la versión nueva en la misma URL.

No hay que volver a instalar RouteOps en los teléfonos.

## Health check
`/healthz`

Debe responder algo equivalente a:

`{"ok":true,"version":"0.3.0","database":"postgresql"}`
