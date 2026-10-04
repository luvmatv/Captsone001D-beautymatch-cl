from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from src.api.db import get_product_repository
from src.api.repositories.products import ProductRepository
from src.api.schemas import EXAMPLE_ID, ErrorResponse, ListPriceChecks, PriceHistory, ProductDetail, ProductPage
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


NOT_FOUND = {404: {"model": ErrorResponse, "description": "No existe un producto con ese ID.",
                   "content": {"application/json": {"example": {"detail": "Product not found"}}}}}
UNAVAILABLE = {503: {"model": ErrorResponse, "description": "La base de datos no responde; reintentar más tarde.",
                     "content": {"application/json": {"example": {"detail": "Database unavailable"}}}}}

router = APIRouter(prefix="/products", tags=["products"], responses=UNAVAILABLE)

Repository = Annotated[ProductRepository, Depends(get_product_repository)]
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
    limit: Annotated[int, Query(ge=1, le=100, description="Productos por página (1 a 100).")] = 20,
    offset: Annotated[int, Query(ge=0, description="Productos a saltar: `offset = página × limit`.")] = 0,
) -> ProductPage:
    """Productos que hoy se venden en al menos una tienda, ordenados por nombre.

    Cada uno trae el precio actual más bajo entre las tiendas donde está
    disponible. Para paginar, usar `total`: hay más páginas mientras
    `offset + limit < total`.
    """
    brand = (brand or "").strip() or None
    items, total = repository.list_products(brand, limit, offset)
    return ProductPage(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/{product_id}",
    summary="Ver un producto y sus precios actuales",
    response_description="La ficha del producto con el precio de cada publicación.",
    responses={**ok(DETAIL_EXAMPLE), **NOT_FOUND},
)
def get_product(product_id: ProductId, repository: Repository) -> ProductDetail:
    """Ficha del producto y el precio actual de cada publicación, de la más barata a la más cara.

    También responde para productos que ya no se venden (con `prices`
    vacío), para que los enlaces guardados sigan funcionando.
    """
    product = repository.get_product(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.get(
    "/{product_id}/price-history",
    summary="Historial de precios de un producto",
    response_description="Una serie de precios por publicación.",
    responses={**ok(HISTORY_EXAMPLE), **NOT_FOUND},
)
def get_price_history(product_id: ProductId, repository: Repository) -> PriceHistory:
    """Todas las lecturas de precio de cada publicación del producto, para graficar su evolución.

    Una serie por publicación (una línea por tienda en el gráfico; dos si una
    tienda lo publicó dos veces). Los puntos van de más antiguo a más reciente,
    con una lectura por cada vez que se revisó la tienda.
    """
    history = repository.get_price_history(product_id)
    if history is None:
        raise HTTPException(status_code=404, detail="Product not found")
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
        raise HTTPException(status_code=404, detail="Product not found")
    return checks
