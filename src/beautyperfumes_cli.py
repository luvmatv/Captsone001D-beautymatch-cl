from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from src.scrapers.logging_config import configure_logging
from src.scrapers.stores.beautyperfumes.scraper import BASE_URL, BeautyPerfumesScraper


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape the Beauty Perfumes catalog (Shopify products.json)")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--headed", action="store_true", help="accepted like the other scrapers; no browser is used")
    parser.add_argument("--output", type=Path, help="JSON path (default: artifacts/raw/beautyperfumes_<timestamp>.json)")
    args = parser.parse_args()

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_path = args.output or Path("artifacts/raw") / f"beautyperfumes_{timestamp}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    log_path = output_path.with_suffix(".log")
    configure_logging(log_path)
    print(f"Output: {output_path}")
    print(f"Log: {log_path}")
    result = BeautyPerfumesScraper(args.base_url).scrape(headless=not args.headed, output_path=output_path)
    pagination = result["pagination"]
    print(f"Scraped {len(result['products'])} products ({pagination['products_seen']} in the catalog, "
          f"excluded {pagination['excluded']}, {pagination['pages_read']} pages)")
    print(f"Stop reason: {pagination['stop_reason']}")


if __name__ == "__main__":
    main()
