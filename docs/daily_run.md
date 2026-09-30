# Corrida diaria de precios

`python -m src.daily_run` hace la corrida completa:

1. scrapers de Preunic, Maicao y Salcobrand;
2. carga a `raw_listings` y `price_history`;
3. embeddings de las publicaciones nuevas o renombradas;
4. pipeline de matching entre las tres tiendas (`MATCHING_STORES` en
   `src/matching/pipeline.py`).

Una tienda que se scrapea pero no está en `MATCHING_STORES` acumula historial
de precios, pero sus publicaciones quedan `pending`, sin producto, y la API
no las muestra. Así entró Salcobrand hasta que se validó su matching.

Está pensada para correr una vez al día desde el Programador de tareas de Windows.

## Programarla (una vez)

1. Dejar la base arrancando sola:
   - Docker Desktop → Settings → General → **Start Docker Desktop when you sign in**.
   - `docker update --restart unless-stopped bm-pg`
2. Descargar el modelo de embeddings (~1 GB, con internet). Si ya corriste
   `python -m src.matching.embeddings` alguna vez, ya está descargado:

   ```powershell
   python -m src.matching.embeddings --download-model
   ```
3. Registrar la tarea (desde la raíz del proyecto; no requiere administrador):

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\register_daily_task.ps1              # 09:00
   powershell -ExecutionPolicy Bypass -File scripts\register_daily_task.ps1 -Time 21:30  # otra hora
   ```

   Agrega `-WakeToRun` para que despierte el equipo si está suspendido.

Para correrla en el momento: `Start-ScheduledTask -TaskName "BeautyMatch - corrida diaria"`.
Para quitarla: `Unregister-ScheduledTask -TaskName "BeautyMatch - corrida diaria"`.

**Qué tiene que estar encendido:** el computador con tu sesión iniciada (puede
estar bloqueado) e internet, para los scrapers. Si Docker Desktop o `bm-pg`
están apagados, la corrida intenta levantarlos y espera hasta 3 minutos. Si el
computador estaba apagado a la hora programada, la tarea corre apenas se encienda.

**Modelo de embeddings sin conexión:** la corrida carga el modelo desde el disco
(`HF_HUB_OFFLINE=1`, solo archivos locales en `%USERPROFILE%\.cache\huggingface\hub`)
y no consulta a Hugging Face. Si el modelo no está descargado, el paso de
embeddings falla con este mensaje (los precios de la corrida quedan cargados
igual y la corrida queda `partial`):

```
embedding model intfloat/multilingual-e5-base is not downloaded (cache: ...).
Download it once, with internet: python -m src.matching.embeddings --download-model
```

## Revisar cómo salió

- **`artifacts/runs/summary.log`**: una línea por corrida, para leer sin terminal:

  ```
  2026-09-28 09:11  OK       preunic ok 500 prod +500 precios | maicao ok 305 prod +305 precios | embeddings +3 | errores 0 | run_20260928T120000Z.log
  2026-09-29 09:40  PARTIAL  preunic failed [timeout] | maicao ok 305 prod +305 precios | embeddings +0 | errores 1 | run_20260929T120000Z.log
  ```

- **`artifacts/runs/run_<fecha>.log`**: el detalle de esa corrida (cada paso, errores con traza).
- **`python -m src.daily_run --status`**: las últimas corridas desde la base, con notas y errores por tienda.
- **Programador de tareas → "Resultado de la última ejecución"**: `0x0` si salió `ok`;
  `0x1` si salió `partial` o `failed`; `0x2` si la corrida se cayó; `0x3` si no
  corrió porque ya había otra en curso.

**Una corrida a la vez.** Si se inicia una corrida mientras otra sigue en curso
(por ejemplo, la tarea programada y un `python -m src.daily_run` a mano), la
segunda no hace nada y deja una línea en `summary.log`:

```
2026-09-30 09:00  SKIPPED  another daily run is in progress (pid 6064 since 2026-09-30 08:58:12)
```

El bloqueo lo libera el sistema operativo cuando termina la corrida que lo
tiene, aunque se caiga o se cierre a la fuerza: nunca queda trabado.

## Estados

| Estado | Tienda | Corrida |
|---|---|---|
| `ok` | Scrape completo y cargado | Todo salió bien |
| `partial` | Se cargaron precios, pero el scrape no terminó limpio o no trae el catálogo completo (ver abajo) | Algo falló, pero hubo precios nuevos |
| `failed` | No se cargó nada | No se cargó ningún precio |

Un scrape **terminó limpio** cuando recorrió todo el catálogo: en Preunic
desaparece el botón "cargar más" (`catalog_exhausted`); en Maicao, la última
página trae menos productos que el tamaño de página (`short_page`).

Solo un scrape que terminó limpio **y** trae el catálogo completo desactiva
las publicaciones que ya no aparecen. "Catálogo completo" depende de la tienda:

- **Preunic:** la categoría muestra su total ("497 productos") y el scraper lo
  guarda en `pagination.site_total`. Las publicaciones leídas tienen que ser
  **exactamente** ese número. Si no coinciden, o la página no mostró el total,
  se cargan los precios, no se desactiva nada y la tienda queda `partial` con
  una nota ("read 496 listings, the store reports 497").
- **Maicao:** la página no muestra el total, pero cada página del listado lo
  pide a la API de búsqueda de la tienda (`total` en la respuesta). El
  scraper escucha esas respuestas, sin hacer consultas propias, y guarda el
  último total en `pagination.site_total`. Se aplica la misma regla exacta que
  en Preunic. Si el scraper no logró leer el total (la respuesta cambió o no
  llegó), vuelve a la regla anterior, al menos el 80 % de las publicaciones
  activas de la tienda, y lo deja anotado: "store total not captured: used
  the 80% coverage rule".

Un scrape cortado (tiempo máximo de 30 min, error) solo agrega precios de
publicaciones ya conocidas y no desactiva nada.

## Si algo falla

| Falla | Qué pasa |
|---|---|
| Un scraper se cae o se pasa de tiempo | Las otras tiendas se scrapean y cargan igual |
| La base está caída todo el día | Los scrapers corren igual; la corrida siguiente carga esos archivos (`backfill`) |
| Embeddings o matching fallan | Los precios ya quedaron guardados; se reintenta al día siguiente |
| El modelo de embeddings no está descargado | El paso de embeddings falla con el mensaje de arriba; descargarlo con `--download-model` |
| El computador se apaga a mitad | La corrida queda `RUNNING` sin hora de término en `--status`; la siguiente carga lo pendiente |

Opciones útiles: `--stores maicao` (solo una tienda), `--skip-scrape` (solo cargar
pendientes, embeddings y matching), `--timeout 45` (minutos por scraper).

## Respaldar la base

El historial de precios no se puede reconstruir: un día que no quedó guardado
se pierde. Conviene respaldar la base al menos una vez por semana y siempre
antes de aplicar una migración. Desde la raíz del proyecto:

```powershell
New-Item -ItemType Directory -Force backups | Out-Null
docker exec bm-pg pg_dump -U postgres -Fc -d beautymatch -f /tmp/beautymatch.dump
docker cp bm-pg:/tmp/beautymatch.dump "backups\beautymatch_$(Get-Date -Format yyyyMMdd_HHmm).dump"
docker exec bm-pg unlink /tmp/beautymatch.dump
```

- `pg_dump` toma una foto consistente aunque la API o una corrida estén usando la base.
- El archivo queda fuera del contenedor: si se borra `bm-pg`, el respaldo sigue ahí.
- Los `*.dump` están en `.gitignore`: no se suben al repositorio por error.

Para restaurar un respaldo, ver la opción A de [api.md](api.md#opción-a-restaurar-un-respaldo-recomendada-para-el-frontend).
