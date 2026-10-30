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

### Comandos

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
& $az acr login --name $acr --expose-token --query accessToken -o tsv |
    & $docker login "$acr.azurecr.io" --username 00000000-0000-0000-0000-000000000000 --password-stdin
& $docker push "$acr.azurecr.io/beautymatch-api:$tag"

# 4. Entorno y app. La app se crea con una URL provisoria: arranca, y los
#    endpoints que leen la base responden 503 hasta cargar la real (paso 5).
& $az containerapp env create --name cae-beautymatch --resource-group rg-beautymatch `
    --location brazilsouth --logs-destination none
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

```powershell
$az = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
$url = Read-Host "URL pooler de Neon"   # se pega ahí; no queda en el historial de comandos
& $az containerapp secret set --name beautymatch-api --resource-group rg-beautymatch `
    --secrets "database-url=$url"
# los secretos se leen al arrancar: reiniciar la revisión activa
$revision = & $az containerapp show --name beautymatch-api --resource-group rg-beautymatch `
    --query properties.latestRevisionName -o tsv
& $az containerapp revision restart --name beautymatch-api --resource-group rg-beautymatch --revision $revision
```

### Actualizar la imagen

Cada cambio de la API: construir desde `main`, subir con la etiqueta del nuevo
commit y crear una revisión nueva:

```powershell
& $az containerapp update --name beautymatch-api --resource-group rg-beautymatch `
    --image "$acr.azurecr.io/beautymatch-api:$tag"
```

## Escalar a cero y el arranque en frío

La app parte con **0 réplicas mínimas**: sin tráfico no consume nada; tras ~5
minutos sin peticiones se apaga. La primera petición después espera que
Azure baje la imagen y la arranque, más la carga del modelo para la búsqueda
semántica. Ese tiempo se mide en Azure (paso 8) antes de decidir si conviene
una réplica mínima en horario de uso.

## Costo esperado

- Container Apps: el cupo gratis mensual (180.000 vCPU-s, 360.000 GiB-s y 2
  millones de peticiones) cubre el uso esporádico con escala a cero.
- Registro Standard: gratis los primeros 12 meses con Azure for Students (un
  registro Standard, 100 GB). Después, o si el beneficio no se aplica, se
  descuenta del crédito (~US$20 al mes): revisar en el portal, *Cost
  Management*, la primera semana.
- Sin Log Analytics: sin costo de logs.
