"""Product queries. Routers depend on the ProductRepository protocol, so tests
can swap PostgresProductRepository for an in-memory fake."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from itertools import groupby
from typing import Protocol
from uuid import UUID

import psycopg

from src.api.schemas import (
    BrandCount,
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
    VerifiedOffer,
)
from src.pricing.list_price_checks import HistoryStatus, Offer, Reading, check_history, check_market, check_offers


class ProductRepository(Protocol):
    def list_products(self, brand: str | None, limit: int, offset: int, words: tuple[str, ...] = (),
                      filters: ProductFilters | None = None,
                      sort: Sort | None = None) -> tuple[list[ProductSummary], int]:
        """One page of products and the total matching the filters (and every search word, if any)."""

    def list_brands(self) -> list[BrandCount]: ...

    def list_offers(self, window_days: int, stores: tuple[str, ...], brand: str | None, limit: int,
                    offset: int) -> tuple[list[VerifiedOffer], int]:
        """One page of verified discounts (largest in pesos first) and their total."""

    def get_variants(self, product_id: UUID) -> list[ProductSummary] | None:
        """The other products of the same fragrance on sale; None if the product does not exist."""

    def get_product(self, product_id: UUID) -> ProductDetail | None: ...

    def get_retirement(self, product_id: UUID) -> tuple[bool, UUID | None]:
        """(retired?, the product it lives on as now, following the chain; None if there is none)."""

    def semantic_search(self, vector: list[float], limit: int,
                        filters: ProductFilters | None = None) -> list[tuple[ProductSummary, float]]:
        """Products on sale whose fragrance is closest to the vector, most similar first, with the similarity."""

    def get_price_history(self, product_id: UUID) -> PriceHistory | None: ...

    def get_list_price_checks(self, product_id: UUID, window_days: int) -> ListPriceChecks | None: ...


# A pending listing keeps its last product_id (so the pipeline can give it the
# same product when it is resolved), but it is not an offer of that product:
# every query counts only resolved listings.
RESOLVED = "rl.matching_status IN ('matched', 'new_product')"

# Every current offer of a resolved listing (current_prices only has active listings).
OFFERS = f"""
SELECT cp.product_id, cp.price, cp.list_price, cp.is_available, cp.scraped_at, s.name AS store
FROM current_prices cp
JOIN raw_listings rl ON rl.raw_listing_id = cp.raw_listing_id
JOIN stores s ON s.store_id = cp.store_id
WHERE cp.product_id IS NOT NULL AND {RESOLVED}
"""

# Cheapest available current price per product; ties go to the store name, so
# the result does not change between identical requests.
LOWEST_PRICE = """
SELECT DISTINCT ON (product_id) product_id, price AS lowest_price, store AS lowest_price_store
FROM offers WHERE is_available
ORDER BY product_id, price, store
"""

# Per product: when a store was last read for it, its largest current discount
# among the available offers (the store's own list price against its price),
# and the stores that have it available.
OFFER_STATS = """
SELECT product_id, max(scraped_at) AS last_updated,
       max(CASE WHEN is_available AND list_price > price
                THEN round(100.0 * (list_price - price) / list_price, 1) END)::float AS best_discount_percent,
       array_agg(DISTINCT store) FILTER (WHERE is_available) AS stores
FROM offers GROUP BY product_id
"""

# A product's picture: the image of its cheapest available offer that has one
# (then any active listing's), so it usually matches the price shown. Maicao's
# listing has no image (database/006).
PRODUCT_IMAGE = f"""
SELECT DISTINCT ON (rl.product_id) rl.product_id, rl.image_url
FROM raw_listings rl
JOIN stores s ON s.store_id = rl.store_id
LEFT JOIN current_prices cp ON cp.raw_listing_id = rl.raw_listing_id
WHERE rl.is_active AND rl.image_url IS NOT NULL AND rl.product_id IS NOT NULL AND {RESOLVED}
ORDER BY rl.product_id, cp.is_available IS NOT TRUE, cp.price NULLS LAST, s.name, rl.listing_url
"""

# Price per ml in CLP, one decimal. Not for sets: their price pays for more than the main bottle.
PRICE_PER_ML = ("CASE WHEN p.presentation <> 'travel_set' AND {price} IS NOT NULL "
                "THEN round({price}::numeric / p.volume_ml, 1)::float END")


def _plain(expression: str) -> str:
    """SQL: the text in lower case, without accents or apostrophes ("Jazmín" = "jazmin",
    "Victoria´s" = "victorias"). Built-in functions only: no unaccent extension. The
    characters are those the catalog uses and their neighbours; others are kept as they are."""
    return f"translate(lower({expression}), 'áàâäãåéèêëíìîïóòôöõúùûüñçý''´', 'aaaaaaeeeeiiiiooooouuuuncy')"


def like_escape(word: str) -> str:
    r"""A search word as a literal LIKE pattern (ESCAPE '\'): "100%" matches "100%", not "100" + anything."""
    return word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class Sort(StrEnum):
    """Orders of GET /products. Every order ends with the name and the ID, so pages are stable."""

    RELEVANCE = "relevance"      # with q: exact name, then names starting with q, then the rest
    NAME = "name"
    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"
    DISCOUNT = "discount"        # largest current discount first
    PRICE_PER_ML = "price_per_ml"


@dataclass(frozen=True)
class ProductFilters:
    """The optional filters of GET /products (empty tuples / None: no filter)."""

    min_price: int | None = None        # on the lowest available price
    max_price: int | None = None
    concentrations: tuple[str, ...] = ()
    min_volume: int | None = None
    max_volume: int | None = None
    genders: tuple[str, ...] = ()       # male / female / unisex ("unisex" also means "not stated")
    stores: tuple[str, ...] = ()        # available in at least one of them


# The list shows only products on sale (an active resolved listing). Detail
# and history still answer for the others, so links keep working.
ON_SALE = f"EXISTS (SELECT 1 FROM raw_listings rl WHERE rl.product_id = p.product_id AND rl.is_active AND {RESOLVED})"

# Search (q): every word somewhere in the product's name or brand. The rank
# puts first the name equal to the search, then names that start with it (with
# or without the brand in front: "asad" finds "Lattafa Asad ..."), then the rest.
SEARCH = rf"""NOT EXISTS (
    SELECT 1 FROM unnest(%(words)s::text[]) AS search(word)
    WHERE listed.name_key || ' ' || listed.brand_key NOT LIKE '%%' || {_plain("search.word")} || '%%' ESCAPE '\')"""
PHRASE = _plain("%(phrase)s::text")
RANK = rf"""CASE
    WHEN listed.name_key LIKE {PHRASE} ESCAPE '\' THEN 0
    WHEN listed.name_key LIKE {PHRASE} || '%%' ESCAPE '\'
      OR (left(listed.name_key, length(listed.brand_key) + 1) = listed.brand_key || ' '
          AND substr(listed.name_key, length(listed.brand_key) + 2) LIKE {PHRASE} || '%%' ESCAPE '\') THEN 1
    ELSE 2 END"""
ORDERS = {
    Sort.RELEVANCE: f"{RANK}, ",
    Sort.NAME: "",
    Sort.PRICE_ASC: "listed.lowest_price NULLS LAST, ",
    Sort.PRICE_DESC: "listed.lowest_price DESC NULLS LAST, ",
    Sort.DISCOUNT: "listed.best_discount_percent DESC NULLS LAST, ",
    Sort.PRICE_PER_ML: "listed.price_per_ml NULLS LAST, ",
}
SUMMARY_COLUMNS = ("product_id, canonical_name, brand, concentration, volume_ml, presentation, lowest_price, "
                   "lowest_price_store, image_url, price_per_ml, best_discount_percent, last_updated")


def list_queries(words: tuple[str, ...], filters: ProductFilters, sort: Sort,
                 extra: tuple[str, ...] = (), order: str | None = None) -> tuple[str, str]:
    """The page query and the count query for these words, filters and order (parameters by name).

    extra: more SQL conditions on p / f; order: an ORDER BY prefix instead of the sort's.
    """
    conditions = ["(%(brand)s::text IS NULL OR lower(f.brand) = lower(%(brand)s::text))", ON_SALE, *extra]
    if filters.min_price is not None:
        conditions.append("lowest.lowest_price >= %(min_price)s")
    if filters.max_price is not None:
        conditions.append("lowest.lowest_price <= %(max_price)s")
    if filters.concentrations:
        conditions.append("p.concentration::text = ANY(%(concentrations)s)")
    if filters.min_volume is not None:
        conditions.append("p.volume_ml >= %(min_volume)s")
    if filters.max_volume is not None:
        conditions.append("p.volume_ml <= %(max_volume)s")
    if filters.genders:
        conditions.append("f.gender::text = ANY(%(genders)s)")
    if filters.stores:
        conditions.append("stats.stores && %(stores)s::text[]")
    keys = f", {_plain('p.canonical_name')} AS name_key, {_plain('f.brand')} AS brand_key" if words else ""
    listed = f"""
WITH offers AS ({OFFERS}), lowest AS ({LOWEST_PRICE}), stats AS ({OFFER_STATS}), image AS ({PRODUCT_IMAGE}),
listed AS (
    SELECT p.product_id, p.canonical_name, f.brand, p.concentration::text AS concentration, p.volume_ml,
           p.presentation::text AS presentation, lowest.lowest_price, lowest.lowest_price_store, image.image_url,
           {PRICE_PER_ML.format(price="lowest.lowest_price")} AS price_per_ml,
           stats.best_discount_percent, stats.last_updated{keys}
    FROM products p
    JOIN fragrances f ON f.fragrance_id = p.fragrance_id
    LEFT JOIN lowest ON lowest.product_id = p.product_id
    LEFT JOIN stats ON stats.product_id = p.product_id
    LEFT JOIN image ON image.product_id = p.product_id
    WHERE {" AND ".join(conditions)}
)"""
    where = f"WHERE {SEARCH}" if words else ""
    page = (f"{listed}\nSELECT {SUMMARY_COLUMNS} FROM listed {where}\n"
            f"ORDER BY {ORDERS[sort] if order is None else order}listed.canonical_name, listed.product_id\n"
            "LIMIT %(limit)s OFFSET %(offset)s")
    count = f"{listed}\nSELECT count(*) AS total FROM listed {where}"
    return page, count


BRANDS = f"""
SELECT f.brand, count(*) AS products
FROM products p
JOIN fragrances f ON f.fragrance_id = p.fragrance_id
WHERE {ON_SALE}
GROUP BY f.brand
ORDER BY lower(f.brand), f.brand
"""

GET_PRODUCT = f"""
SELECT p.product_id, p.fragrance_id, p.canonical_name, f.brand, p.concentration::text AS concentration,
       p.volume_ml, p.presentation::text AS presentation,
       (SELECT rl.image_url
        FROM raw_listings rl
        JOIN stores s ON s.store_id = rl.store_id
        LEFT JOIN current_prices cp ON cp.raw_listing_id = rl.raw_listing_id
        WHERE rl.product_id = p.product_id AND rl.is_active AND rl.image_url IS NOT NULL AND {RESOLVED}
        ORDER BY cp.is_available IS NOT TRUE, cp.price NULLS LAST, s.name, rl.listing_url
        LIMIT 1) AS image_url
FROM products p
JOIN fragrances f ON f.fragrance_id = p.fragrance_id
WHERE p.product_id = %s
"""

CURRENT_PRICES = f"""
SELECT s.name AS store, cp.price, cp.list_price, cp.is_available, rl.listing_url, cp.scraped_at, rl.image_url,
       {PRICE_PER_ML.format(price="cp.price")} AS price_per_ml
FROM current_prices cp
JOIN raw_listings rl ON rl.raw_listing_id = cp.raw_listing_id
JOIN stores s ON s.store_id = cp.store_id
JOIN products p ON p.product_id = cp.product_id
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


# GET /offers: every available current offer with a discount (list price above
# the price), with its product; then every current offer of those products,
# for the market check.
DISCOUNTED_OFFERS = f"""
SELECT cp.raw_listing_id, cp.product_id, p.canonical_name, f.brand, p.volume_ml, s.name AS store, rl.listing_url,
       rl.image_url, cp.price, cp.list_price, cp.is_available, cp.scraped_at
FROM current_prices cp
JOIN raw_listings rl ON rl.raw_listing_id = cp.raw_listing_id
JOIN stores s ON s.store_id = cp.store_id
JOIN products p ON p.product_id = cp.product_id
JOIN fragrances f ON f.fragrance_id = p.fragrance_id
WHERE cp.is_available AND cp.list_price > cp.price AND {RESOLVED}
"""
PRODUCTS_OFFERS = f"""
SELECT cp.raw_listing_id, cp.product_id, s.name AS store, rl.listing_url, cp.price, cp.list_price, cp.is_available,
       cp.scraped_at
FROM current_prices cp
JOIN raw_listings rl ON rl.raw_listing_id = cp.raw_listing_id
JOIN stores s ON s.store_id = cp.store_id
WHERE cp.product_id = ANY(%s) AND {RESOLVED}
"""
LATEST_READING = "SELECT max(scraped_at) AS latest FROM price_history"

# A retired product ID (database/007) and where it went, following the chain
# when the replacement was retired too (at most RETIREMENT_HOPS: a cycle cannot loop).
# GET /search/semantic: the fragrances closest to the query (cosine similarity on
# fragrances.embedding, the mean of their listings'). Exact, not through the HNSW
# index: "+ 0" keeps the planner from using it, because with its default
# ef_search it returns at most 40 neighbours; with ~2,300 fragrances the exact
# scan takes milliseconds.
SEMANTIC_CANDIDATES = 200
NEAREST_FRAGRANCES = """
SELECT fragrance_id, (1 - (embedding <=> %(vector)s::vector))::float AS similarity
FROM fragrances WHERE embedding IS NOT NULL
ORDER BY (embedding <=> %(vector)s::vector) + 0
LIMIT %(candidates)s
"""
PRODUCT_FRAGRANCES = "SELECT product_id, fragrance_id FROM products WHERE product_id = ANY(%s)"

RETIREMENT_HOPS = 20
RETIREMENT = f"""
WITH RECURSIVE chain AS (
    SELECT product_id, replaced_by, 1 AS hops FROM retired_products WHERE product_id = %(product_id)s
    UNION ALL
    SELECT r.product_id, r.replaced_by, chain.hops + 1
    FROM retired_products r JOIN chain ON r.product_id = chain.replaced_by
    WHERE chain.hops < {RETIREMENT_HOPS}
)
SELECT chain.replaced_by, EXISTS (SELECT 1 FROM products p WHERE p.product_id = chain.replaced_by) AS exists
FROM chain ORDER BY chain.hops DESC LIMIT 1
"""

# The verified offers change once a day, when a run loads new prices: they are
# kept per window until price_history has a newer reading.
_offers_cache: dict[int, tuple[object, list[VerifiedOffer]]] = {}


class PostgresProductRepository:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection  # rows as dicts (the pool sets dict_row)

    def list_products(self, brand: str | None, limit: int, offset: int, words: tuple[str, ...] = (),
                      filters: ProductFilters | None = None,
                      sort: Sort | None = None) -> tuple[list[ProductSummary], int]:
        filters = filters or ProductFilters()
        sort = sort or (Sort.RELEVANCE if words else Sort.NAME)
        if sort is Sort.RELEVANCE and not words:
            sort = Sort.NAME  # nothing to rank by
        params = {"brand": brand, "limit": limit, "offset": offset, **asdict(filters)}
        params |= {key: list(value) for key, value in params.items() if isinstance(value, tuple)}
        if words:
            patterns = [like_escape(word) for word in words]
            params |= {"words": patterns, "phrase": " ".join(patterns)}
        page, count = list_queries(words, filters, sort)
        rows = self.connection.execute(page, params).fetchall()
        total = self.connection.execute(count, params).fetchone()["total"]
        return [ProductSummary(**row) for row in rows], total

    def list_brands(self) -> list[BrandCount]:
        return [BrandCount(**row) for row in self.connection.execute(BRANDS).fetchall()]

    def list_offers(self, window_days: int, stores: tuple[str, ...], brand: str | None, limit: int,
                    offset: int) -> tuple[list[VerifiedOffer], int]:
        offers = [o for o in self._verified_offers(window_days)
                  if (not stores or o.store in stores) and (brand is None or o.brand.lower() == brand.lower())]
        return offers[offset:offset + limit], len(offers)

    def _verified_offers(self, window_days: int) -> list[VerifiedOffer]:
        """Every discount whose list price the listing's own history supports, largest in pesos first."""
        latest = self.connection.execute(LATEST_READING).fetchone()["latest"]
        cached = _offers_cache.get(window_days)
        if cached and cached[0] == latest:
            return cached[1]
        discounted = self.connection.execute(DISCOUNTED_OFFERS).fetchall()
        readings: dict[UUID, list[Reading]] = {}
        for listing_id, group in groupby(self.connection.execute(
                OFFER_READINGS, ([row["raw_listing_id"] for row in discounted],)).fetchall(),
                key=lambda r: r["raw_listing_id"]):
            readings[listing_id] = [_reading(r) for r in group]
        by_product: dict[UUID, list[Offer]] = {}
        for row in self.connection.execute(PRODUCTS_OFFERS, (list({r["product_id"] for r in discounted}),)).fetchall():
            by_product.setdefault(row["product_id"], []).append(Offer(row["store"], row["listing_url"], _reading(row), ()))
        verified = []
        for row in discounted:
            offer = Offer(row["store"], row["listing_url"], _reading(row), tuple(readings.get(row["raw_listing_id"], ())))
            history = check_history(offer, window_days)
            if history.status is not HistoryStatus.CONSISTENT:
                continue
            market = check_market(offer, by_product.get(row["product_id"], []))
            amount = int(row["list_price"]) - int(row["price"])
            verified.append(VerifiedOffer(
                product_id=row["product_id"], canonical_name=row["canonical_name"], brand=row["brand"],
                volume_ml=row["volume_ml"], store=row["store"], listing_url=row["listing_url"],
                image_url=row["image_url"], price=int(row["price"]), list_price=int(row["list_price"]),
                discount_amount=amount, discount_percent=round(100 * amount / int(row["list_price"]), 1),
                scraped_at=row["scraped_at"], vs_history=HistoryCheck(**asdict(history)),
                vs_market=MarketCheck(**{**asdict(market), "reference_stores": list(market.reference_stores)}),
            ))
        verified.sort(key=lambda o: (-o.discount_amount, -o.discount_percent, o.canonical_name, o.listing_url))
        _offers_cache[window_days] = (latest, verified)
        return verified

    def get_variants(self, product_id: UUID) -> list[ProductSummary] | None:
        product = self.connection.execute(GET_PRODUCT, (product_id,)).fetchone()
        if product is None:
            return None
        page, _ = list_queries((), ProductFilters(), Sort.NAME,
                               extra=("p.fragrance_id = %(fragrance_id)s", "p.product_id <> %(product_id)s"),
                               order="listed.presentation, listed.volume_ml, ")
        params = {"brand": None, "limit": 100, "offset": 0, "fragrance_id": product["fragrance_id"],
                  "product_id": product_id}
        return [ProductSummary(**row) for row in self.connection.execute(page, params).fetchall()]

    def get_product(self, product_id: UUID) -> ProductDetail | None:
        product = self.connection.execute(GET_PRODUCT, (product_id,)).fetchone()
        if product is None:
            return None
        prices = [StorePrice(**row) for row in self.connection.execute(CURRENT_PRICES, (product_id,)).fetchall()]
        product.pop("fragrance_id")
        return ProductDetail(**product, prices=prices, last_updated=max((p.scraped_at for p in prices), default=None))

    def semantic_search(self, vector: list[float], limit: int,
                        filters: ProductFilters | None = None) -> list[tuple[ProductSummary, float]]:
        nearest = {row["fragrance_id"]: row["similarity"] for row in self.connection.execute(
            NEAREST_FRAGRANCES, {"vector": "[" + ",".join(f"{v:.7f}" for v in vector) + "]",
                                 "candidates": SEMANTIC_CANDIDATES}).fetchall()}
        if not nearest:
            return []
        filters = filters or ProductFilters()
        page, _ = list_queries((), filters, Sort.NAME, extra=("p.fragrance_id = ANY(%(fragrance_ids)s)",))
        params = {"brand": None, "limit": 10_000, "offset": 0, "fragrance_ids": list(nearest), **asdict(filters)}
        params |= {key: list(value) for key, value in params.items() if isinstance(value, tuple)}
        products = [ProductSummary(**row) for row in self.connection.execute(page, params).fetchall()]
        fragrance_of = {row["product_id"]: row["fragrance_id"] for row in self.connection.execute(
            PRODUCT_FRAGRANCES, ([p.product_id for p in products],)).fetchall()}
        ranked = sorted(((p, round(nearest[fragrance_of[p.product_id]], 4)) for p in products),
                        key=lambda pair: (-pair[1], pair[0].canonical_name, str(pair[0].product_id)))
        return ranked[:limit]

    def get_retirement(self, product_id: UUID) -> tuple[bool, UUID | None]:
        row = self.connection.execute(RETIREMENT, {"product_id": product_id}).fetchone()
        if row is None:
            return False, None
        return True, row["replaced_by"] if row["exists"] else None

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
