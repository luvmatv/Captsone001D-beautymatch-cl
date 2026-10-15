from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from src.scrapers.logging_config import configure_logging
from src.scrapers.stores.preunic.categories import category_urls
from src.scrapers.stores.preunic.scraper import PreunicScraper


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Preunic's perfume categories (config/scraping.json)")
    parser.add_argument("--category-url", action="append", dest="category_urls", metavar="URL",
                        help="read this category instead of the configured ones (repeat for several)")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--output", type=Path, help="JSON path (default: artifacts/raw/preunic_<timestamp>.json)")
    args = parser.parse_args()

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_path = args.output or Path("artifacts/raw") / f"preunic_{timestamp}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    log_path = output_path.with_suffix(".log")
    configure_logging(log_path)
    print(f"Output: {output_path}")
    print(f"Log: {log_path}")
    urls = args.category_urls or category_urls()
    print(f"Categories: {', '.join(urls)}")
    result = PreunicScraper(urls).scrape(
        headless=not args.headed, output_path=output_path
    )
    enrichment = result["detail_enrichment"]
    print(f"Scraped {len(result['products'])} products")
    print(
        "Concentration: "
        f"{enrichment['concentration_before']} -> {enrichment['concentration_after']} "
        f"of {enrichment['products_total']} "
        f"(not_available={enrichment['not_available']}, "
        f"failed={enrichment['failed']}, timed_out={enrichment['timed_out']})"
    )
    print(f"Detail sources: {enrichment['sources']}")
    print(
        f"Volume: {enrichment['volume_before']} -> {enrichment['volume_after']} "
        f"of {enrichment['products_total']} (not in technical sheet={enrichment['volume_not_available']})"
    )


if __name__ == "__main__":
    main()
