from __future__ import annotations

import logging
from pathlib import Path


def configure_logging(log_path: Path) -> None:
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    scraper_logger = logging.getLogger("src.scrapers")
    scraper_logger.setLevel(logging.DEBUG)
    scraper_logger.addHandler(console_handler)
    scraper_logger.addHandler(file_handler)
