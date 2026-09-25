from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from src.scrapers.logging_config import configure_logging
from src.scrapers.stores.preunic.scraper import PreunicScraper

DEFAULT_CATEGORY_URL = "https://preunic.cl/t/perfumes-y-fragancias"


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape a Preunic perfume category")
    parser.add_argument("--category-url", default=DEFAULT_CATEGORY_URL)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    output_directory = Path("artifacts/raw")
    output_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_path = output_directory / f"preunic_{timestamp}.json"
    log_path = output_path.with_suffix(".log")
    configure_logging(log_path)
    print(f"Output: {output_path}")
    print(f"Log: {log_path}")
    result = PreunicScraper(args.category_url).scrape(
        headless=not args.headed, output_path=output_path
    )
    enrichment = result["detail_enrichment"]
    print(f"Scraped {len(result['products'])} products")
    print(
        "Concentration: "
        f"{enrichment['concentration_before']} -> {enrichment['concentration_after']} "
        f"of {enrichment['products_total']} "
        f"(failed={enrichment['failed']}, timed_out={enrichment['timed_out']})"
    )


if __name__ == "__main__":
    main()
