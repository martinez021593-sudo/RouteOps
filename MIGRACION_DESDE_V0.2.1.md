# Migración desde V0.2.1

V0.3 usa `routeops_v03.db` y **no modifica** `routeops_v02.db`.

Para la primera prueba recomiendo NO migrar la base anterior. Crea una jornada nueva e importa los paquetes con `paquetes_ejemplo_v03.csv` o tu archivo real. Esto permite validar Smart Dispatch sin mezclar datos históricos.

Si después quieres conservar el historial de V0.2.1, se hará una migración explícita cuando confirmemos los campos reales de empresa/origen/tipo que usa la operación.
