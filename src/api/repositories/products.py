"""Product queries. Routers depend on the ProductRepository protocol, so tests
can swap PostgresProductRepository for an in-memory fake."""

from __future__ import annotations

from dataclasses import asdict
from itertools import groupby
from typing import Protocol
from uuid import UUID

import psycopg

from src.api.schemas import (
    HistoryCheck,
    ListPriceCheck,
    ListPriceChecks,
    MarketCheck,
    PriceHistory,
    PricePoint,
    PriceSeries,
    ProductDetail,
    ProductSummary,
    StorePrice,
)
from src.pricing.list_price_checks import Offer, Reading, check_offers


class ProductRepository(Protocol):
    def list_products(self, brand: str | None, limit: int, offset: int) -> tuple[list[ProductSummary], int]:
        """One page of products and the total matching the filter."""

    def get_product(self, product_id: UUID) -> ProductDetail | None: ...

    def get_price_history(self, product_id: UUID) -> PriceHistory | None: ...

    def get_list_price_checks(self, product_id: UUID, window_days: int) -> ListPriceChecks | None: ...


# A pending listing keeps its last product_id (so the pipeline can give it the
# same product when it is resolved), but it is not an offer of that product:
# every query counts only resolved listings.
RESOLVED = "rl.matching_status IN ('matched', 'new_product')"

# Cheapest available current price per product; ties go to the store name, so
# the result does not change between identical requests.
LOWEST_PRICE = f"""
SELECT DISTINCT ON (cp.product_id) cp.product_id, cp.price AS lowest_price, s.name AS lowest_price_store
FROM current_prices cp
JOIN raw_listings rl ON rl.raw_listing_id = cp.raw_listing_id
JOIN stores s ON s.store_id = cp.store_id
WHERE cp.is_available AND cp.product_id IS NOT NULL AND {RESOLVED}
ORDER BY cp.product_id, cp.price, s.name
"""

# The list shows only products on sale (an active resolved listing). Detail
# and history still answer for the others, so links keep working.
LIST_FILTER = f"""(%(brand)s::text IS NULL OR lower(f.brand) = lower(%(brand)s::text))
  AND EXISTS (SELECT 1 FROM raw_listings rl WHERE rl.product_id = p.product_id AND rl.is_active AND {RESOLVED})"""

LIST_PRODUCTS = f"""
WITH lowest AS ({LOWEST_PRICE})
SELECT p.product_id, p.canonical_name, f.brand, p.concentration::text AS concentration, p.volume_ml,
       lowest.lowest_price, lowest.lowest_price_store
FROM products p
JOIN fragrances f ON f.fragrance_id = p.fragrance_id
LEFT JOIN lowest ON lowest.product_id = p.product_id
WHERE {LIST_FILTER}
ORDER BY p.canonical_name, p.product_id
LIMIT %(limit)s OFFSET %(offset)s
"""

COUNT_PRODUCTS = f"""
SELECT count(*) AS total
FROM products p
JOIN fragrances f ON f.fragrance_id = p.fragrance_id
WHERE {LIST_FILTER}
"""

GET_PRODUCT = """
SELECT p.product_id, p.canonical_name, f.brand, p.concentration::text AS concentration, p.volume_ml,
       p.presentation::text AS presentation
FROM products p
JOIN fragrances f ON f.fragrance_id = p.fragrance_id
WHERE p.product_id = %s
"""

CURRENT_PRICES = f"""
SELECT s.name AS store, cp.price, cp.list_price, cp.is_available, rl.listing_url, cp.scraped_at
FROM current_prices cp
JOIN raw_listings rl ON rl.raw_listing_id = cp.raw_listing_id
JOIN stores s ON s.store_id = cp.store_id
WHERE cp.product_id = %s AND {RESOLVED}
ORDER BY cp.price, s.name, rl.listing_url
"""

# Every scrape of every resolved listing of the product, including listings no
# longer active: they are still part of the product's price history. A pending
# listing's whole series is hidden while it is pending, like in the detail,
# and comes back complete if it is resolved to this product again.
PRICE_HISTORY = f"""
SELECT rl.raw_listing_id, s.name AS store, rl.listing_url,
       ph.scraped_at, ph.price, ph.list_price, ph.is_available
FROM raw_listings rl
JOIN stores s ON s.store_id = rl.store_id
JOIN price_history ph ON ph.raw_listing_id = rl.raw_listing_id
WHERE rl.product_id = %s AND {RESOLVED}
ORDER BY s.name, rl.listing_url, rl.raw_listing_id, ph.scraped_at
"""


# The offers of the detail (same filter and order) with their listing IDs, and
# every reading of those listings: check_history picks the window itself.
CHECKED_OFFERS = f"""
SELECT cp.raw_listing_id, s.name AS store, rl.listing_url, cp.price, cp.list_price, cp.is_available, cp.scraped_at
FROM current_prices cp
JOIN raw_listings rl ON rl.raw_listing_id = cp.raw_listing_id
JOIN stores s ON s.store_id = cp.store_id
WHERE cp.product_id = %s AND {RESOLVED}
ORDER BY cp.price, s.name, rl.listing_url
"""
OFFER_READINGS = """
SELECT raw_listing_id, scraped_at, price, list_price, is_available
FROM price_history WHERE raw_listing_id = ANY(%s)
ORDER BY raw_listing_id, scraped_at
"""


def _reading(row: dict) -> Reading:
    return Reading(row["scraped_at"], int(row["price"]),
                   int(row["list_price"]) if row["list_price"] is not None else None, row["is_available"])


class PostgresProductRepository:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection  # rows as dicts (the pool sets dict_row)

    def list_products(self, brand: str | None, limit: int, offset: int) -> tuple[list[ProductSummary], int]:
        params = {"brand": brand, "limit": limit, "offset": offset}
        rows = self.connection.execute(LIST_PRODUCTS, params).fetchall()
        total = self.connection.execute(COUNT_PRODUCTS, params).fetchone()["total"]
        return [ProductSummary(**row) for row in rows], total

    def get_product(self, product_id: UUID) -> ProductDetail | None:
        product = self.connection.execute(GET_PRODUCT, (product_id,)).fetchone()
        if product is None:
            return None
        prices = self.connection.execute(CURRENT_PRICES, (product_id,)).fetchall()
        return ProductDetail(**product, prices=[StorePrice(**row) for row in prices])

    def get_price_history(self, product_id: UUID) -> PriceHistory | None:
        product = self.connection.execute(GET_PRODUCT, (product_id,)).fetchone()
        if product is None:
            return None
        rows = self.connection.execute(PRICE_HISTORY, (product_id,)).fetchall()
        series = []
        for _, points in groupby(rows, key=lambda row: row["raw_listing_id"]):
            points = list(points)
            series.append(PriceSeries(
                store=points[0]["store"],
                listing_url=points[0]["listing_url"],
                points=[PricePoint(**point) for point in points],
            ))
        return PriceHistory(product_id=product_id, canonical_name=product["canonical_name"], series=series)

    def get_list_price_checks(self, product_id: UUID, window_days: int) -> ListPriceChecks | None:
        product = self.connection.execute(GET_PRODUCT, (product_id,)).fetchone()
        if product is None:
            return None
        rows = self.connection.execute(CHECKED_OFFERS, (product_id,)).fetchall()
        readings = {listing_id: [_reading(r) for r in group] for listing_id, group in groupby(
            self.connection.execute(OFFER_READINGS, ([row["raw_listing_id"] for row in rows],)).fetchall(),
            key=lambda r: r["raw_listing_id"])}
        offers = [Offer(row["store"], row["listing_url"], _reading(row), tuple(readings[row["raw_listing_id"]]))
                  for row in rows]
        checks = [
            ListPriceCheck(
                store=offer.store, listing_url=offer.listing_url, price=offer.current.price,
                list_price=offer.current.list_price, is_available=offer.current.is_available,
                scraped_at=offer.current.scraped_at,
                vs_history=HistoryCheck(**asdict(history)),
                vs_market=MarketCheck(**{**asdict(market), "reference_stores": list(market.reference_stores)}),
            )
            for offer, history, market in check_offers(offers, window_days)
        ]
        return ListPriceChecks(product_id=product_id, canonical_name=product["canonical_name"],
                               window_days=window_days, checks=checks)
