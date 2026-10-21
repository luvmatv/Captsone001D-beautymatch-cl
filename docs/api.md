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
   foreach ($f in "001_initial_schema", "002_raw_listing_parsed_attributes", "003_stable_product_ids", "004_scrape_runs", "005_schema_migrations") {
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

- Varios orígenes: `API_CORS_ORIGINS=http://localhost:5173,https://beautymatch.example.cl`.
- Vacío: ningún navegador de otro origen puede llamarla (`curl`, el backend
  del chatbot o Postman funcionan igual: CORS solo lo aplica el navegador).
- Cada origen debe empezar con `http://` o `https://`; si no, la API no
  arranca y dice cuál está mal. `*` permite cualquier origen (útil para una
  demo; en producción, mejor listar los dominios).
- Solo se permite `GET`, sin cookies ni credenciales.

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
| `GET /products/{product_id}/variants` | Otros tamaños y presentaciones de la misma fragancia |
| `GET /brands` | Marcas con productos a la venta y cuántos, para los menús de filtros |
| `GET /offers` | Descuentos cuyo precio de lista respalda el historial, de mayor a menor en pesos |
| `GET /search/semantic` | Productos más parecidos en significado a una consulta en lenguaje natural (chatbot) |

### `GET /products`

Parámetros: `q` (búsqueda por texto, ver abajo), `brand` (marca exacta, sin
distinguir mayúsculas), los filtros y el orden de abajo, `limit` (1 a 100, por
defecto 20) y `offset` (por defecto 0).

**Filtros (opcionales, se combinan entre sí, con `q` y con `brand`):**

| Parámetro | Qué filtra |
|---|---|
| `min_price`, `max_price` | Rango sobre `lowest_price` (CLP). Con un filtro de precio quedan fuera los productos sin precio disponible |
| `concentration` | `edp`, `edt`, `parfum`, `cologne`, `eau_fraiche`, `other`. Se repite para aceptar varias: `concentration=edp&concentration=edt` |
| `min_volume`, `max_volume` | Rango de volumen en ml |
| `gender` | `male`, `female`, `unisex` (se repite). `unisex` incluye las fragancias cuyo género ninguna tienda informa |
| `store` | Disponible en esa tienda: `preunic`, `maicao`, `salcobrand`, `beautyperfumes` (se repite: en alguna de ellas) |

**Orden (`sort`):** `name` (por defecto sin `q`), `relevance` (por defecto con
`q`), `price_asc`, `price_desc`, `discount` (mayor descuento primero) o
`price_per_ml` (más barato por ml primero). Los productos sin ese dato van al
final y los empates se ordenan por nombre, así que las páginas no se repiten.

Un mínimo mayor que el máximo, una tienda desconocida o un valor fuera de la
lista responde `422`.

```
GET /products?gender=female&concentration=edp&max_price=30000&sort=price_asc
```

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
- `image_url`: imagen del producto, la de su oferta disponible más barata que
  tenga una (URL `https` de la tienda). `null` si ninguna publicación trae imagen:
  Maicao no la entrega, así que un producto que solo vende Maicao no tiene.

**Búsqueda (`q`, opcional):**

- Busca en el nombre del producto y en la marca. No distingue mayúsculas, acentos
  ni apóstrofos: `jazmin` encuentra «Jazmín» y `victorias` encuentra «Victoria's».
- Con varias palabras, deben estar todas, en cualquier orden. Cada palabra puede
  ser parte de una palabra: `blue sedu` encuentra «Blue Seduction».
- Se combina con `brand` y con la paginación. `total` cuenta solo los productos
  que coinciden.
- Orden: primero el producto cuyo nombre es exactamente la búsqueda, luego los que
  empiezan con ella (con o sin la marca delante: `asad` pone primero
  «Lattafa Asad …») y después el resto. Dentro de cada grupo, por nombre. El orden
  es el mismo en cada llamada, así que las páginas no se repiten ni se saltan.
- Sin `q` (o con `q` vacío), la lista es exactamente la de siempre.
- `%`, `_` y `\` se buscan como texto: `100%` no funciona como comodín.
- Hasta 100 caracteres y 10 palabras, sin caracteres de control; si no, `422`
  con el formato de error habitual (`string_too_long`, `string_pattern_mismatch`
  o `too_many_words`).

```
GET /products?q=blue%20seduction&brand=antonio%20banderas&limit=10
```

**Campos de cada producto en la lista**, además de los del ejemplo:

- `presentation`: `full_bottle`, `tester`, `travel_set`, `miniature` o `refill`.
- `price_per_ml`: `lowest_price` dividido por `volume_ml`, con un decimal. Es
  `null` en los sets, porque su precio incluye más que el frasco principal.
- `best_discount_percent`: el mayor descuento actual entre sus ofertas
  disponibles (lo que la tienda rebaja de su propio precio de lista). No dice si
  ese precio de lista es creíble: para eso está `list-price-checks`.
- `last_updated`: la lectura más reciente de sus precios actuales (UTC).

### `GET /brands`

```json
{ "items": [ { "brand": "Lattafa", "products": 168 } ], "total": 311 }
```

Cada marca con productos a la venta y cuántos, en orden alfabético. El nombre
es exactamente el que acepta el filtro `brand` de `GET /products`.

### `GET /products/{product_id}/variants`

Los otros productos de la misma fragancia que hoy se venden (misma marca,
nombre y género): otros tamaños, sets y testers. Cada uno con los mismos
campos que en la lista, ordenados por presentación y volumen. Una versión
distinta (Elixir, Intense) es otra fragancia y no aparece. Responde `404` si
el producto no existe y una lista vacía si no hay otros.

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
- `image_url` (en la ficha y en cada precio): la imagen del producto, elegida
  como en la lista, y la de cada publicación. `null` en Maicao.
- `last_updated` en la ficha y `price_per_ml` en cada precio: como en la lista.
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

### `GET /offers`

Las ofertas de hoy con descuento cuyo precio de lista está respaldado por el
historial: el precio tachado **no supera el precio más alto que esa misma
publicación cobró sin descuento y con stock** en los últimos `window_days`
días (`vs_history.status = consistent`, la misma regla de `list-price-checks`).
Ordenadas de mayor a menor descuento en pesos.

Parámetros: `store` (se repite), `brand` (exacta), `window_days` (1 a 365, por
defecto 30), `limit` y `offset`.

```json
{
  "items": [
    {
      "product_id": "6534b09e-a83c-4a52-812a-49280f82de79",
      "canonical_name": "Lattafa Asad EDP 100 ml",
      "brand": "Lattafa", "volume_ml": 100, "store": "preunic",
      "listing_url": "https://preunic.cl/products/perfume-hombre-lattafa-asad-edp-100-ml",
      "image_url": "https://static.preunic.cl/moqsejx9xvcr7vtmi0hpemv7mkry",
      "price": 25999, "list_price": 34999, "discount_amount": 9000, "discount_percent": 25.7,
      "scraped_at": "2026-10-20T12:00:36Z",
      "vs_history": { "status": "consistent", "reference_price": 34999, "...": "..." },
      "vs_market": { "status": "within_market", "reference_price": 32990, "...": "..." }
    }
  ],
  "total": 166, "limit": 20, "offset": 0, "window_days": 30, "currency": "CLP"
}
```

- Quedan fuera los descuentos que no tienen con qué compararse
  (`insufficient_data`: con poco historial son la mayoría, así que la lista
  crece a medida que se acumulan días) y los de precio de lista sobre su
  historial (`above_history`).
- `vs_market` va como contexto, igual que en `list-price-checks`.
- Se recalcula cuando una corrida diaria carga precios nuevos.

### `GET /search/semantic`

Para el chatbot: compara la consulta (`q`, obligatoria, hasta 200 caracteres)
con el embedding de cada fragancia, calculado con el mismo modelo multilingüe
a partir del nombre y la marca de sus publicaciones. Entiende sinónimos, otros
idiomas y nombres mal escritos, pero **solo sabe lo que dicen los nombres**: no
conoce notas olfativas ni descripciones.

Parámetros: `q`, `limit` (1 a 50, por defecto 10) y los mismos filtros de
`GET /products` (`min_price`, `max_price`, `concentration`, `min_volume`,
`max_volume`, `gender`, `store`). No pagina.

```json
{
  "query": "perfume árabe de vainilla",
  "items": [
    { "product_id": "6534b09e-...", "canonical_name": "Lattafa Asad EDP 100 ml", "...": "...",
      "similarity": 0.8731 }
  ]
}
```

- Cada ítem es un producto como los de `GET /products` más `similarity`
  (coseno, de -1 a 1; más alto es más parecido). Orden: `similarity`
  descendente, empates por nombre.
- Busca entre las 200 fragancias más parecidas y devuelve sus productos a la
  venta que pasan los filtros.
- El modelo (~1 GB de memoria) se carga en la primera búsqueda, sin internet:
  debe estar descargado (`python -m src.matching.embeddings --download-model`).
  Sin él, este endpoint responde `503` y el resto de la API funciona igual.

### Errores

| Código | Cuándo | Cuerpo |
|---|---|---|
| `308` | El `product_id` se retiró al unirse a otro (resultaron ser el mismo producto). `Location` lleva al ID vigente con la misma ruta y parámetros; `fetch` la sigue solo | `{"detail": "Product merged into another", "replaced_by": "<id vigente>"}` |
| `404` | El `product_id` no existe | `{"detail": "Product not found"}` |
| `410` | El `product_id` se retiró sin reemplazo | `{"detail": "Product retired", "replaced_by": null}` |
| `422` | Parámetro inválido (`product_id` que no es UUID, `limit` o `window_days` fuera de rango, `q` demasiado largo, con más de 10 palabras o con caracteres de control) | `{"detail": [ ...un objeto por problema... ]}` |
| `503` | La base de datos no responde, o (solo `/search/semantic`) el modelo de embeddings no está descargado | `{"detail": "Database unavailable"}` o `{"detail": "Semantic search unavailable: ..."}` |

## 6. Notas para el frontend

- **Precios:** enteros en pesos chilenos. Para mostrarlos:
  `new Intl.NumberFormat("es-CL", { style: "currency", currency: "CLP" }).format(25999)` → `$25.999`.
- **Fechas:** UTC en ISO 8601; `new Date(scraped_at)` las convierte a la hora local.
- **IDs:** `product_id` es estable aunque se actualice el catálogo, así que se puede
  usar en rutas del frontend (`/producto/:id`). Un id sigue a las publicaciones
  del producto, aunque cambie su nombre. Si dos productos resultan ser el
  mismo, se conserva uno y el otro id responde `308` hacia el vigente (siguiendo
  la cadena si hubo varias uniones): conviene reemplazar el id guardado por
  `replaced_by`. Un id retirado sin reemplazo responde `410`.
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
