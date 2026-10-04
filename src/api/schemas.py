"""Response models. Prices are whole Chilean pesos (CLP has no decimals).

Descriptions and examples are for /docs; they do not change the JSON shape.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from src.pricing.list_price_checks import MARKET_MARGIN, HistoryStatus, MarketStatus

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
STORE = Field(description="Tienda, en minúsculas: `preunic`, `maicao`, `salcobrand` o `beautyperfumes`.",
              examples=["preunic"])
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


# GET /products/{product_id}/list-price-checks
class HistoryCheck(BaseModel):
    """Precio de lista contra el historial de la misma publicación."""

    status: HistoryStatus = Field(
        description="`no_list_price`: hoy no muestra precio de lista (no anuncia descuento). "
                    "`insufficient_data`: no hay ninguna lectura sin descuento y con stock en la ventana, "
                    "así que no se puede decir nada (no significa que esté bien). "
                    "`consistent`: el precio de lista no supera el precio más alto cobrado sin descuento. "
                    "`above_history`: precio de lista inconsistente con el historial: supera el precio "
                    "más alto que esta misma publicación cobró sin descuento en la ventana.",
        examples=["consistent"],
    )
    reference_price: int | None = Field(
        description="Precio más alto cobrado sin descuento y con stock en la ventana, en CLP. "
                    "`null` si no hay ninguno o si no hay precio de lista.",
        examples=[29999],
    )
    reference_scraped_at: datetime | None = Field(
        description="Última lectura con ese precio de referencia (UTC). `null` junto con `reference_price`.",
        examples=["2026-09-28T13:13:54Z"],
    )
    observed_from: datetime | None = Field(
        description="Primera lectura de la publicación dentro de la ventana (UTC): desde cuándo hay datos.",
        examples=["2026-09-25T12:14:16Z"],
    )
    points_in_window: int = Field(description="Lecturas de la publicación dentro de la ventana.", examples=[5])
    undiscounted_points: int = Field(
        description="De esas, cuántas fueron sin descuento y con stock (las que sirven de referencia).",
        examples=[2],
    )


class MarketCheck(BaseModel):
    """Precio de lista contra otras tiendas. Dato de contexto, no una alerta."""

    status: MarketStatus = Field(
        description="`no_list_price`: hoy no muestra precio de lista. "
                    "`insufficient_data`: ninguna otra tienda vende el mismo producto disponible y sin "
                    "descuento. `within_market`: el precio de lista no supera la referencia en más de "
                    f"{MARKET_MARGIN:.0%}. `above_market`: precio de lista sobre el mercado: la supera en "
                    f"más de {MARKET_MARGIN:.0%}. Depende del emparejamiento entre tiendas.",
        examples=["above_market"],
    )
    reference_price: int | None = Field(
        description="Mediana, entre las otras tiendas, del precio sin descuento de cada una (si una tienda "
                    "lo publica dos veces, cuenta una vez con el más bajo). `null` si no hay ninguna.",
        examples=[39999],
    )
    reference_stores: list[str] = Field(description="Tiendas usadas para la referencia.", examples=[["salcobrand"]])
    percent_above: float | None = Field(
        description="Cuánto supera el precio de lista a la referencia, en porcentaje (negativo si es menor). "
                    "`null` si no hay referencia.",
        examples=[75.0],
    )


class ListPriceCheck(BaseModel):
    """Las verificaciones de una publicación con su precio actual."""

    store: str = STORE
    listing_url: str = LISTING_URL
    price: int = PRICE
    list_price: int | None = LIST_PRICE
    is_available: bool = IS_AVAILABLE
    scraped_at: datetime = SCRAPED_AT
    vs_history: HistoryCheck = Field(description="Precio de lista contra el historial de esta publicación.")
    vs_market: MarketCheck = Field(description="Precio de lista contra otras tiendas (contexto, no alerta).")


class ListPriceChecks(BaseModel):
    """Verificación de los precios de lista de un producto."""

    product_id: UUID = PRODUCT_ID
    canonical_name: str = CANONICAL_NAME
    currency: str = Field("CLP", description=CURRENCY.description, examples=CURRENCY.examples)
    window_days: int = Field(description="Días de historial revisados antes de la lectura actual.", examples=[30])
    checks: list[ListPriceCheck] = Field(
        description="Una entrada por publicación activa, en el mismo orden que `prices` de la ficha. "
                    "Vacía si hoy ninguna tienda lo publica.",
    )


class ErrorResponse(BaseModel):
    """Error 404 o 503."""

    detail: str = Field(description="Qué salió mal, en inglés.", examples=["Product not found"])
