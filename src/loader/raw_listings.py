"""Load scraper JSON snapshots into raw_listings and price_history.

Usage:
    python -m src.loader.raw_listings                 # latest finished file per store
    python -m src.loader.raw_listings artifacts/raw/maicao_....json
    python -m src.loader.raw_listings --deactivate-missing ...

A finished scrape ("done") is loaded in full. An unfinished one (killed by a
timeout, crashed) only adds prices for listings already known: its product
attributes may be half-enriched, so they are not trusted.

With --deactivate-missing, listings of the store that are not in the file
become inactive, but only when the scrape is complete: it ended cleanly (the
store's catalog was exhausted) and it has the whole catalog. For Preunic that
means exactly as many listings as the product total its category page shows;
for other stores, at least MIN_COVERAGE of the store's active listings.
Otherwise nothing is deactivated.
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
# A scrape bringing fewer listings than this share of the store's active ones
# is treated as incomplete (e.g. the site returned a short catalog).
MIN_COVERAGE = 0.8


class ScrapeError(Exception):
    """A scrape file that cannot be loaded."""


def _preunic_stop(pagination: dict) -> tuple[bool, str]:
    # The "load more" button disappears when the whole category is shown.
    if pagination.get("catalog_exhausted") is True:
        return True, "catalog_exhausted"
    return False, "load_more_stopped"


def _maicao_stop(pagination: dict) -> tuple[bool, str]:
    # A page with fewer cards than the page size is the last one.
    reason = pagination.get("stop_reason") or "unknown"
    return reason == "short_page", reason


CLEAN_STOP = {"preunic": _preunic_stop, "maicao": _maicao_stop}


def _matches_site_total(data: dict[str, Any], read: int, active_before: int) -> str | None:
    # Preunic's category page shows its product count: the scrape has the whole
    # catalog only if the listings read are exactly that many.
    total = (data.get("pagination") or {}).get("site_total")
    if total is None:
        return "the page did not show a product total (pagination.site_total)"
    if read != total:
        return f"read {read} listings, the page shows {total}"
    return None


def _covers_active_listings(data: dict[str, Any], read: int, active_before: int) -> str | None:
    # No trustworthy total: compare with what the store had active.
    coverage = read / active_before if active_before else 1.0
    if coverage < MIN_COVERAGE:
        return f"{read} listings = {coverage:.0%} of the {active_before} active (minimum {MIN_COVERAGE:.0%})"
    return None


# Why a cleanly ended scrape still is not the whole catalog (None = it is).
INCOMPLETE_REASON = {"preunic": _matches_site_total}
DEFAULT_INCOMPLETE_REASON = _covers_active_listings


def scrape_stop(data: dict[str, Any]) -> tuple[bool, str]:
    """(ended cleanly, reason) of a scrape file."""
    step = (data.get("progress") or {}).get("step")
    if step != "done":
        return False, f"unfinished:{step or 'unknown'}"
    return CLEAN_STOP[data["store"]](data.get("pagination") or {})

UPSERT_STORE = """
INSERT INTO stores (name, base_url) VALUES (%s, %s)
ON CONFLICT (name) DO UPDATE SET base_url = EXCLUDED.base_url
RETURNING store_id
"""

# Only scraped fields are refreshed; product_id and matching_status belong to
# the matching step and are left untouched. The embedding is computed from
# brand + name, so it is cleared when either changes (the embeddings step
# recomputes it).
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
    is_active            = true,
    embedding            = CASE
        WHEN (raw_listings.raw_name, raw_listings.raw_brand) IS DISTINCT FROM (EXCLUDED.raw_name, EXCLUDED.raw_brand)
        THEN NULL ELSE raw_listings.embedding END
RETURNING raw_listing_id, (xmax = 0) AS inserted
"""

# Unfinished scrapes: only mark known listings as seen, never create or rewrite them.
TOUCH_LISTING = """
UPDATE raw_listings
SET last_seen_at = GREATEST(last_seen_at, %(scraped_at)s), is_active = true
WHERE store_id = %(store_id)s AND listing_url = %(listing_url)s
RETURNING raw_listing_id
"""

COUNT_ACTIVE = "SELECT count(*) FROM raw_listings WHERE store_id = %s AND is_active"

DEACTIVATE_MISSING = """
UPDATE raw_listings SET is_active = false
WHERE store_id = %s AND is_active AND NOT (listing_url = ANY(%s))
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
    raise ScrapeError(f"No finished {store} scrape (progress.step == 'done') in {directory}")


def read_scrape(path: Path, allow_unfinished: bool = False) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ScrapeError(f"{path}: cannot read JSON ({error})") from error
    store = data.get("store")
    if store not in STORES:
        raise ScrapeError(f"{path}: unknown store {store!r}")
    if not allow_unfinished and (data.get("progress") or {}).get("step") != "done":
        raise ScrapeError(f"{path}: scrape did not finish (progress.step != 'done')")
    version = data.get("price_extraction_version", 1)
    if version < PRICE_EXTRACTION_VERSION:
        raise ScrapeError(
            f"{path}: price_extraction_version {version} has unreliable prices; "
            f"re-run the {store} scraper (version {PRICE_EXTRACTION_VERSION}) before loading"
        )
    return data


def pending_files(connection: psycopg.Connection, store: str, directory: Path = RAW_DIRECTORY) -> list[Path]:
    """Scrape files of the store newer than its last loaded price, oldest first.

    Files are loaded in a single transaction each, so "newer than the last
    loaded price" is exactly "not loaded yet". Files without products are skipped.
    """
    last = connection.execute(
        """SELECT max(ph.scraped_at) FROM price_history ph
           JOIN raw_listings rl ON rl.raw_listing_id = ph.raw_listing_id
           JOIN stores s ON s.store_id = rl.store_id WHERE s.name = %s""", (store,)
    ).fetchone()[0]
    pending = []
    for path in directory.glob(f"{store}_*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            scraped_at = datetime.fromisoformat(data["scraped_at"])
        except (OSError, ValueError, KeyError):
            continue
        if data.get("products") and (last is None or scraped_at > last):
            pending.append((scraped_at, path))
    return [path for _, path in sorted(pending)]


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


def load_file(
    connection: psycopg.Connection, path: Path, *, deactivate_missing: bool = False, allow_unfinished: bool = False
) -> dict[str, Any]:
    """Load one scrape file in a single transaction; returns what it did.

    stats["complete"] says whether the scrape covers the store's whole catalog
    (ended cleanly and brought >= MIN_COVERAGE of its active listings).
    """
    data = read_scrape(path, allow_unfinished=allow_unfinished)
    store = data["store"]
    scraped_at = datetime.fromisoformat(data["scraped_at"])
    finished = (data.get("progress") or {}).get("step") == "done"
    listings, problems = convert_products(store, data["products"])
    for problem in problems:
        logger.warning("%s skipped %s", path.name, problem)

    ended_cleanly, stop_reason = scrape_stop(data)
    stats: dict[str, Any] = {
        "file": path.name, "store": store, "scraped_at": scraped_at, "products": len(data["products"]),
        "mode": "full" if finished else "prices_only", "stop_reason": stop_reason, "complete": False,
        "inserted": 0, "updated": 0, "prices_added": 0, "skipped": len(problems), "deactivated": 0, "notes": [],
    }
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(UPSERT_STORE, (store, STORES[store]))
        store_id = cursor.fetchone()[0]
        active_before = cursor.execute(COUNT_ACTIVE, (store_id,)).fetchone()[0]
        incomplete = INCOMPLETE_REASON.get(store, DEFAULT_INCOMPLETE_REASON)(data, len(listings), active_before)
        stats["complete"] = ended_cleanly and incomplete is None
        if not ended_cleanly:
            stats["notes"].append(f"scrape did not end cleanly ({stop_reason})")
        elif incomplete:
            stats["notes"].append(incomplete)
        if not finished:
            stats["notes"].append("unfinished scrape: prices of known listings only")

        for listing in listings:
            if finished:
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
            else:
                row = cursor.execute(TOUCH_LISTING, {"store_id": store_id, "listing_url": listing.listing_url,
                                                     "scraped_at": scraped_at}).fetchone()
                if row is None:  # new listing, attributes not trusted: wait for a finished scrape
                    stats["skipped"] += 1
                    continue
                raw_listing_id = row[0]
                stats["updated"] += 1
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

        if deactivate_missing and stats["complete"]:
            cursor.execute(DEACTIVATE_MISSING, (store_id, [listing.listing_url for listing in listings]))
            stats["deactivated"] = cursor.rowcount
        elif deactivate_missing:
            stats["notes"].append("no listings deactivated")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Load scraper JSON into raw_listings")
    parser.add_argument("files", nargs="*", type=Path,
                        help="JSON files to load (default: latest finished scrape per store)")
    parser.add_argument("--deactivate-missing", action="store_true",
                        help="deactivate listings not in a complete scrape of their store")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        files = args.files or [latest_finished_scrape(store) for store in STORES]
        with psycopg.connect(args.database_url) as connection:
            for path in files:
                stats = load_file(connection, path, deactivate_missing=args.deactivate_missing)
                print(
                    f"{stats['store']:8} {stats['file']}: {stats['products']} products -> "
                    f"{stats['inserted']} new, {stats['updated']} updated listings, "
                    f"{stats['prices_added']} prices, {stats['skipped']} skipped, "
                    f"{stats['deactivated']} deactivated"
                    + (f" ({'; '.join(stats['notes'])})" if stats["notes"] else "")
                )
    except ScrapeError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
