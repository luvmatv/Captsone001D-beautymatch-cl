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
    VariantList,
)
from src.matching.pipeline import MATCHING_STORES as STORES
from src.pricing.list_price_checks import DEFAULT_WINDOW_DAYS

# Example bodies for /docs, taken from real responses (Lattafa Asad EDP 100 ml).
PREUNIC_URL = "https://preunic.cl/products/perfume-hombre-lattafa-asad-edp-100-ml"
MAICAO_URL = "https://www.maicao.cl/asad-medp-sp100m/CLMC_589473.html"
LIST_EXAMPLE = {
    "items": [{
        "product_id": EXAMPLE_ID, "canonical_name": "Lattafa Asad EDP 100 ml", "brand": "Lattafa",
        "concentration": "edp", "volume_ml": 100, "lowest_price": 25999, "lowest_price_store": "preunic",
    }],
    "total": 7, "limit": 1, "offset": 0,
}
DETAIL_EXAMPLE = {
    "product_id": EXAMPLE_ID, "canonical_name": "Lattafa Asad EDP 100 ml", "brand": "Lattafa",
    "concentration": "edp", "volume_ml": 100, "presentation": "full_bottle", "currency": "CLP",
    "prices": [
        {"store": "preunic", "price": 25999, "list_price": 34999, "is_available": True,
         "listing_url": PREUNIC_URL, "scraped_at": "2026-09-25T22:43:19.504174Z"},
        {"store": "maicao", "price": 35999, "list_price": 39999, "is_available": True,
         "listing_url": MAICAO_URL, "scraped_at": "2026-09-25T12:22:36.734262Z"},
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

router = APIRouter(prefix="/products", tags=["products"], responses=UNAVAILABLE)
brands_router = APIRouter(prefix="/brands", tags=["brands"], responses=UNAVAILABLE)
offers_router = APIRouter(prefix="/offers", tags=["offers"], responses=UNAVAILABLE)

Repository = Annotated[ProductRepository, Depends(get_product_repository)]

SEARCH_MAX_LENGTH = 100
SEARCH_MAX_WORDS = 10
# No control characters (a NUL cannot even reach PostgreSQL); everything else is
# searched literally: LIKE's % and _ are escaped by the repository.
SEARCH_PATTERN = r"^[^\x00-\x1f\x7f]*$"
ProductId = Annotated[UUID, Path(description="ID del producto (UUID), tal como viene en `GET /products`.",
                                 examples=[EXAMPLE_ID])]


@router.get(
    "",
    summary="Listar productos",
    response_description="Una página de productos con su precio más bajo.",
    responses=ok(LIST_EXAMPLE),
)
def list_products(
    repository: Repository,
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
    filters = ProductFilters(
        min_price=min_price, max_price=max_price, concentrations=tuple(c.value for c in concentration or ()),
        min_volume=min_volume, max_volume=max_volume, genders=tuple(g.value for g in gender or ()),
        stores=tuple(sorted(set(store or ()))))
    items, total = repository.list_products(brand, limit, offset, words, filters, sort)
    return ProductPage(items=items, total=total, limit=limit, offset=offset)


@brands_router.get(
    "",
    summary="Listar marcas",
    response_description="Las marcas con productos a la venta, para los menús de filtros.",
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
    responses=NOT_FOUND,
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
