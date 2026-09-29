"""Response models. Prices are whole Chilean pesos (CLP has no decimals).

Descriptions and examples are for /docs; they do not change the JSON shape.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

EXAMPLE_ID = "6534b09e-a83c-4a52-812a-49280f82de79"


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


PRODUCT_ID = Field(description="ID estable del producto (UUID).", examples=[EXAMPLE_ID])
CANONICAL_NAME = Field(
    description="Nombre normalizado para mostrar: marca, fragancia, concentración y volumen.",
    examples=["Lattafa Asad EDP 100 ml"],
)
BRAND = Field(description="Marca, escrita igual en todo el catálogo.", examples=["Lattafa"])
CONCENTRATION = Field(
    description="Concentración: edp, edt, parfum, cologne, eau_fraiche u other. "
                "`null` si ninguna tienda la informa (común en body mists).",
    examples=["edp"],
)
VOLUME_ML = Field(description="Volumen en mililitros.", examples=[100])
CURRENCY = Field(description="Moneda de todos los precios. Siempre CLP.", examples=["CLP"])
STORE = Field(description="Tienda, en minúsculas: `preunic`, `maicao` o `salcobrand`.", examples=["preunic"])
PRICE = Field(description="Precio actual en CLP, con el descuento incluido si lo hay.", examples=[25999])
LIST_PRICE = Field(
    description="Precio \"normal\" tachado en CLP. `null` si la tienda no muestra descuento.",
    examples=[34999],
)
IS_AVAILABLE = Field(description="`false` si la tienda lo muestra sin stock online.", examples=[True])
LISTING_URL = Field(
    description="Página del producto en la tienda.",
    examples=["https://preunic.cl/products/perfume-hombre-lattafa-asad-edp-100-ml"],
)
SCRAPED_AT = Field(description="Cuándo se leyó este precio (UTC, ISO 8601).",
                   examples=["2026-09-25T22:43:19.504174Z"])


# GET /products
class ProductSummary(BaseModel):
    """Un producto en la lista, con el precio más bajo entre tiendas."""

    product_id: UUID = PRODUCT_ID
    canonical_name: str = CANONICAL_NAME
    brand: str = BRAND
    concentration: Concentration | None = CONCENTRATION
    volume_ml: int = VOLUME_ML
    lowest_price: int | None = Field(
        description="Precio actual más bajo en CLP entre las publicaciones disponibles. "
                    "`null` si ninguna tienda lo tiene disponible.",
        examples=[25999],
    )
    lowest_price_store: str | None = Field(
        description="Tienda con el precio más bajo (`null` junto con `lowest_price`). "
                    "Si dos tiendas empatan, la primera en orden alfabético.",
        examples=["preunic"],
    )


class ProductPage(BaseModel):
    """Una página de productos."""

    items: list[ProductSummary] = Field(description="Productos de esta página, ordenados por `canonical_name`.")
    total: int = Field(description="Total de productos con el filtro aplicado (todas las páginas).", examples=[588])
    limit: int = Field(description="Tamaño de página pedido.", examples=[20])
    offset: int = Field(description="Productos saltados antes de esta página.", examples=[0])


# GET /products/{product_id}
class StorePrice(BaseModel):
    """Precio actual de una publicación."""

    store: str = STORE
    price: int = PRICE
    list_price: int | None = LIST_PRICE
    is_available: bool = IS_AVAILABLE
    listing_url: str = LISTING_URL
    scraped_at: datetime = SCRAPED_AT


class ProductDetail(BaseModel):
    """Ficha de un producto con sus precios actuales."""

    product_id: UUID = PRODUCT_ID
    canonical_name: str = CANONICAL_NAME
    brand: str = BRAND
    concentration: Concentration | None = CONCENTRATION
    volume_ml: int = VOLUME_ML
    presentation: Presentation = Field(
        description="full_bottle (frasco), tester, travel_set (estuche o set), miniature o refill.",
        examples=["full_bottle"],
    )
    currency: str = Field("CLP", description=CURRENCY.description, examples=CURRENCY.examples)
    prices: list[StorePrice] = Field(
        description="Una entrada por publicación activa, de la más barata a la más cara. Puede haber dos de "
                    "la misma tienda (la tienda publicó el producto dos veces) y puede venir vacía si "
                    "hoy ninguna tienda lo publica.",
    )


# GET /products/{product_id}/price-history
class PricePoint(BaseModel):
    """El precio de una publicación en una lectura."""

    scraped_at: datetime = SCRAPED_AT
    price: int = PRICE
    list_price: int | None = LIST_PRICE
    is_available: bool = IS_AVAILABLE


class PriceSeries(BaseModel):
    """Historial de una publicación: una línea del gráfico."""

    store: str = STORE
    listing_url: str = LISTING_URL
    points: list[PricePoint] = Field(description="Lecturas de la más antigua a la más reciente.")


class PriceHistory(BaseModel):
    """Historial de precios de un producto, una serie por publicación."""

    product_id: UUID = PRODUCT_ID
    canonical_name: str = CANONICAL_NAME
    currency: str = Field("CLP", description=CURRENCY.description, examples=CURRENCY.examples)
    series: list[PriceSeries] = Field(
        description="Una serie por publicación, incluidas las que ya no están activas. "
                    "Vacía si el producto no tiene publicaciones con historial.",
    )


class ErrorResponse(BaseModel):
    """Error 404 o 503."""

    detail: str = Field(description="Qué salió mal, en inglés.", examples=["Product not found"])
