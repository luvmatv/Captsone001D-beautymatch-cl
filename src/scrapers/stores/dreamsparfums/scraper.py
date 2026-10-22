"""Dreams Parfums (dreamsparfums.cl), a Jumpseller store.

There is no public product API: the scraper reads the catalog listing
(/perfumes?page=N, 30 products a page), which the store renders as plain
HTML. robots.txt allows the listing and its pagination; it disallows search,
filters, sorting and price ranges, which are never used. One fixed user
agent, PAGE_PAUSE_SECONDS between requests.

Stock: the listing shows only products in stock. A product page of one that
is missing from the listing says "OutOfStock" with stock 0 (checked on
2026-10-22 against the sitemap), and each card's quantity selector tops out at
its stock. So every listed product is available, and one that leaves the
listing is out of stock or gone: the loader deactivates it like any listing
missing from a complete scrape, and reactivates it when it comes back. No
product page is opened.

Every page says "31-60 de 573 productos": the total (exclusions included) the
loader compares with the distinct products read. A card the parser cannot
read (no id, URL, name or price) is counted, so a change in the store's
markup leaves the scrape incomplete instead of loading wrong data.

Not loaded, like in the other stores: testers ("TESTER" in the name or the
URL), deodorants and body lotions sold alone, and gift sets with a body
lotion. Sets with a deodorant stay.
"""

from __future__ import annotations

import html
import json
import logging
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from src.scrapers.concentration import extract_concentration
from src.scrapers.prices import PRICE_EXTRACTION_VERSION
from src.scrapers.volume import extract_volume

logger = logging.getLogger(__name__)

BASE_URL = "https://dreamsparfums.cl"
CATALOG_PATH = "/perfumes"    # the store's "Catalogo": every perfume in stock
MAX_PAGES = 100               # 3000 products; 20 pages on 2026-10-22
PAGE_PAUSE_SECONDS = 3
REQUEST_TIMEOUT_SECONDS = 60
REQUEST_ATTEMPTS = 3
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/130.0 Safari/537.36")

CARD = re.compile(r"<article\s+class=\"theme-block product-block[^\"]*\"(.*?)</article>", re.S)
TOTAL = re.compile(r"\d+\s*-\s*\d+\s+de\s+(\d+)\s+productos")
PAGE_LINK = re.compile(r"href=\"/perfumes\?page=(\d+)\"")

TESTER = re.compile(r"\btester\b", re.IGNORECASE)
GIFT_SET = re.compile(r"\b(?:set|estuche|kit)\b|\+", re.IGNORECASE)
DEODORANT = re.compile(r"\bdesodorante\b|\bdeo\b", re.IGNORECASE)
LOTION = re.compile(r"\bloci[oó]n\b|\blotion\b", re.IGNORECASE)


@dataclass
class ProductRecord:
    name: str
    brand: str | None
    current_price: str | None
    previous_price: str | None
    volume: str | None
    concentration: str | None
    url: str | None
    image_url: str | None
    availability: str | None
    # Extra data, not used as prices or attributes:
    sku: str | None = None
    jumpseller_id: str | None = None
    stock: int | None = None  # the quantity selector's maximum: the units in stock


def _first(pattern: str, card: str) -> str | None:
    match = re.search(pattern, card, re.S)
    return " ".join(html.unescape(match.group(1)).split()) if match else None


def parse_card(card: str, base_url: str = BASE_URL) -> dict[str, Any] | None:
    """One listing card -> its fields, or None if a required one (id, URL, name, price) is missing."""
    price = (_first(r"product-block__price--new\">(.*?)<", card)
             or _first(r"class=\"product-block__price\">(.*?)<", card))
    fields = {
        "id": _first(r"data-product-id=\"(\d+)\"", card),
        "path": _first(r"href=\"(/[^\"?#]+)\"\s+class=\"product-block__name\"", card),
        "name": _first(r"class=\"product-block__name\"[^>]*>(.*?)<", card),
        "sku": _first(r"class=\"product-block__sku[^\"]*\">(.*?)<", card),
        "brand": _first(r"class=\"product-block__brand[^\"]*\">(.*?)<", card),
        "price": price.replace(" ", "") if price else None,
        "old_price": (_first(r"product-block__price--old\">(.*?)<", card) or "").replace(" ", "") or None,
        "image": _first(r"<img\s+src=\"(https://[^\"]+)\"\s+class=\"product-block__image\"", card),
        "stock": _first(r"max=\"(\d+)\"", _first(r"(<input[^>]*name=\"qty\"[^>]*>)", card) or ""),
    }
    if not all(fields[key] for key in ("id", "path", "name", "price")):
        return None
    fields["url"] = base_url.rstrip("/") + fields["path"]
    return fields


def exclusion_reason(fields: dict[str, Any]) -> str | None:
    """Why a listed product is not loaded, or None when it is a perfume to load."""
    name, path = fields["name"], fields["path"]
    if TESTER.search(name) or TESTER.search(path.replace("-", " ")):
        return "tester"
    gift_set = bool(GIFT_SET.search(name))
    if DEODORANT.search(name) and not gift_set:
        return "deodorant"
    if LOTION.search(name):
        return "set_with_lotion" if gift_set else "body_lotion"
    return None


def product_record(fields: dict[str, Any]) -> ProductRecord:
    name = fields["name"]
    stock = fields["stock"]
    return ProductRecord(
        name=name,
        brand=fields["brand"],
        current_price=fields["price"],
        previous_price=fields["old_price"],
        volume=extract_volume(name),
        concentration=extract_concentration(name),
        url=fields["url"],
        image_url=fields["image"],
        availability="available",  # the listing shows only products in stock
        sku=fields["sku"],
        jumpseller_id=fields["id"],
        stock=int(stock) if stock else None,
    )


class DreamsparfumsScraper:
    store_name = "dreamsparfums"

    def __init__(self, base_url: str = BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self.catalog_url = f"{self.base_url}{CATALOG_PATH}"

    def scrape(self, headless: bool = True, output_path: Path | None = None) -> dict[str, Any]:
        """Read every page of the catalog listing. headless is accepted for the CLI's sake: no browser is used."""
        result: dict[str, Any] = {
            "store": self.store_name,
            "category_url": self.catalog_url,
            "scraped_at": datetime.now(UTC).isoformat(),
            "price_extraction_version": PRICE_EXTRACTION_VERSION,
            "progress": {},
            "pagination": None,
            "failures": [],
            "products": [],
        }
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT_SECONDS,
                          follow_redirects=True) as client:
            try:
                result["pagination"] = self._walk_pages(client, result, output_path)
            except Exception as error:
                message = str(error).strip().splitlines()[0] if str(error).strip() else ""
                result["failures"].append({"step": result["progress"].get("step"), "url": result["progress"].get("url"),
                                           "error": f"{type(error).__name__}: {message}"[:300]})
                logger.error("failure step=%s error=%s", result["progress"].get("step"), message)
                self._write_snapshot(result, output_path)
                raise
        self._set_step(result, output_path, "done")
        return result

    def _walk_pages(self, client: httpx.Client, result: dict[str, Any], output_path: Path | None) -> dict[str, Any]:
        seen: set[str] = set()
        excluded: Counter = Counter()
        products: list[dict[str, Any]] = []
        unparsed = 0
        site_total, total_pages = None, None
        stop_reason, pages_read, number, empty_page = "max_pages_reached", 0, 1, None
        while number <= MAX_PAGES:
            url = f"{self.catalog_url}?page={number}"
            self._set_step(result, output_path, f"listing:page:{number}", url)
            page = self._get(client, url)
            pages_read += 1
            if number == 1:
                total = TOTAL.search(page)
                site_total = int(total.group(1)) if total else None
                links = [int(n) for n in PAGE_LINK.findall(page)]
                total_pages = max(links) if links else 1
            cards = CARD.findall(page)
            if not cards:
                # before the last page the listing announced: it shrank, or the page failed.
                # Not a clean end: the loader keeps the load partial and deactivates nothing.
                stop_reason, empty_page = "empty_page", number
                logger.warning("empty page %d of %s announced (site_total=%s, products read so far=%d): url=%s",
                               number, total_pages, site_total, len(seen), url)
                break
            for card in cards:
                fields = parse_card(card, self.base_url)
                if fields is None:
                    unparsed += 1
                    continue
                if fields["id"] in seen:
                    continue
                seen.add(fields["id"])
                reason = exclusion_reason(fields)
                if reason:
                    excluded[reason] += 1
                    continue
                products.append(asdict(product_record(fields)))
            result["products"] = products
            if number >= total_pages:
                stop_reason = "all_pages"
                break
            number += 1
            time.sleep(PAGE_PAUSE_SECONDS)
        if unparsed:
            logger.warning("%d cards could not be read (no id, URL, name or price)", unparsed)
        logger.info("pages=%d seen=%d products=%d excluded=%s unparsed=%d site_total=%s stop=%s",
                    pages_read, len(seen), len(products), dict(excluded), unparsed, site_total, stop_reason)
        return {
            "pages_read": pages_read,
            "total_pages": total_pages,
            "stop_reason": stop_reason,
            "empty_page": empty_page,       # the page number that came back empty, if one did
            # a card that could not be read is a product not seen: the counts will not match the total
            "catalog_exhausted": stop_reason == "all_pages",
            "site_total": site_total,       # products the listing reports, exclusions included
            "products_seen": len(seen),     # distinct products read, exclusions included
            "unparsed_cards": unparsed,
            "final_products": len(products),
            "excluded": dict(sorted(excluded.items())),
        }

    @staticmethod
    def _get(client: httpx.Client, url: str) -> str:
        """A listing page's HTML, retrying transient failures."""
        for attempt in range(1, REQUEST_ATTEMPTS + 1):
            try:
                response = client.get(url)
                response.raise_for_status()
                return response.text
            except httpx.HTTPError as error:
                if attempt == REQUEST_ATTEMPTS:
                    raise
                logger.warning("request %s failed (attempt %d): %s", url, attempt, error)
                time.sleep(5 * attempt)
        return ""

    def _set_step(self, result: dict[str, Any], output_path: Path | None, step: str, url: str | None = None) -> None:
        result["progress"] = {"step": step, "url": url, "updated_at": datetime.now(UTC).isoformat()}
        logger.info("step=%s url=%s", step, url or "-")
        self._write_snapshot(result, output_path)

    @staticmethod
    def _write_snapshot(result: dict[str, Any], output_path: Path | None) -> None:
        if not output_path:
            return
        try:
            output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as error:
            logger.warning("could not write snapshot %s: %s", output_path, error)
