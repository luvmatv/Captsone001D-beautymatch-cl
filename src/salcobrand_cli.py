from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from src.scrapers.logging_config import configure_logging
from src.scrapers.stores.salcobrand.scraper import SalcobrandScraper

DEFAULT_CATEGORY_URL = "https://salcobrand.cl/t/belleza/perfumes-and-fragancias"


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape the Salcobrand perfume catalog")
    parser.add_argument("--category-url", default=DEFAULT_CATEGORY_URL)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--output", type=Path, help="JSON path (default: artifacts/raw/salcobrand_<timestamp>.json)")
    args = parser.parse_args()

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_path = args.output or Path("artifacts/raw") / f"salcobrand_{timestamp}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    log_path = output_path.with_suffix(".log")
    configure_logging(log_path)
    print(f"Output: {output_path}")
    print(f"Log: {log_path}")
    result = SalcobrandScraper(args.category_url).scrape(headless=not args.headed, output_path=output_path)
    pagination = result["pagination"]
    print(f"Scraped {len(result['products'])} products (site total {pagination['site_total']}, "
          f"{pagination['pages_captured']}/{pagination['nb_pages']} pages)")
    print(f"Stop reason: {pagination['stop_reason']}")


if __name__ == "__main__":
    main()
