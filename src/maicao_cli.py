from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from src.scrapers.logging_config import configure_logging
from src.scrapers.stores.maicao.scraper import MaicaoScraper

DEFAULT_CATEGORY_URL = "https://www.maicao.cl/perfumes-y-fragancias/"


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape the Maicao perfume catalog")
    parser.add_argument("--category-url", default=DEFAULT_CATEGORY_URL)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    output_directory = Path("artifacts/raw")
    output_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_path = output_directory / f"maicao_{timestamp}.json"
    log_path = output_path.with_suffix(".log")
    configure_logging(log_path)
    print(f"Output: {output_path}")
    print(f"Log: {log_path}")
    result = MaicaoScraper(args.category_url).scrape(
        headless=not args.headed, output_path=output_path
    )
    print(f"Scraped {len(result['products'])} products")
    print(f"Stop reason: {result['pagination']['stop_reason']}")


if __name__ == "__main__":
    main()
