"""Which Preunic categories the scraper reads: config/scraping.json, not the code.

On 2026-10-14 Preunic split its perfume catalog in two categories (77 + 405
products, none in both). The scraper reads every configured category, each one
checked against its own page total (listing.py), and keeps one product per
listing URL. Changing the list is a config change: edit the file, commit, and
pull it in the production copy.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

CONFIG_PATH = Path(__file__).resolve().parents[4] / "config" / "scraping.json"


def category_urls(path: Path = CONFIG_PATH) -> list[str]:
    """The configured Preunic category URLs, in order and without repeats."""
    try:
        urls = json.loads(path.read_text(encoding="utf-8"))["preunic"]["category_urls"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError(f"{path}: no preunic.category_urls ({error})") from error
    if not isinstance(urls, list) or not urls or not all(isinstance(url, str) and url.startswith("https://")
                                                          for url in urls):
        raise ValueError(f"{path}: preunic.category_urls must be a non-empty list of https URLs")
    return list(dict.fromkeys(url.rstrip("/") for url in urls))


def category_name(url: str) -> str:
    """'https://preunic.cl/t/perfume' -> '/t/perfume' (for notes and logs)."""
    return urlsplit(url).path or url
