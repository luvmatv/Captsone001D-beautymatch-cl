# Desplegar la API en Azure Container Apps

La API corre en **Azure Container Apps** (plan Consumption, región **Brazil
South**) con la base en **Neon** (São Paulo). El scraper y la corrida diaria
siguen en el PC. Suscripción: *Azure for Students* (sin tarjeta: si se acaba el
crédito, los recursos se apagan; no hay cobros extra).

## Qué hay en la imagen

- `Dockerfile` + `requirements-api.txt`: Python 3.14, torch solo CPU y las
  mismas versiones que el entorno de desarrollo. Sin scrapers ni tests.
- El modelo de embeddings (`intfloat/multilingual-e5-base`) se descarga **al
  construir la imagen**. El contenedor corre sin conexión a Hugging Face
  (`HF_HUB_OFFLINE=1`): un arranque en frío nunca espera esa descarga.
- `.dockerignore` es una lista de permitidos: solo entran `src/` y
  `requirements-api.txt` (nunca `.env`, datos ni respaldos).
- Corre como usuario sin privilegios (uid 1000) en el puerto 8000.

Medido en el PC (2026-10-23, `--cpus 1 --memory 2g`): la imagen pesa 3,9 GB;
`/healthz` responde a los 5 s; el modelo queda listo a los 14 s (mientras
tanto `/search/semantic` responde `503` con `Retry-After`); con el modelo
cargado usa ~780 MiB.

## Configuración de la app

| Variable | Valor | Por qué |
|---|---|---|
| `DATABASE_URL` | La URL **pooler** de Neon, como secreto `database-url` | La API solo lee: el pooler le sirve (la corrida diaria, en cambio, usa la directa). La URL de Neon ya trae `sslmode=require` |
| `API_CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173` | Por ahora; se agrega la URL del frontend real cuando exista |
| `API_POOL_MAX_SIZE` | `4` | Una sola réplica, pocas conexiones |

Con `DATABASE_URL`, el pool no deja conexiones abiertas sin uso (mínimo 0,
cierre a los 4 min): así Neon puede suspenderse y no gasta sus 100 horas de
cómputo mensuales. Con la URL pooler se desactivan las sentencias preparadas
(PgBouncer en modo transacción no las conserva).

`GET /healthz` (fuera de `/docs`) responde `{"status": "ok", "semantic_model":
"loading" | "ready" | "not_loaded"}` sin tocar la base: sirve para revisar un
arranque y para las sondas de salud sin despertar Neon.

## Recursos (paso 7; crearlos solo con el OK)

| Recurso | Nombre | Notas |
|---|---|---|
| Grupo de recursos | `rg-beautymatch` | Brazil South (la suscripción solo permite northcentralus, newzealandnorth, canadacentral, southafricanorth y brazilsouth) |
| Registro de imágenes | `<acr>` (nombre único global, p. ej. `bmapiregistry`) | Plan **Standard**: Azure for Students incluye un registro Standard (100 GB) gratis por 12 meses; Basic no entra en ese beneficio |
| Entorno de Container Apps | `cae-beautymatch` | `--logs-destination none`: sin Log Analytics, sin cobros por logs |
| Container App | `beautymatch-api` | 1 vCPU / 2 GiB, 0 a 1 réplica, acceso externo al puerto 8000 |

> **Desde el 2026-11-10 la CLI de Azure no sirve en este PC.** Duoc bloquea
> `az login` con el error **53003** (acceso condicional: dispositivo no
> registrado). No se buscan otras formas de iniciar sesión con `az`. El
> portal web (https://portal.azure.com) sí funciona: todo se hace como en
> [Procedimiento actual: portal + token del registro](#procedimiento-actual-portal--token-del-registro).
> Los comandos `az` de abajo quedan como registro de cómo se crearon los
> recursos (paso 7, 2026-10-30).

### Comandos (creación original, con la CLI)

`az` no está en el PATH: se usa con su ruta completa. `docker` tampoco.

```powershell
$az = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
$docker = "C:\Users\lukas\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe"
$acr = "bmapiregistry"          # nombre del registro (único en Azure)
$tag = "<sha corto de main>"    # una etiqueta por commit, nunca latest

# 1. Una vez: extensión y proveedores de la suscripción
& $az extension add --name containerapp --upgrade
& $az provider register --namespace Microsoft.App --wait
& $az provider register --namespace Microsoft.ContainerRegistry --wait
& $az provider register --namespace Microsoft.OperationalInsights --wait

# 2. Grupo y registro
& $az group create --name rg-beautymatch --location brazilsouth
& $az acr create --resource-group rg-beautymatch --name $acr --sku Standard --location brazilsouth

# 3. Imagen: construir desde main, etiquetar y subir
& $docker build -t "beautymatch-api:$tag" .
& $docker tag "beautymatch-api:$tag" "$acr.azurecr.io/beautymatch-api:$tag"
# az acr login llama a docker: necesita encontrarlo en el PATH (solo en esta sesión).
# (Pasar el token por tubería a "docker login --password-stdin" falla en PowerShell 5.1.)
$env:PATH = "$(Split-Path $docker);$env:PATH"
& $az acr login --name $acr
& $docker push "$acr.azurecr.io/beautymatch-api:$tag"

# 4. Entorno y app. La app se crea con una URL provisoria: arranca, y los
#    endpoints que leen la base responden 503 hasta cargar la real (paso 5).
#    ConsumptionOnly a la vista: la extensión 1.3.0b5 crea si no un entorno
#    "Express" (preliminar), donde la app no puede leer del registro con su identidad.
& $az containerapp env create --name cae-beautymatch --resource-group rg-beautymatch `
    --location brazilsouth --logs-destination none --environment-mode ConsumptionOnly
& $az containerapp create --name beautymatch-api --resource-group rg-beautymatch `
    --environment cae-beautymatch --image "$acr.azurecr.io/beautymatch-api:$tag" `
    --registry-server "$acr.azurecr.io" --registry-identity system `
    --target-port 8000 --ingress external --cpu 1.0 --memory 2.0Gi `
    --min-replicas 0 --max-replicas 1 `
    --secrets "database-url=postgresql://pending@localhost/pending" `
    --env-vars "DATABASE_URL=secretref:database-url" "API_POOL_MAX_SIZE=4" `
               "API_CORS_ORIGINS=http://localhost:3000,http://localhost:5173"

# 5. La URL pública
& $az containerapp show --name beautymatch-api --resource-group rg-beautymatch `
    --query properties.configuration.ingress.fqdn -o tsv
```

### El secreto (lo carga el dueño de la cuenta, no se escribe en el chat)

La URL de Neon trae `&` (`...?sslmode=require&channel_binding=require`).
`az.cmd` pasa por `cmd`, que corta ahí; por eso se llama al Python de la CLI
directamente. `-AsSecureString` evita que la URL quede a la vista en la
pantalla (no copiar la salida de este bloque a ningún chat).

```powershell
$py = "C:\Program Files\Microsoft SDKs\Azure\CLI2\python.exe"
$s = Read-Host "URL pooler de Neon (production)" -AsSecureString
$url = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
& $py -IBm azure.cli containerapp secret set --name beautymatch-api --resource-group rg-beautymatch `
    --secrets "database-url=$url" --only-show-errors -o none
Remove-Variable url, s
# los secretos se leen al arrancar: reiniciar la revisión activa
$revision = & $py -IBm azure.cli containerapp show --name beautymatch-api --resource-group rg-beautymatch `
    --query properties.latestRevisionName -o tsv
& $py -IBm azure.cli containerapp revision restart --name beautymatch-api --resource-group rg-beautymatch `
    --revision $revision -o none
```

### Actualizar la imagen

Cada cambio de la API: construir desde `main`, subir con la etiqueta del nuevo
commit y crear una revisión nueva:

```powershell
& $az containerapp update --name beautymatch-api --resource-group rg-beautymatch `
    --image "$acr.azurecr.io/beautymatch-api:$tag"
```

Ya no se puede así (CLI bloqueada): ver la sección siguiente.

## Procedimiento actual: portal + token del registro

Usado por primera vez el 2026-11-10 (imagen `3566a8f`). Sin `az`: el
registro se autentica con un **token** propio, solo para subir a
`beautymatch-api`, y la app se cambia en el portal. Reparto: el dueño de la
cuenta hace los clics y el `docker login`; quien despliega construye, sube y
verifica. Ninguna contraseña pasa por un chat.

```powershell
$docker = "C:\Users\lukas\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe"
$tag = "<sha corto de main>"    # una etiqueta por commit, nunca latest
```

### 1. Construir y probar la imagen (en el PC)

Desde un checkout limpio de `main` (`git status` vacío):

```powershell
& $docker build -t "beautymatch-api:$tag" .
& $docker tag "beautymatch-api:$tag" "bmapiregistry.azurecr.io/beautymatch-api:$tag"
```

El aviso `current commit information was not captured` (git no está en el
PATH) no afecta la imagen. Conviene probarla antes contra una base local
(`docker run -p 8001:8000 -e DATABASE_URL=postgresql://...@host.docker.internal:5432/<base> ...`)
y revisar `/healthz` en `ready`, `/products`, `/offers` y `/search/semantic`.

### 2. Crear el token en el portal (dueño de la cuenta)

1. Buscar `bmapiregistry` en la barra superior y abrir el *Container registry*.
2. **Permisos del repositorio → Mapas de ámbito** (*Repository permissions →
   Scope maps*). El mapa `push-beautymatch-api` ya existe (creado el
   2026-11-10): repositorio `beautymatch-api` con **content/write** y
   **content/read** (docker necesita leer para subir), nada más. Si no está,
   crearlo con **+ Agregar** con esos permisos.
3. **Tokens → + Agregar**: nombre `push-api`, mapa `push-beautymatch-api`,
   estado **Habilitado** → **Crear**.
4. Abrir el token → junto a **password1**, **Generar**; si deja, vencimiento
   al día siguiente. La contraseña se muestra **una sola vez**: copiarla con su
   botón y no pegarla en otro lado que el paso 3.

Si **Tokens** aparece deshabilitado o pide pasar el registro a Premium, parar:
no cambiar el plan (tiene costo).

### 3. `docker login` (dueño de la cuenta, en su propia terminal)

```powershell
& "C:\Users\lukas\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe" login bmapiregistry.azurecr.io -u push-api
```

Pegar la contraseña cuando pide `Password:` (no se ve al pegar) → debe decir
**Login Succeeded**. Docker la guarda en el almacén de credenciales de
Windows, así que el `docker push` del paso siguiente funciona sin volver a
escribirla.

### 4. Subir la imagen

```powershell
$env:PATH = "$(Split-Path $docker);$env:PATH"   # el ayudante de credenciales está junto a docker.exe
& $docker push "bmapiregistry.azurecr.io/beautymatch-api:$tag"
```

Unos minutos (3,9 GB; las capas que el registro ya tiene no se suben de
nuevo: el 2026-11-10 tardó 54 s). El `digest` que imprime debe ser el ID de la
imagen construida (`docker images --no-trunc`).

### 5. Cambiar la imagen de la app en el portal (dueño de la cuenta)

1. Buscar `beautymatch-api` y abrir la *Container App* (no el repositorio
   del registro).
2. **Aplicación → Contenedores** (*Application → Containers*) → **Editar e
   implementar** (*Edit and deploy*).
3. Marcar el contenedor (es el único) → **Editar** (*Edit*). En el panel:
   origen **Azure Container Registry**, registro `bmapiregistry.azurecr.io`,
   imagen `beautymatch-api`, **etiqueta = la nueva**. No tocar CPU, memoria,
   variables ni secretos → **Guardar**.
4. **Crear** (*Create*): crea una revisión nueva. En **Revisiones y réplicas**
   debe quedar *Running* (al principio *Provisioning*).

La app sigue bajando del registro con su identidad administrada
(`--registry-identity system`): el token es solo para subir.

### 6. Verificar en la URL pública

`https://beautymatch-api.happyrock-538a1151.brazilsouth.azurecontainerapps.io`.
El primer arranque con una imagen nueva puede pasar de 2 minutos.

- `/healthz`: `{"status": "ok", "semantic_model": "ready"}`.
- `/products?limit=1`: `total` > 0.
- `/products/{id}`: los campos nuevos de la versión (así se confirma que
  responde la imagen nueva y no la anterior).
- `/offers?limit=1` y `/search/semantic?q=perfume%20dulce%20de%20vainilla`.

### 7. Eliminar el token (dueño de la cuenta)

**Tokens** → `push-api` → **Eliminar** (el 2026-11-10 se eliminó; también
sirve **Deshabilitado**). El mapa de ámbito se deja para la próxima vez. La
credencial que guardó `docker login` deja de servir sola; si se quiere
borrar del PC: `docker logout bmapiregistry.azurecr.io`.

### El secreto de la base, desde el portal

Si hay que cambiar la URL de Neon (por ejemplo, tras rotar la contraseña):
*Container App* `beautymatch-api` → **Configuración → Secretos**
(*Settings → Secrets*) → `database-url` → **Editar** → pegar la URL
**pooler** de Neon → **Guardar**. Los secretos se leen al arrancar: luego
**Revisiones y réplicas** → la revisión activa → **Reiniciar** (*Restart*).
La URL se pega solo en el portal, nunca en un chat.

### La réplica del día de la presentación, desde el portal

*Container App* `beautymatch-api` → **Aplicación → Escalar** (*Application →
Scale*) → **Réplicas mínimas** = `1` → **Guardar** / **Crear** (crea una
revisión con la misma imagen). Unos 5 minutos antes, y comprobar `/healthz`
en `ready`. El mismo día, volver a **Réplicas mínimas** = `0` (ver costos en la
sección siguiente).

## Escalar a cero y el arranque en frío

La app queda con **0 réplicas mínimas** (decisión del 2026-11-01): sin tráfico
no consume nada; tras 5 a 7 minutos sin peticiones se apaga. Medido en Azure
(2026-10-30, paso 8), la primera petición después de apagada:

| | 1ª | 2ª | 3ª |
|---|---|---|---|
| `/healthz` responde | 23,5 s | 27,6 s | 41,8 s |
| modelo semántico listo (desde la 1ª petición) | — | 35,5 s | 50,5 s |

Ya despierta: `/products` 0,3 s, `/brands` 0,9 s, `/search/semantic` ~2 s.
El primer arranque después de subir una imagen nueva tarda más (pasó de 2
minutos): Azure baja la imagen completa. El frontend debería llamar a
`/healthz` al abrirse, para despertar la API, y mostrar "cargando" mientras
`/search/semantic` responda `503`.

Una réplica mínima siempre encendida no cabe en el cupo gratis (~2,6 millones
de vCPU-s al mes contra 180.000): se usa solo para una presentación.

### Día de la presentación: una réplica encendida

Con la CLI bloqueada, se hace desde el portal (ver "La réplica del día de la
presentación, desde el portal", más arriba). Los comandos quedan como
referencia.

Antes (unos 5 minutos antes, para que arranque y cargue el modelo):

```powershell
$py = "C:\Program Files\Microsoft SDKs\Azure\CLI2\python.exe"
& $py -IBm azure.cli containerapp update --name beautymatch-api --resource-group rg-beautymatch `
    --min-replicas 1 -o none
# comprobar: debe decir 1, y /healthz "ready"
& $py -IBm azure.cli containerapp show --name beautymatch-api --resource-group rg-beautymatch `
    --query properties.template.scale.minReplicas -o tsv
Invoke-RestMethod https://beautymatch-api.happyrock-538a1151.brazilsouth.azurecontainerapps.io/healthz
```

Después, **el mismo día**: cada hora encendida consume ~3.600 vCPU-s del cupo
gratis (y la memoria, ~7.200 GiB-s).

```powershell
& $py -IBm azure.cli containerapp update --name beautymatch-api --resource-group rg-beautymatch `
    --min-replicas 0 -o none
& $py -IBm azure.cli containerapp show --name beautymatch-api --resource-group rg-beautymatch `
    --query properties.template.scale.minReplicas -o tsv   # debe decir 0
```

`containerapp update` crea una revisión nueva con la misma imagen y el mismo
secreto; no cambia nada más.

## Costo esperado

- Container Apps: el cupo gratis mensual (180.000 vCPU-s, 360.000 GiB-s y 2
  millones de peticiones) cubre el uso esporádico con escala a cero.
- Registro Standard: gratis los primeros 12 meses con Azure for Students (un
  registro Standard, 100 GB). Después, o si el beneficio no se aplica, se
  descuenta del crédito (~US$20 al mes): revisar en el portal, *Cost
  Management*, la primera semana.
- Sin Log Analytics: sin costo de logs.
