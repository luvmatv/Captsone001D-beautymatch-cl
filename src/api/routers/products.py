from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.db import get_product_repository
from src.api.repositories.products import ProductRepository
from src.api.schemas import ErrorResponse, PriceHistory, ProductDetail, ProductPage

router = APIRouter(prefix="/products", tags=["products"])

Repository = Annotated[ProductRepository, Depends(get_product_repository)]
NOT_FOUND = {404: {"model": ErrorResponse, "description": "Product not found"}}


@router.get("")
def list_products(
    repository: Repository,
    brand: Annotated[str | None, Query(description="Exact brand, case-insensitive")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProductPage:
    brand = (brand or "").strip() or None
    items, total = repository.list_products(brand, limit, offset)
    return ProductPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/{product_id}", responses=NOT_FOUND)
def get_product(product_id: UUID, repository: Repository) -> ProductDetail:
    product = repository.get_product(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.get("/{product_id}/price-history", responses=NOT_FOUND)
def get_price_history(product_id: UUID, repository: Repository) -> PriceHistory:
    history = repository.get_price_history(product_id)
    if history is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return history
