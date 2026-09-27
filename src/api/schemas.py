"""Response models. Prices are whole Chilean pesos (CLP has no decimals)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel


class Concentration(StrEnum):  # = concentration_type in the database
    EDP = "edp"
    EDT = "edt"
    PARFUM = "parfum"
    COLOGNE = "cologne"
    EAU_FRAICHE = "eau_fraiche"
    OTHER = "other"


class Presentation(StrEnum):  # = presentation_type
    FULL_BOTTLE = "full_bottle"
    TESTER = "tester"
    TRAVEL_SET = "travel_set"
    MINIATURE = "miniature"
    REFILL = "refill"


# GET /products
class ProductSummary(BaseModel):
    product_id: UUID
    canonical_name: str
    brand: str
    concentration: Concentration | None  # None = no store states it
    volume_ml: int
    lowest_price: int | None  # None when no store has it available
    lowest_price_store: str | None


class ProductPage(BaseModel):
    items: list[ProductSummary]
    total: int  # with the filter applied
    limit: int
    offset: int


# GET /products/{product_id}
class StorePrice(BaseModel):
    store: str
    price: int  # current price, discount included
    list_price: int | None  # crossed-out "before discount" price; None when there is no discount
    is_available: bool
    listing_url: str
    scraped_at: datetime


class ProductDetail(BaseModel):
    product_id: UUID
    canonical_name: str
    brand: str
    concentration: Concentration | None
    volume_ml: int
    presentation: Presentation
    currency: str = "CLP"
    prices: list[StorePrice]  # one per active listing, cheapest first


# GET /products/{product_id}/price-history
class PricePoint(BaseModel):
    scraped_at: datetime
    price: int
    list_price: int | None
    is_available: bool


class PriceSeries(BaseModel):
    store: str
    listing_url: str
    points: list[PricePoint]  # oldest first


class PriceHistory(BaseModel):
    product_id: UUID
    canonical_name: str
    currency: str = "CLP"
    series: list[PriceSeries]  # one per listing


class ErrorResponse(BaseModel):
    detail: str
