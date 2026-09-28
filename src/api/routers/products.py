from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from src.api.db import get_product_repository
from src.api.repositories.products import ProductRepository
from src.api.schemas import EXAMPLE_ID, ErrorResponse, PriceHistory, ProductDetail, ProductPage

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
