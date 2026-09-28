# Corrida diaria de precios

`python -m src.daily_run` hace la corrida completa:

1. scraper de Preunic y scraper de Maicao;
2. carga a `raw_listings` y `price_history`;
3. embeddings de las publicaciones nuevas o renombradas;
4. pipeline de matching.

Está pensada para correr una vez al día desde el Programador de tareas de Windows.

## Programarla (una vez)

1. Dejar la base arrancando sola:
   - Docker Desktop → Settings → General → **Start Docker Desktop when you sign in**.
   - `docker update --restart unless-stopped bm-pg`
2. Registrar la tarea (desde la raíz del proyecto; no requiere administrador):

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\register_daily_task.ps1              # 09:00
   powershell -ExecutionPolicy Bypass -File scripts\register_daily_task.ps1 -Time 21:30  # otra hora
   ```

   Agrega `-WakeToRun` para que despierte el equipo si está suspendido.

Para correrla en el momento: `Start-ScheduledTask -TaskName "BeautyMatch - corrida diaria"`.
Para quitarla: `Unregister-ScheduledTask -TaskName "BeautyMatch - corrida diaria"`.

**Qué tiene que estar encendido:** el computador con tu sesión iniciada (puede
estar bloqueado) e internet. Si Docker Desktop o `bm-pg` están apagados, la
corrida intenta levantarlos y espera hasta 3 minutos. Si el computador estaba
apagado a la hora programada, la tarea corre apenas se encienda.

## Revisar cómo salió

- **`artifacts/runs/summary.log`**: una línea por corrida, para leer sin terminal:

  ```
  2026-09-28 09:11  OK       preunic ok 500 prod +500 precios | maicao ok 305 prod +305 precios | embeddings +3 | errores 0 | run_20260928T120000Z.log
  2026-09-29 09:40  PARTIAL  preunic failed [timeout] | maicao ok 305 prod +305 precios | embeddings +0 | errores 1 | run_20260929T120000Z.log
  ```

- **`artifacts/runs/run_<fecha>.log`**: el detalle de esa corrida (cada paso, errores con traza).
- **`python -m src.daily_run --status`**: las últimas corridas desde la base, con notas y errores por tienda.
- **Programador de tareas → "Resultado de la última ejecución"**: `0x0` si salió `ok`;
  `0x1` si salió `partial` o `failed`; `0x2` si la corrida se cayó.

## Estados

| Estado | Tienda | Corrida |
|---|---|---|
| `ok` | Scrape completo y cargado | Todo salió bien |
| `partial` | Se cargaron precios, pero el scrape no terminó limpio o trajo menos del 80 % del catálogo | Algo falló, pero hubo precios nuevos |
| `failed` | No se cargó nada | No se cargó ningún precio |

Un scrape **terminó limpio** cuando recorrió todo el catálogo: en Preunic
desaparece el botón "cargar más" (`catalog_exhausted`); en Maicao, la última
página trae menos productos que el tamaño de página (`short_page`).

Solo un scrape que terminó limpio **y** trae al menos el 80 % de las
publicaciones activas de la tienda desactiva las publicaciones que ya no
aparecen. Un scrape cortado (tiempo máximo de 30 min, error) solo agrega
precios de publicaciones ya conocidas y no desactiva nada.

## Si algo falla

| Falla | Qué pasa |
|---|---|
| Un scraper se cae o se pasa de tiempo | Las otras tiendas se scrapean y cargan igual |
| La base está caída todo el día | Los scrapers corren igual; la corrida siguiente carga esos archivos (`backfill`) |
| Embeddings o matching fallan | Los precios ya quedaron guardados; se reintenta al día siguiente |
| El computador se apaga a mitad | La corrida queda `RUNNING` sin hora de término en `--status`; la siguiente carga lo pendiente |

Opciones útiles: `--stores maicao` (solo una tienda), `--skip-scrape` (solo cargar
pendientes, embeddings y matching), `--timeout 45` (minutos por scraper).
