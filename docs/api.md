# API de BeautyMatch CL

Guía para levantar el backend en local y usar la API desde el frontend.
La referencia completa (campos, tipos, ejemplos) está en **http://127.0.0.1:8000/docs**
con la API corriendo.

## 1. Requisitos

- Python 3.11 o superior
- Docker Desktop

```powershell
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 2. Base de datos (Docker)

PostgreSQL 17 con pgvector, en un contenedor llamado `bm-pg`. Solo la primera vez:

```powershell
docker run -d --name bm-pg -e POSTGRES_PASSWORD=dev -p 5432:5432 -v bm-pg-data:/var/lib/postgresql/data pgvector/pgvector:pg17
docker exec bm-pg createdb -U postgres beautymatch
```

Las veces siguientes basta con `docker start bm-pg` (o iniciarlo desde Docker Desktop).

## 3. Cargar datos

### Opción A: restaurar un respaldo (recomendada para el frontend)

Es lo más rápido: pide el archivo `beautymatch.dump` a quien mantiene la base.
El respaldo trae el esquema y los datos, así que no hace falta aplicar migraciones.

```powershell
docker cp beautymatch.dump bm-pg:/tmp/beautymatch.dump
docker exec bm-pg pg_restore -U postgres -d beautymatch --clean --if-exists --no-owner /tmp/beautymatch.dump
```

Para generar el respaldo desde una base que ya tiene datos:

```powershell
docker exec bm-pg pg_dump -U postgres -Fc -d beautymatch -f /tmp/beautymatch.dump
docker cp bm-pg:/tmp/beautymatch.dump beautymatch.dump
```

### Opción B: construir los datos desde cero

1. Aplicar las migraciones, en orden. Se copian al contenedor porque pasarlas
   por un pipe de PowerShell daña los acentos de los comentarios:

   ```powershell
   foreach ($f in "001_initial_schema", "002_raw_listing_parsed_attributes", "003_stable_product_ids", "004_scrape_runs") {
       docker cp "database/$f.sql" "bm-pg:/tmp/$f.sql"
       docker exec bm-pg psql -U postgres -d beautymatch -v ON_ERROR_STOP=1 -f "/tmp/$f.sql"
   }
   ```

2. Correr los scrapers. Recorren el catálogo de cada tienda con un navegador,
   así que tardan. Dejan un JSON en `artifacts/raw/`:

   ```powershell
   python -m playwright install chromium   # solo la primera vez
   python -m src.cli                        # Preunic
   python -m src.maicao_cli                 # Maicao
   ```

3. Cargar, calcular embeddings y emparejar productos:

   ```powershell
   python -m src.loader.raw_listings        # último JSON completo de cada tienda
   python -m src.matching.embeddings        # la primera vez descarga el modelo (~1 GB)
   python -m src.matching.pipeline          # crea/actualiza productos y precios comparables
   ```

Estos scripts se conectan a `postgresql://postgres:dev@localhost:5432/beautymatch`.
Si tu base es otra, define la variable `DATABASE_URL` con esa dirección.

## 4. Correr la API

```powershell
copy .env.example .env      # macOS/Linux: cp .env.example .env
```

En `.env`, completar `PGPASSWORD=dev` (o la contraseña de tu contenedor). Luego:

```powershell
uvicorn src.api.main:app --env-file .env --reload
```

- API: http://127.0.0.1:8000
- Documentación interactiva: http://127.0.0.1:8000/docs

**CORS:** `API_CORS_ORIGINS` en `.env` lista los orígenes del navegador que
pueden llamar a la API, separados por comas. Viene con `http://localhost:5173`
(Vite). Si el frontend corre en otro puerto, agrégalo tal como aparece en la
barra del navegador (sin `/` al final) y reinicia la API.

Si la base no está levantada, la API arranca igual y responde `503` hasta que
vuelva.

## 5. Endpoints

Todos son `GET` y devuelven JSON.

| Endpoint | Para qué |
|---|---|
| `GET /products` | Lista paginada del catálogo, con el precio más bajo de cada producto |
| `GET /products/{product_id}` | Ficha de un producto y el precio actual en cada tienda |
| `GET /products/{product_id}/price-history` | Historial de precios, para graficar |
| `GET /products/{product_id}/list-price-checks` | Precio de lista de cada publicación contra su historial y contra otras tiendas |

### `GET /products`

Parámetros: `brand` (marca exacta, sin distinguir mayúsculas), `limit` (1 a
100, por defecto 20) y `offset` (por defecto 0).

```json
{
  "items": [
    {
      "product_id": "6534b09e-a83c-4a52-812a-49280f82de79",
      "canonical_name": "Lattafa Asad EDP 100 ml",
      "brand": "Lattafa",
      "concentration": "edp",
      "volume_ml": 100,
      "lowest_price": 25999,
      "lowest_price_store": "preunic"
    }
  ],
  "total": 7,
  "limit": 1,
  "offset": 0
}
```

- Solo incluye productos que hoy se venden en alguna tienda, ordenados por nombre.
- Hay más páginas mientras `offset + limit < total`.
- `lowest_price` y `lowest_price_store` son `null` si ninguna tienda lo tiene disponible.
- `concentration` puede ser `null` (la tienda no la informa, típico en body mists).

### `GET /products/{product_id}`

```json
{
  "product_id": "6534b09e-a83c-4a52-812a-49280f82de79",
  "canonical_name": "Lattafa Asad EDP 100 ml",
  "brand": "Lattafa",
  "concentration": "edp",
  "volume_ml": 100,
  "presentation": "full_bottle",
  "currency": "CLP",
  "prices": [
    {
      "store": "preunic",
      "price": 25999,
      "list_price": 34999,
      "is_available": true,
      "listing_url": "https://preunic.cl/products/perfume-hombre-lattafa-asad-edp-100-ml",
      "scraped_at": "2026-09-25T22:43:19.504174Z"
    },
    {
      "store": "maicao",
      "price": 35999,
      "list_price": 39999,
      "is_available": true,
      "listing_url": "https://www.maicao.cl/asad-medp-sp100m/CLMC_589473.html",
      "scraped_at": "2026-09-25T12:22:36.734262Z"
    }
  ]
}
```

- `prices` tiene una entrada por publicación, de la más barata a la más cara.
  Una tienda puede aparecer dos veces si publicó el producto dos veces.
- `list_price` es el precio tachado; `null` si no hay descuento.
- `prices` puede venir vacío: el producto existe pero hoy nadie lo publica.
- `presentation`: `full_bottle`, `tester`, `travel_set`, `miniature` o `refill`.

### `GET /products/{product_id}/price-history`

```json
{
  "product_id": "6534b09e-a83c-4a52-812a-49280f82de79",
  "canonical_name": "Lattafa Asad EDP 100 ml",
  "currency": "CLP",
  "series": [
    {
      "store": "maicao",
      "listing_url": "https://www.maicao.cl/asad-medp-sp100m/CLMC_589473.html",
      "points": [
        { "scraped_at": "2026-09-25T12:14:16.534369Z", "price": 35999, "list_price": 39999, "is_available": true },
        { "scraped_at": "2026-09-25T12:22:36.734262Z", "price": 35999, "list_price": 39999, "is_available": true }
      ]
    },
    {
      "store": "preunic",
      "listing_url": "https://preunic.cl/products/perfume-hombre-lattafa-asad-edp-100-ml",
      "points": [
        { "scraped_at": "2026-09-25T12:28:16.757206Z", "price": 25999, "list_price": 34999, "is_available": true },
        { "scraped_at": "2026-09-25T22:43:19.504174Z", "price": 25999, "list_price": 34999, "is_available": true }
      ]
    }
  ]
}
```

- Cada serie es una línea del gráfico: eje X `scraped_at`, eje Y `price`.
  Los puntos vienen del más antiguo al más reciente.
- Normalmente hay una serie por tienda, pero puede haber dos de la misma
  tienda (dos publicaciones): usar `listing_url` como clave, no `store`.
- Hoy hay pocas lecturas por publicación; el historial crece con cada scrape.

### `GET /products/{product_id}/list-price-checks`

Revisa el precio de lista (el precio "normal" tachado) de cada publicación
actual. Parámetro: `window_days`, los días de historial que se revisan antes
de la lectura actual (1 a 365, por defecto 30).

```json
{
  "product_id": "6534b09e-a83c-4a52-812a-49280f82de79",
  "canonical_name": "Lattafa Eclaire EDP 100 ml",
  "currency": "CLP",
  "window_days": 30,
  "checks": [
    {
      "store": "beautyperfumes",
      "listing_url": "https://beautyperfumes.cl/products/lattafa-eclaire-edp-100ml-mujer",
      "price": 29900,
      "list_price": 69990,
      "is_available": true,
      "scraped_at": "2026-10-04T00:03:11Z",
      "vs_history": {
        "status": "insufficient_data",
        "reference_price": null,
        "reference_scraped_at": null,
        "observed_from": "2026-10-02T18:17:14Z",
        "points_in_window": 2,
        "undiscounted_points": 0
      },
      "vs_market": {
        "status": "above_market",
        "reference_price": 39999,
        "reference_stores": ["salcobrand"],
        "percent_above": 75.0
      }
    }
  ]
}
```

- `checks` tiene una entrada por publicación, en el mismo orden que `prices`
  de la ficha.
- **`vs_history`: precio de lista contra el historial de la misma publicación.**
  - `no_list_price`: hoy no muestra precio de lista.
  - `insufficient_data`: en la ventana no hay ninguna lectura sin descuento y
    con stock, así que no hay con qué comparar. **No significa que el precio
    esté bien.** Con poco historial, la mayoría de los descuentos sale así.
  - `consistent`: el precio de lista no supera el precio más alto que la
    publicación cobró sin descuento en la ventana (`reference_price`).
  - `above_history`: precio de lista inconsistente con el historial: lo
    supera.
  - Las lecturas sin stock no cuentan como referencia: ese precio no se podía
    pagar.
- **`vs_market`: precio de lista contra otras tiendas. Es un dato de
  contexto, no una alerta.** Los precios normales varían entre tiendas y la
  comparación depende de que el emparejamiento sea correcto.
  - `reference_price` es la mediana, entre las otras tiendas, de su precio sin
    descuento y disponible (cada tienda cuenta una vez, con el más bajo).
  - `within_market` / `above_market`: el precio de lista supera esa referencia
    en hasta 20 % / en más de 20 % (`percent_above`).
  - `insufficient_data`: ninguna otra tienda lo vende disponible y sin
    descuento.
- Ninguna de las dos verificaciones afirma intención: dicen lo que muestran
  las lecturas guardadas.

### Errores

| Código | Cuándo | Cuerpo |
|---|---|---|
| `404` | El `product_id` no existe | `{"detail": "Product not found"}` |
| `422` | Parámetro inválido (`product_id` que no es UUID, `limit` o `window_days` fuera de rango) | `{"detail": [ ...un objeto por problema... ]}` |
| `503` | La base de datos no responde | `{"detail": "Database unavailable"}` |

## 6. Notas para el frontend

- **Precios:** enteros en pesos chilenos. Para mostrarlos:
  `new Intl.NumberFormat("es-CL", { style: "currency", currency: "CLP" }).format(25999)` → `$25.999`.
- **Fechas:** UTC en ISO 8601; `new Date(scraped_at)` las convierte a la hora local.
- **IDs:** `product_id` es estable aunque se actualice el catálogo, así que se puede
  usar en rutas del frontend (`/producto/:id`).
- **Nombres:** algunos productos que solo vende Maicao tienen nombres abreviados
  por la tienda (p. ej. "Lattafa Asad Deso.Sp200M 200 ml"). Es un problema
  conocido de los datos; ver [known_data_issues.md](known_data_issues.md).

## 7. Tests

```powershell
python -m pytest
```

Los tests de base de datos no tocan `beautymatch`: crean su propia base,
`beautymatch_test`, en el mismo servidor. Le aplican las migraciones de
`database/`, le copian el catálogo de `beautymatch` (solo lectura) y la borran
al terminar. Si `bm-pg` no está corriendo, esos tests se saltan solos.
