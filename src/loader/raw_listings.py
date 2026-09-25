"""Load scraper JSON snapshots into raw_listings and price_history.

Usage:
    python -m src.loader.raw_listings                 # latest finished file per store
    python -m src.loader.raw_listings artifacts/raw/maicao_....json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg

from src.loader.conversions import Listing, listing_from_product
from src.scrapers.prices import PRICE_EXTRACTION_VERSION

logger = logging.getLogger(__name__)

DEFAULT_DATABASE_URL = "postgresql://postgres:dev@localhost:5432/beautymatch"
RAW_DIRECTORY = Path("artifacts/raw")
STORES = {
    "preunic": "https://preunic.cl",
    "maicao": "https://www.maicao.cl",
}

UPSERT_STORE = """
INSERT INTO stores (name, base_url) VALUES (%s, %s)
ON CONFLICT (name) DO UPDATE SET base_url = EXCLUDED.base_url
RETURNING store_id
"""

# Only scraped fields are refreshed; product_id, matching_status and embedding
# belong to the matching step and are left untouched.
UPSERT_LISTING = """
INSERT INTO raw_listings (
    store_id, store_sku, listing_url, raw_name, raw_brand,
    parsed_concentration, parsed_volume_ml, first_seen_at, last_seen_at
)
VALUES (
    %(store_id)s, %(store_sku)s, %(listing_url)s, %(raw_name)s, %(raw_brand)s,
    %(parsed_concentration)s::concentration_type, %(parsed_volume_ml)s,
    %(scraped_at)s, %(scraped_at)s
)
ON CONFLICT (store_id, listing_url) DO UPDATE SET
    store_sku            = EXCLUDED.store_sku,
    raw_name             = EXCLUDED.raw_name,
    raw_brand            = EXCLUDED.raw_brand,
    parsed_concentration = EXCLUDED.parsed_concentration,
    parsed_volume_ml     = EXCLUDED.parsed_volume_ml,
    first_seen_at        = LEAST(raw_listings.first_seen_at, EXCLUDED.first_seen_at),
    last_seen_at         = GREATEST(raw_listings.last_seen_at, EXCLUDED.last_seen_at),
    is_active            = true
RETURNING raw_listing_id, (xmax = 0) AS inserted
"""

# One price row per listing per scrape; reloading the same file adds nothing.
INSERT_PRICE = """
INSERT INTO price_history (raw_listing_id, price, list_price, currency, is_available, scraped_at)
SELECT %(raw_listing_id)s, %(price)s, %(list_price)s, 'CLP', %(is_available)s, %(scraped_at)s
WHERE NOT EXISTS (
    SELECT 1 FROM price_history
    WHERE raw_listing_id = %(raw_listing_id)s AND scraped_at = %(scraped_at)s
)
"""


def latest_finished_scrape(store: str, directory: Path = RAW_DIRECTORY) -> Path:
    for path in sorted(directory.glob(f"{store}_*.json"), reverse=True):
        data = json.loads(path.read_text(encoding="utf-8"))
        if (data.get("progress") or {}).get("step") == "done":
            return path
    raise SystemExit(f"No finished {store} scrape (progress.step == 'done') in {directory}")


def read_scrape(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    store = data.get("store")
    if store not in STORES:
        raise SystemExit(f"{path}: unknown store {store!r}")
    if (data.get("progress") or {}).get("step") != "done":
        raise SystemExit(f"{path}: scrape did not finish (progress.step != 'done')")
    version = data.get("price_extraction_version", 1)
    if version < PRICE_EXTRACTION_VERSION:
        raise SystemExit(
            f"{path}: price_extraction_version {version} has unreliable prices; "
            f"re-run the {store} scraper (version {PRICE_EXTRACTION_VERSION}) before loading"
        )
    return data


def convert_products(
    store: str, products: list[dict[str, Any]]
) -> tuple[list[Listing], list[str]]:
    listings: dict[str, Listing] = {}
    problems: list[str] = []
    for product in products:
        if not product.get("url") or not (product.get("name") or "").strip():
            problems.append(f"missing url/name: {product.get('url') or product.get('name')!r}")
            continue
        try:
            listing = listing_from_product(store, product)
        except ValueError as error:
            problems.append(f"{product['url']}: {error}")
            continue
        listings[listing.listing_url] = listing  # listing pages can repeat a product
    return list(listings.values()), problems


def load_file(connection: psycopg.Connection, path: Path) -> dict[str, Any]:
    data = read_scrape(path)
    store = data["store"]
    scraped_at = datetime.fromisoformat(data["scraped_at"])
    listings, problems = convert_products(store, data["products"])
    for problem in problems:
        logger.warning("%s skipped %s", path.name, problem)

    stats = {"file": path.name, "store": store, "products": len(data["products"]),
             "inserted": 0, "updated": 0, "prices_added": 0, "skipped": len(problems)}
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(UPSERT_STORE, (store, STORES[store]))
        store_id = cursor.fetchone()[0]
        for listing in listings:
            cursor.execute(
                UPSERT_LISTING,
                {
                    "store_id": store_id,
                    "store_sku": listing.store_sku,
                    "listing_url": listing.listing_url,
                    "raw_name": listing.raw_name,
                    "raw_brand": listing.raw_brand,
                    "parsed_concentration": listing.parsed_concentration,
                    "parsed_volume_ml": listing.parsed_volume_ml,
                    "scraped_at": scraped_at,
                },
            )
            raw_listing_id, inserted = cursor.fetchone()
            stats["inserted" if inserted else "updated"] += 1
            if listing.price is None:
                continue
            cursor.execute(
                INSERT_PRICE,
                {
                    "raw_listing_id": raw_listing_id,
                    "price": listing.price,
                    "list_price": listing.list_price,
                    "is_available": listing.is_available,
                    "scraped_at": scraped_at,
                },
            )
            stats["prices_added"] += cursor.rowcount
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Load scraper JSON into raw_listings")
    parser.add_argument("files", nargs="*", type=Path,
                        help="JSON files to load (default: latest finished scrape per store)")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    files = args.files or [latest_finished_scrape(store) for store in STORES]
    with psycopg.connect(args.database_url) as connection:
        for path in files:
            stats = load_file(connection, path)
            print(
                f"{stats['store']:8} {stats['file']}: {stats['products']} products -> "
                f"{stats['inserted']} new, {stats['updated']} updated listings, "
                f"{stats['prices_added']} prices, {stats['skipped']} skipped"
            )


if __name__ == "__main__":
    main()
