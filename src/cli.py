from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from src.scrapers.stores.preunic.scraper import PreunicScraper

DEFAULT_CATEGORY_URL = "https://preunic.cl/t/perfumes-y-fragancias"


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape a Preunic perfume category")
    parser.add_argument("--category-url", default=DEFAULT_CATEGORY_URL)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    result = PreunicScraper(args.category_url).scrape(headless=not args.headed)
    output_directory = Path("artifacts/raw")
    output_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_path = output_directory / f"preunic_{timestamp}.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Scraped {len(result['products'])} products")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()
