from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.api.db import get_product_repository
from src.api.repositories.products import ProductFilters, ProductRepository, Sort
from src.api.schemas import (
    EXAMPLE_ID,
    BrandList,
    Concentration,
    ErrorResponse,
    Gender,
    ListPriceChecks,
    OfferPage,
    PriceHistory,
    ProductDetail,
    ProductPage,
    RetiredResponse,
    SemanticMatch,
    SemanticPage,
    VariantList,
)
from src.api.semantic import Embedder, SemanticSearchUnavailable, get_embedder
from src.matching.pipeline import MATCHING_STORES as STORES
from src.pricing.list_price_checks import DEFAULT_WINDOW_DAYS

# Example bodies for /docs, taken from real responses (Lattafa Asad EDP 100 ml;
# the list, detail, variants, brands, offers and semantic search of 2026-10-20).
PREUNIC_URL = "https://preunic.cl/products/perfume-hombre-lattafa-asad-edp-100-ml"
MAICAO_URL = "https://www.maicao.cl/asad-medp-sp100m/CLMC_589473.html"
ASAD_BEAUTYPERFUMES_URL = "https://beautyperfumes.cl/products/lattafa-asad-100ml-edp-unisex-asad100u"
ASAD_IMAGE = "https://cdn.shopify.com/s/files/1/0709/3292/2608/files/s-pdpxl.webp?v=1721684953"
ASAD_SUMMARY = {
    "product_id": EXAMPLE_ID, "canonical_name": "Lattafa Asad EDP 100 ml", "brand": "Lattafa",
    "concentration": "edp", "volume_ml": 100, "presentation": "full_bottle", "lowest_price": 22900,
    "lowest_price_store": "beautyperfumes", "image_url": ASAD_IMAGE, "price_per_ml": 229.0,
    "best_discount_percent": 42.7, "last_updated": "2026-10-20T12:13:07.949147Z",
}
LIST_EXAMPLE = {"items": [ASAD_SUMMARY], "total": 6, "limit": 1, "offset": 0}
DETAIL_EXAMPLE = {
    **{key: ASAD_SUMMARY[key] for key in ("product_id", "canonical_name", "brand", "concentration", "volume_ml",
                                          "presentation", "image_url", "last_updated")},
    "currency": "CLP",
    "prices": [
        {"store": "beautyperfumes", "price": 22900, "list_price": 39990, "is_available": True,
         "listing_url": ASAD_BEAUTYPERFUMES_URL, "scraped_at": "2026-10-20T12:13:07.949147Z",
         "image_url": ASAD_IMAGE, "price_per_ml": 229.0},
        {"store": "maicao", "price": 27999, "list_price": 39999, "is_available": True,
         "listing_url": MAICAO_URL, "scraped_at": "2026-10-20T12:04:35.903788Z",
         "image_url": None, "price_per_ml": 280.0},
    ],
}
# Shakira Rojo: the same fragrance in 30, 50 and 80 ml (the 80 ml is listed but out of stock).
VARIANTS_EXAMPLE = {
    "product_id": "74fdf315-4243-4b54-a7c4-f33c92448054", "canonical_name": "Shakira Rojo EDP 50 ml",
    "items": [
        {"product_id": "161aff1a-a06e-4719-b1d8-9069c60f5fb3", "canonical_name": "Shakira Rojo EDP 30 ml",
         "brand": "Shakira", "concentration": "edp", "volume_ml": 30, "presentation": "full_bottle",
         "lowest_price": 7999, "lowest_price_store": "maicao", "image_url": None, "price_per_ml": 266.6,
         "best_discount_percent": None, "last_updated": "2026-10-20T12:04:35.903788Z"},
        {"product_id": "80059f82-78f5-43f1-8305-a0bdcf0a5c38", "canonical_name": "Shakira Rojo EDP 80 ml",
         "brand": "Shakira", "concentration": "edp", "volume_ml": 80, "presentation": "full_bottle",
         "lowest_price": None, "lowest_price_store": None,
         "image_url": "https://cdn.shopify.com/s/files/1/0709/3292/2608/files/"
                      "6_75403cc7-48de-42e7-acdd-cfb3f5c3c4ee.png?v=1780587665",
         "price_per_ml": None, "best_discount_percent": None, "last_updated": "2026-10-20T12:13:07.949147Z"},
    ],
}
BRANDS_EXAMPLE = {"items": [{"brand": "451", "products": 3}, {"brand": "4711", "products": 2},
                            {"brand": "Lattafa", "products": 151}], "total": 218}
OFFERS_EXAMPLE = {
    "items": [{
        "product_id": EXAMPLE_ID, "canonical_name": "Lattafa Asad EDP 100 ml", "brand": "Lattafa", "volume_ml": 100,
        "store": "maicao", "listing_url": MAICAO_URL, "image_url": None,
        "price": 27999, "list_price": 39999, "discount_amount": 12000, "discount_percent": 30.0,
        "scraped_at": "2026-10-20T12:04:35.903788Z",
        "vs_history": {"status": "consistent", "reference_price": 39999,
                       "reference_scraped_at": "2026-09-28T13:13:54.994049Z",
                       "observed_from": "2026-09-25T12:14:16.534369Z", "points_in_window": 31,
                       "undiscounted_points": 3},
        "vs_market": {"status": "insufficient_data", "reference_price": None, "reference_stores": [],
                      "percent_above": None},
    }],
    "total": 3, "limit": 1, "offset": 0, "window_days": 30, "currency": "CLP",
}
SEMANTIC_EXAMPLE = {
    "query": "asad lattafa",
    "items": [
        {**ASAD_SUMMARY, "similarity": 0.9008},
        {"product_id": "827152aa-37f7-4109-9413-2c55e7cdb09c", "canonical_name": "Lattafa Asad Bourbon EDP 100 ml",
         "brand": "Lattafa", "concentration": "edp", "volume_ml": 100, "presentation": "full_bottle",
         "lowest_price": 29900, "lowest_price_store": "beautyperfumes",
         "image_url": "https://cdn.shopify.com/s/files/1/0709/3292/2608/files/1500_4.jpg?v=1739452185",
         "price_per_ml": 299.0, "best_discount_percent": 46.6, "last_updated": "2026-10-20T12:13:07.949147Z",
         "similarity": 0.8908},
    ],
}
HISTORY_EXAMPLE = {
    "product_id": EXAMPLE_ID, "canonical_name": "Lattafa Asad EDP 100 ml", "currency": "CLP",
    "series": [
        {"store": "maicao", "listing_url": MAICAO_URL, "points": [
            {"scraped_at": "2026-09-25T12:14:16.534369Z", "price": 35999, "list_price": 39999, "is_available": True},
            {"scraped_at": "2026-09-25T12:22:36.734262Z", "price": 35999, "list_price": 39999, "is_available": True},
        ]},
        {"store": "preunic", "listing_url": PREUNIC_URL, "points": [
            {"scraped_at": "2026-09-25T12:28:16.757206Z", "price": 25999, "list_price": 34999, "is_available": True},
            {"scraped_at": "2026-09-25T22:43:19.504174Z", "price": 25999, "list_price": 34999, "is_available": True},
        ]},
    ],
}
# Lattafa Eclaire EDP 100 ml (real readings of 2026-10-04): Beauty Perfumes has
# had the discount since it was first read; Salcobrand sells it undiscounted.
BEAUTYPERFUMES_URL = "https://beautyperfumes.cl/products/lattafa-eclaire-edp-100ml-mujer"
SALCOBRAND_URL = "https://salcobrand.cl/products/lattafa-eclaire-edp-100ml?default_sku=593585"
NO_LIST_PRICE = {"reference_price": None, "reference_scraped_at": None}
CHECKS_EXAMPLE = {
    "product_id": EXAMPLE_ID, "canonical_name": "Lattafa Eclaire EDP 100 ml", "currency": "CLP", "window_days": 30,
    "checks": [
        {"store": "beautyperfumes", "listing_url": BEAUTYPERFUMES_URL, "price": 29900, "list_price": 69990,
         "is_available": True, "scraped_at": "2026-10-04T00:03:11Z",
         "vs_history": {"status": "insufficient_data", **NO_LIST_PRICE, "observed_from": "2026-10-02T18:17:14Z",
                        "points_in_window": 2, "undiscounted_points": 0},
         "vs_market": {"status": "above_market", "reference_price": 39999, "reference_stores": ["salcobrand"],
                       "percent_above": 75.0}},
        {"store": "salcobrand", "listing_url": SALCOBRAND_URL, "price": 39999, "list_price": None,
         "is_available": True, "scraped_at": "2026-10-02T12:10:59Z",
         "vs_history": {"status": "no_list_price", **NO_LIST_PRICE, "observed_from": "2026-09-28T15:26:49Z",
                        "points_in_window": 6, "undiscounted_points": 6},
         "vs_market": {"status": "no_list_price", "reference_price": None, "reference_stores": [],
                       "percent_above": None}},
    ],
}


def ok(example: dict) -> dict:
    return {200: {"content": {"application/json": {"example": example}}}}


MERGED_ID = "1f5cbb26-d386-4735-bcca-7ce85cd8609c"
NOT_FOUND = {
    404: {"model": ErrorResponse, "description": "No existe un producto con ese ID.",
          "content": {"application/json": {"example": {"detail": "Product not found"}}}},
    308: {"model": RetiredResponse,
          "description": "El producto se unió a otro (resultaron ser el mismo): `Location` y `replaced_by` dan el "
                         "ID vigente, con la misma ruta y parámetros. `fetch` y los navegadores siguen la "
                         "redirección solos; conviene guardar el ID nuevo.",
          "content": {"application/json": {"example": {"detail": "Product merged into another",
                                                         "replaced_by": MERGED_ID}}}},
    410: {"model": RetiredResponse,
          "description": "El producto existió pero se retiró sin un reemplazo (`replaced_by` es `null`).",
          "content": {"application/json": {"example": {"detail": "Product retired", "replaced_by": None}}}},
}


class ProductMoved(Exception):
    """A retired product ID that lives on as another product: answered 308 (see main.py)."""

    def __init__(self, replaced_by: UUID, location: str) -> None:
        super().__init__(location)
        self.replaced_by, self.location = replaced_by, location


class ProductGone(Exception):
    """A retired product ID without a replacement: answered 410."""


def moved_response(request: Request, error: ProductMoved) -> JSONResponse:
    return JSONResponse(status_code=308, headers={"Location": error.location},
                        content={"detail": "Product merged into another", "replaced_by": str(error.replaced_by)})


def gone_response(request: Request, error: ProductGone) -> JSONResponse:
    return JSONResponse(status_code=410, content={"detail": "Product retired", "replaced_by": None})


def missing_product(product_id: UUID, repository: ProductRepository, request: Request, suffix: str = "") -> HTTPException:
    """For a product that is not in the catalog: 308 to its replacement, 410 if retired without one, else 404."""
    retired, replaced_by = repository.get_retirement(product_id)
    if replaced_by is not None:
        query = f"?{request.url.query}" if request.url.query else ""
        raise ProductMoved(replaced_by, f"/products/{replaced_by}{suffix}{query}")
    if retired:
        raise ProductGone()
    return HTTPException(status_code=404, detail="Product not found")


UNAVAILABLE = {503: {"model": ErrorResponse, "description": "La base de datos no responde; reintentar más tarde.",
                     "content": {"application/json": {"example": {"detail": "Database unavailable"}}}}}
# Replaces FastAPI's English "Validation Error" (same body); /brands has no parameters.
INVALID = {422: {"description": "Parámetro inválido. `detail` trae un objeto por problema: el parámetro en `loc`, "
                                "el motivo en `msg` (en inglés) y el valor recibido en `input`.",
                 "content": {"application/json": {"example": {"detail": [{
                     "type": "greater_than_equal", "loc": ["query", "limit"],
                     "msg": "Input should be greater than or equal to 1", "input": "0", "ctx": {"ge": 1}}]}}}}}

router = APIRouter(prefix="/products", tags=["products"], responses={**UNAVAILABLE, **INVALID})
brands_router = APIRouter(prefix="/brands", tags=["brands"], responses=UNAVAILABLE)
offers_router = APIRouter(prefix="/offers", tags=["offers"], responses={**UNAVAILABLE, **INVALID})
search_router = APIRouter(prefix="/search", tags=["search"], responses={**UNAVAILABLE, **INVALID})

Repository = Annotated[ProductRepository, Depends(get_product_repository)]

SEARCH_MAX_LENGTH = 100
SEARCH_MAX_WORDS = 10
# No control characters (a NUL cannot even reach PostgreSQL); everything else is
# searched literally: LIKE's % and _ are escaped by the repository.
SEARCH_PATTERN = r"^[^\x00-\x1f\x7f]*$"
ProductId = Annotated[UUID, Path(description="ID del producto (UUID), tal como viene en `GET /products`.",
                                 examples=[EXAMPLE_ID])]


def product_filters(
    min_price: Annotated[int | None, Query(
        ge=0, description="Precio mínimo en CLP, sobre el precio más bajo disponible (`lowest_price`). "
                          "Con un filtro de precio, los productos sin precio disponible quedan fuera.",
        examples=[10000])] = None,
    max_price: Annotated[int | None, Query(ge=0, description="Precio máximo en CLP (ver `min_price`).",
                                           examples=[30000])] = None,
    concentration: Annotated[list[Concentration] | None, Query(
        description="Concentración. Se puede repetir para aceptar varias: `concentration=edp&concentration=edt`.",
        examples=[["edp"]])] = None,
    min_volume: Annotated[int | None, Query(ge=1, description="Volumen mínimo en ml.", examples=[50])] = None,
    max_volume: Annotated[int | None, Query(ge=1, description="Volumen máximo en ml.", examples=[100])] = None,
    gender: Annotated[list[Gender] | None, Query(
        description="Género de la fragancia: `male`, `female` o `unisex`. Se puede repetir. `unisex` incluye "
                    "las fragancias cuyo género ninguna tienda informa.", examples=[["female"]])] = None,
    store: Annotated[list[str] | None, Query(
        description=f"Solo productos disponibles en esta tienda ({', '.join(sorted(STORES))}). Se puede "
                    "repetir: disponible en alguna de ellas.", examples=[["preunic"]])] = None,
) -> ProductFilters:
    """The filters shared by GET /products and GET /search/semantic, validated (422 like any parameter)."""
    problems = [
        {"type": "range", "loc": ("query", low), "input": low_value,
         "msg": f"{low} ({low_value}) is greater than {high} ({high_value})"}
        for low, low_value, high, high_value in (("min_price", min_price, "max_price", max_price),
                                                 ("min_volume", min_volume, "max_volume", max_volume))
        if low_value is not None and high_value is not None and low_value > high_value
    ]
    unknown = sorted(set(store or ()) - set(STORES))
    if unknown:
        problems.append({"type": "enum", "loc": ("query", "store"), "input": unknown,
                         "msg": f"Unknown store: {', '.join(unknown)}. Known: {', '.join(sorted(STORES))}"})
    if problems:
        raise RequestValidationError(problems)
    return ProductFilters(
        min_price=min_price, max_price=max_price, concentrations=tuple(c.value for c in concentration or ()),
        min_volume=min_volume, max_volume=max_volume, genders=tuple(g.value for g in gender or ()),
        stores=tuple(sorted(set(store or ()))))


Filters = Annotated[ProductFilters, Depends(product_filters)]


@router.get(
    "",
    summary="Listar productos",
    response_description="Una página de productos con su precio más bajo.",
    responses=ok(LIST_EXAMPLE),
)
def list_products(
    repository: Repository,
    filters: Filters,
    brand: Annotated[str | None, Query(
        description="Filtra por marca exacta, sin distinguir mayúsculas (`lattafa` = `Lattafa`). "
                    "Sin valor o vacío: todas las marcas.",
        examples=["Lattafa"],
    )] = None,
    q: Annotated[str | None, Query(
        max_length=SEARCH_MAX_LENGTH, pattern=SEARCH_PATTERN,
        description=f"Busca en el nombre y la marca del producto, sin distinguir mayúsculas ni acentos "
                    f"(`jazmin` = `Jazmín`). Con varias palabras, deben estar todas, en cualquier orden. "
                    f"Se combina con `brand` y la paginación. Hasta {SEARCH_MAX_LENGTH} caracteres y "
                    f"{SEARCH_MAX_WORDS} palabras. Sin valor o vacío: sin búsqueda.",
        examples=["asad"],
    )] = None,
    sort: Annotated[Sort | None, Query(
        description="Orden: `name` (por defecto sin `q`), `relevance` (por defecto con `q`), `price_asc`, "
                    "`price_desc`, `discount` (mayor descuento primero) o `price_per_ml` (más barato por ml "
                    "primero). Los productos sin el dato van al final; los empates, por nombre.",
        examples=["price_asc"])] = None,
    limit: Annotated[int, Query(ge=1, le=100, description="Productos por página (1 a 100).")] = 20,
    offset: Annotated[int, Query(ge=0, description="Productos a saltar: `offset = página × limit`.")] = 0,
) -> ProductPage:
    """Productos que hoy se venden en al menos una tienda, ordenados por nombre.

    Cada uno trae el precio actual más bajo entre las tiendas donde está
    disponible. Para paginar, usar `total`: hay más páginas mientras
    `offset + limit < total`.

    Con `q`, primero el producto cuyo nombre es la búsqueda, luego los que
    empiezan con ella (con o sin la marca delante) y después el resto; dentro
    de cada grupo, por nombre. `total` cuenta solo los que coinciden.

    Todos los filtros se combinan entre sí (y con `q` y `brand`); los que
    aceptan varios valores se repiten en la URL.
    """
    brand = (brand or "").strip() or None
    words = tuple((q or "").split())
    if len(words) > SEARCH_MAX_WORDS:
        raise RequestValidationError([{
            "type": "too_many_words", "loc": ("query", "q"), "input": q,
            "msg": f"The search has {len(words)} words; at most {SEARCH_MAX_WORDS} are allowed",
            "ctx": {"max_words": SEARCH_MAX_WORDS},
        }])
    items, total = repository.list_products(brand, limit, offset, words, filters, sort)
    return ProductPage(items=items, total=total, limit=limit, offset=offset)


SEMANTIC_MAX_LENGTH = 200


@search_router.get(
    "/semantic",
    summary="Búsqueda semántica (para el chatbot)",
    response_description="Los productos a la venta más parecidos a la consulta, del más parecido al menos.",
    responses={**ok(SEMANTIC_EXAMPLE), 503: {"model": ErrorResponse,
                     "description": "La base no responde, o el modelo de embeddings no está descargado.",
                     "content": {"application/json": {"example": {
                         "detail": "Semantic search unavailable: embedding model intfloat/multilingual-e5-base "
                                   "is not downloaded"}}}}},
)
def semantic_search(
    repository: Repository,
    embedder: Annotated[Embedder, Depends(get_embedder)],
    filters: Filters,
    q: Annotated[str, Query(
        min_length=1, max_length=SEMANTIC_MAX_LENGTH, pattern=SEARCH_PATTERN,
        description="Lo que busca la persona, en lenguaje natural o con un nombre aproximado: "
                    "`perfume árabe de vainilla para hombre`, `colonia inglesa`. Hasta "
                    f"{SEMANTIC_MAX_LENGTH} caracteres.",
        examples=["perfume dulce de vainilla"])],
    limit: Annotated[int, Query(ge=1, le=50, description="Cuántos productos devolver (1 a 50).")] = 10,
) -> SemanticPage:
    """Productos ordenados por parecido de significado con `q`, con los mismos filtros que `GET /products`.

    Compara la consulta con el embedding de cada fragancia (calculado con el
    nombre y la marca de sus publicaciones, con el mismo modelo multilingüe),
    así que entiende sinónimos, otros idiomas y nombres mal escritos, pero
    **solo sabe lo que dicen los nombres**: no conoce notas olfativas ni
    descripciones. Devuelve los productos a la venta de las 200 fragancias más
    parecidas, filtrados, del más parecido al menos (`similarity`, de -1 a 1).
    No pagina: pedir más con `limit`.
    """
    text = q.strip()
    if not text:
        raise RequestValidationError([{"type": "string_too_short", "loc": ("query", "q"), "input": q,
                                       "msg": "The search is empty"}])
    try:
        vector = embedder(text)
    except SemanticSearchUnavailable as error:
        raise HTTPException(status_code=503, detail=f"Semantic search unavailable: {error}") from error
    matches = repository.semantic_search(vector, limit, filters)
    return SemanticPage(query=text, items=[SemanticMatch(**product.model_dump(), similarity=similarity)
                                           for product, similarity in matches])


@brands_router.get(
    "",
    summary="Listar marcas",
    response_description="Las marcas con productos a la venta, para los menús de filtros.",
    responses=ok(BRANDS_EXAMPLE),
)
def list_brands(repository: Repository) -> BrandList:
    """Cada marca con cuántos de sus productos se venden hoy en alguna tienda, en orden alfabético.

    El nombre de la marca es el mismo que usan `GET /products` (campo `brand`) y su filtro `brand`.
    """
    items = repository.list_brands()
    return BrandList(items=items, total=len(items))


@offers_router.get(
    "",
    summary="Ofertas verificadas",
    response_description="Descuentos cuyo precio de lista coincide con el historial, de mayor a menor en pesos.",
    responses=ok(OFFERS_EXAMPLE),
)
def list_offers(
    repository: Repository,
    store: Annotated[list[str] | None, Query(
        description=f"Solo ofertas de esta tienda ({', '.join(sorted(STORES))}); se puede repetir.",
        examples=[["salcobrand"]])] = None,
    brand: Annotated[str | None, Query(description="Marca exacta, sin distinguir mayúsculas.",
                                       examples=["Lattafa"])] = None,
    window_days: Annotated[int, Query(
        ge=1, le=365, description="Días de historial con que se verifica el precio de lista (1 a 365).",
    )] = DEFAULT_WINDOW_DAYS,
    limit: Annotated[int, Query(ge=1, le=100, description="Ofertas por página (1 a 100).")] = 20,
    offset: Annotated[int, Query(ge=0, description="Ofertas a saltar: `offset = página × limit`.")] = 0,
) -> OfferPage:
    """Las ofertas con descuento cuyo precio de lista está respaldado por el historial de la publicación.

    Una oferta entra si hoy está disponible con descuento (precio de lista
    tachado mayor que el precio) y su precio de lista **no supera el precio más
    alto que esa misma publicación cobró sin descuento y con stock** en los
    últimos `window_days` días (`vs_history.status = consistent`, igual que en
    `GET /products/{product_id}/list-price-checks`).

    Quedan fuera las que no tienen con qué compararse (`insufficient_data`:
    con poco historial son la mayoría) y las de precio de lista sobre su
    historial (`above_history`). Orden: de mayor a menor descuento en pesos.
    `vs_market` acompaña como contexto. Se actualiza con cada corrida diaria.
    """
    unknown = sorted(set(store or ()) - set(STORES))
    if unknown:
        raise RequestValidationError([{"type": "enum", "loc": ("query", "store"), "input": unknown,
                                       "msg": f"Unknown store: {', '.join(unknown)}. Known: {', '.join(sorted(STORES))}"}])
    items, total = repository.list_offers(window_days, tuple(sorted(set(store or ()))),
                                          (brand or "").strip() or None, limit, offset)
    return OfferPage(items=items, total=total, limit=limit, offset=offset, window_days=window_days)


@router.get(
    "/{product_id}",
    summary="Ver un producto y sus precios actuales",
    response_description="La ficha del producto con el precio de cada publicación.",
    responses={**ok(DETAIL_EXAMPLE), **NOT_FOUND},
)
def get_product(product_id: ProductId, repository: Repository, request: Request) -> ProductDetail:
    """Ficha del producto y el precio actual de cada publicación, de la más barata a la más cara.

    También responde para productos que ya no se venden (con `prices`
    vacío), para que los enlaces guardados sigan funcionando.
    """
    product = repository.get_product(product_id)
    if product is None:
        raise missing_product(product_id, repository, request)
    return product


@router.get(
    "/{product_id}/variants",
    summary="Otros tamaños y presentaciones del mismo perfume",
    response_description="Los otros productos de la misma fragancia que hoy se venden.",
    responses={**ok(VARIANTS_EXAMPLE), **NOT_FOUND},
)
def get_variants(product_id: ProductId, repository: Repository, request: Request) -> VariantList:
    """Los otros productos de la misma fragancia: el mismo perfume en otro tamaño, como set o tester.

    Misma fragancia es misma marca, nombre y género. Una versión distinta
    (Elixir, Intense, Parfum) es otra fragancia y no aparece. Solo productos
    que hoy se venden; la lista viene vacía si no hay otros.
    """
    product = repository.get_product(product_id)
    variants = repository.get_variants(product_id) if product is not None else None
    if product is None or variants is None:
        raise missing_product(product_id, repository, request, "/variants")
    return VariantList(product_id=product_id, canonical_name=product.canonical_name, items=variants)


@router.get(
    "/{product_id}/price-history",
    summary="Historial de precios de un producto",
    response_description="Una serie de precios por publicación.",
    responses={**ok(HISTORY_EXAMPLE), **NOT_FOUND},
)
def get_price_history(product_id: ProductId, repository: Repository, request: Request) -> PriceHistory:
    """Todas las lecturas de precio de cada publicación del producto, para graficar su evolución.

    Una serie por publicación (una línea por tienda en el gráfico; dos si una
    tienda lo publicó dos veces). Los puntos van de más antiguo a más reciente,
    con una lectura por cada vez que se revisó la tienda.
    """
    history = repository.get_price_history(product_id)
    if history is None:
        raise missing_product(product_id, repository, request, "/price-history")
    return history


@router.get(
    "/{product_id}/list-price-checks",
    summary="Verificar los precios de lista de un producto",
    response_description="Para cada publicación actual, su precio de lista contra su historial y contra otras tiendas.",
    responses={**ok(CHECKS_EXAMPLE), **NOT_FOUND},
)
def get_list_price_checks(
    product_id: ProductId,
    repository: Repository,
    request: Request,
    window_days: Annotated[int, Query(
        ge=1, le=365, description="Días de historial que se revisan antes de la lectura actual (1 a 365).",
    )] = DEFAULT_WINDOW_DAYS,
) -> ListPriceChecks:
    """Compara el precio de lista (el precio "normal" tachado) de cada publicación con dos referencias.

    - **`vs_history`**: el historial de la misma publicación. `above_history`
      significa precio de lista inconsistente con el historial: la tienda
      anuncia como precio normal uno más alto que el que cobró sin descuento
      en la ventana.
    - **`vs_market`**: lo que cobran otras tiendas sin descuento por el mismo
      producto (mediana entre tiendas). Es un **dato de contexto, no una
      alerta**: los precios normales varían entre tiendas y depende de que el
      emparejamiento sea correcto.

    Ninguna de las dos afirma intención. Sin datos con qué comparar, el
    estado es `insufficient_data`, que no significa que el precio esté bien.
    Con poco historial, la mayoría de los descuentos sale así.
    """
    checks = repository.get_list_price_checks(product_id, window_days)
    if checks is None:
        raise missing_product(product_id, repository, request, "/list-price-checks")
    return checks
