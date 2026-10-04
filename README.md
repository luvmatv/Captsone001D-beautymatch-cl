# BeautyMatch CL

**Comparador de precios de perfumería en tiendas chilenas.**

Proyecto Capstone — Ingeniería en Informática, Duoc UC.

## Descripción

El mismo perfume se publica con nombres, formatos y descripciones distintas en
cada tienda online ("Blue Seduction Man EDT 200 mL", "ANTONIO BANDERAS BLUE
SEDUCTION FOR MEN 200ML EDT (H)"...), lo que impide comparar precios de forma
confiable. BeautyMatch CL extrae los catálogos de perfumería de varias tiendas,
reconoce cuáles publicaciones son el mismo producto (misma fragancia,
concentración, volumen y presentación) y guarda el historial de precios de cada
una, para mostrar dónde conviene comprar.

## Alcance

El proyecto se dedica a la **perfumería**: perfumes, colonias, body mists,
splashes y estuches. Es una categoría con atributos estructurados (marca,
concentración, volumen) que permiten decidir con precisión si dos
publicaciones son el mismo producto.

**Incluido**
- Extracción automatizada de los catálogos de perfumería de 6 tiendas chilenas
  (objetivo). Hoy hay 4 activas: Preunic, Maicao, Salcobrand y Beauty Perfumes
- Normalización y emparejamiento de productos equivalentes entre tiendas
- Historial de precios de cada publicación (implementado)
- Verificación de precios de lista contra el historial de cada publicación y
  entre tiendas (implementada). Solo da resultados cuando hay historial
  suficiente; mientras tanto responde "sin datos suficientes"
- Comparador web con ficha de producto consolidada

**Fuera del alcance**
- Compra o checkout dentro de la plataforma
- Aplicación móvil nativa
- Verificación de autenticidad del producto
- Otras categorías de belleza (maquillaje, skincare)

## Arquitectura

- **Scraping:** Python + Playwright (Beauty Perfumes, sin navegador: lee el catálogo JSON de Shopify)
- **Normalización:** embeddings + reglas de negocio (marca, volumen, concentración, género, presentación)
- **Base de datos:** PostgreSQL + pgvector
- **API:** FastAPI
- **Frontend:** React

## Tiendas

| Tienda | Scraper | Notas |
|---|---|---|
| Preunic | `python -m src.cli` | categoría "Perfumes y Fragancias" |
| Maicao | `python -m src.maicao_cli` | |
| Salcobrand | `python -m src.salcobrand_cli` | |
| Beauty Perfumes | `python -m src.beautyperfumes_cli` | sin testers, decants ni productos que no son perfume |
| dperfumes | `python -m src.dperfumes_cli` | API de WooCommerce; aún fuera del matching y de la corrida diaria |

Cada scraper deja un JSON en `artifacts/raw/` (ignorado por Git). Los
problemas conocidos de los datos de cada tienda están en
[docs/known_data_issues.md](docs/known_data_issues.md).

## Puesta en marcha

Requisitos: Python 3.11 o superior y Docker Desktop.

```powershell
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m playwright install chromium
```

### Base de datos (Docker)

PostgreSQL 17 con pgvector, en un contenedor llamado `bm-pg`. Solo la primera vez:

```powershell
docker run -d --name bm-pg -e POSTGRES_PASSWORD=dev -p 5432:5432 -v bm-pg-data:/var/lib/postgresql/data pgvector/pgvector:pg17
docker exec bm-pg createdb -U postgres beautymatch
foreach ($f in "001_initial_schema", "002_raw_listing_parsed_attributes", "003_stable_product_ids", "004_scrape_runs") {
    docker cp "database/$f.sql" "bm-pg:/tmp/$f.sql"
    docker exec bm-pg psql -U postgres -d beautymatch -v ON_ERROR_STOP=1 -f "/tmp/$f.sql"
}
```

Las veces siguientes basta con `docker start bm-pg`. Los scripts se conectan a
`postgresql://postgres:dev@localhost:5432/beautymatch`; para otra base, define
`DATABASE_URL`. Para restaurar o generar un respaldo (`beautymatch.dump`), ver
[docs/api.md](docs/api.md) y [docs/daily_run.md](docs/daily_run.md).

### Cargar datos y emparejar

```powershell
python -m src.loader.raw_listings        # carga el último JSON completo de cada tienda
python -m src.matching.embeddings        # la primera vez descarga el modelo (~1 GB)
python -m src.matching.pipeline          # crea/actualiza productos; --dry-run muestra el plan sin escribir
```

### Corrida diaria

`python -m src.daily_run` hace todo en un solo comando: scrapea las cuatro
tiendas, carga los precios, calcula los embeddings nuevos y empareja. Cada
corrida queda registrada en la base y en `artifacts/runs/summary.log`. Cómo
programarla en el Programador de tareas de Windows, qué hacer si falla y cómo
respaldar la base: [docs/daily_run.md](docs/daily_run.md).

### API

```powershell
copy .env.example .env      # completar PGPASSWORD
uvicorn src.api.main:app --env-file .env --reload
```

Documentación interactiva en http://127.0.0.1:8000/docs. Guía para el
frontend (endpoints, CORS, errores): [docs/api.md](docs/api.md).

## Matching

Para cada publicación, los embeddings (modelo `intfloat/multilingual-e5-base`)
buscan candidatas parecidas de la misma marca en las otras tiendas. La
similitud solo ordena: deciden reglas de negocio explícitas, que vetan los
pares con distinto volumen, concentración, género, presentación (set o frasco)
o nombre de fragancia, y aceptan solo los que coinciden en todo. Lo dudoso va a
revisión.

La prioridad es la precisión: unir dos productos distintos es peor que perder
un match. Cada regla se mide contra las etiquetas humanas antes de aplicarse,
y la precisión de los matches automáticos se registra en
[docs/matching_evaluation.md](docs/matching_evaluation.md)
(`python -m src.matching.evaluate`).

### Revisión manual

Los pares dudosos se exportan a `artifacts/review/review_queue_<fecha>.csv`.
Una persona los etiqueta (`same`, `different` o `same_fragrance_unknown_size`)
y los guarda en `data/labeled/`. El pipeline lee esas etiquetas en cada
corrida: un par etiquetado `same` se acepta como match y uno `different` se
veta, aunque las reglas digan otra cosa.

## Tests

```powershell
python -m pytest
```

Los tests de base de datos usan una base aparte, `beautymatch_test`, en el
mismo servidor (ver [docs/api.md](docs/api.md)); nunca tocan `beautymatch`.

## Metodología

Desarrollo bajo Scrum, sprints de 2 semanas.
