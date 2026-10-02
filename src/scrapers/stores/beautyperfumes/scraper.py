"""Beauty Perfumes (beautyperfumes.cl), a Shopify store.

Shopify publishes the whole catalog as JSON at /products.json, 250 products a
page; a page past the end comes back empty. The scraper reads those pages with
plain HTTP requests (no browser) until the empty one. robots.txt does not
disallow /products.json (it disallows recommendations, sorted and filtered
collections, cart and checkout, which are not used).

The store does not publish a catalog total, so the loader checks completeness
with the empty last page plus the 80 % coverage rule.

Not every product is loaded. Excluded here, so no later step ever sees them:
- testers: "tester" in the title, the product type, the handle or the
  description (no single field marks all of them), or "(T)" in the title,
  which is how the store names some testers (a "(T)" bottle sells below the
  same bottle without it);
- decants (perfume split into a small bottle): none in the catalog on
  2026-10-02, excluded in case they appear;
- deodorants, creams and home fragrances: the other stores are scraped from
  their perfume category, while products.json is the whole catalog;
- bottles sold "sin celofán" (without the factory wrap), cheaper than new ones.
The result counts the exclusions by reason.
"""

from __future__ import annotations

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
from src.scrapers.prices import PRICE_EXTRACTION_VERSION, clp
from src.scrapers.volume import extract_volume

logger = logging.getLogger(__name__)

BASE_URL = "https://beautyperfumes.cl"
PAGE_SIZE = 250            # the most products.json returns per page
MAX_PAGES = 40             # 10 000 products; the catalog had 2379 on 2026-10-02
PAGE_PAUSE_SECONDS = 3     # between pages: the same pace as the other scrapers
REQUEST_TIMEOUT_SECONDS = 30
REQUEST_ATTEMPTS = 3
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/130.0 Safari/537.36")
OUT_OF_STOCK = "Sin stock online"  # same availability text the loader already knows

TESTER = re.compile(r"\btest(?:er)?\b", re.IGNORECASE)
TESTER_SUFFIX = re.compile(r"\(T\)")
DECANT = re.compile(r"\bdecants?\b|\bfraccionad", re.IGNORECASE)
UNWRAPPED = re.compile(r"\bsin\s+celof[aá]n\b", re.IGNORECASE)
OUT_OF_SCOPE_TYPES = frozenset({"desodorante", "crema", "ambiental"})


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
    shopify_id: str | None = None
    product_type: str | None = None


def _description(product: dict[str, Any]) -> str:
    return re.sub(r"<[^>]+>", " ", product.get("body_html") or "")


def exclusion_reason(product: dict[str, Any]) -> str | None:
    """Why a products.json product is not loaded, or None when it is a perfume to load."""
    title = product.get("title") or ""
    fields = (title, product.get("product_type") or "", product.get("handle") or "", _description(product))
    if any(TESTER.search(field) for field in fields) or TESTER_SUFFIX.search(title):
        return "tester"
    if any(DECANT.search(field) for field in fields):
        return "decant"
    if (product.get("product_type") or "").strip().lower() in OUT_OF_SCOPE_TYPES:
        return "not_a_perfume"
    if UNWRAPPED.search(title) or UNWRAPPED.search(_description(product)):
        return "unwrapped"
    return None


def product_from_shopify(product: dict[str, Any]) -> ProductRecord:
    """One products.json product -> the product fields shared with the other scrapers.

    Each product has one variant in this store; with more, the first one is used.
    """
    name = " ".join((product.get("title") or "").split())
    variant = (product.get("variants") or [{}])[0]
    price, list_price = variant.get("price"), variant.get("compare_at_price")
    discounted = list_price not in (None, "") and price not in (None, "") and float(list_price) > float(price)
    images = product.get("images") or []
    handle = product.get("handle")
    return ProductRecord(
        name=name,
        brand=(product.get("vendor") or "").strip() or None,
        current_price=clp(price),
        previous_price=clp(list_price) if discounted else None,
        volume=extract_volume(name),
        concentration=extract_concentration(name),
        url=f"{BASE_URL}/products/{handle}" if handle else None,
        image_url=images[0].get("src") if images else None,
        availability="available" if variant.get("available") else OUT_OF_STOCK,
        sku=(variant.get("sku") or "").strip() or None,
        shopify_id=str(product["id"]) if product.get("id") is not None else None,
        product_type=(product.get("product_type") or "").strip() or None,
    )


class BeautyPerfumesScraper:
    store_name = "beautyperfumes"

    def __init__(self, base_url: str = BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self.catalog_url = f"{self.base_url}/products.json"

    def scrape(self, headless: bool = True, output_path: Path | None = None) -> dict[str, Any]:
        """Read every products.json page. headless is accepted for the CLI's sake: no browser is used."""
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
        with httpx.Client(headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                          timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True) as client:
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
        seen: set[Any] = set()
        excluded: Counter = Counter()
        products: list[dict[str, Any]] = []
        stop_reason, pages_read, multi_variant = "max_pages_reached", 0, 0
        for number in range(1, MAX_PAGES + 1):
            url = f"{self.catalog_url}?limit={PAGE_SIZE}&page={number}"
            self._set_step(result, output_path, f"listing:page:{number}", url)
            batch = self._fetch_page(client, url)
            pages_read += 1
            if not batch:
                stop_reason = "empty_page"
                break
            for product in batch:
                if product.get("id") in seen:
                    continue
                seen.add(product.get("id"))
                reason = exclusion_reason(product)
                if reason:
                    excluded[reason] += 1
                    continue
                multi_variant += len(product.get("variants") or []) > 1
                products.append(asdict(product_from_shopify(product)))
            result["products"] = products
            time.sleep(PAGE_PAUSE_SECONDS)
        logger.info("pages=%d products=%d excluded=%s stop=%s", pages_read, len(products), dict(excluded), stop_reason)
        return {
            "pages_read": pages_read,
            "page_size": PAGE_SIZE,
            "stop_reason": stop_reason,
            "catalog_exhausted": stop_reason == "empty_page",
            "products_seen": len(seen),
            "final_products": len(products),
            "excluded": dict(sorted(excluded.items())),
            "multi_variant_products": multi_variant,
            "site_total": None,  # the store publishes no total: the loader uses the coverage rule
        }

    @staticmethod
    def _fetch_page(client: httpx.Client, url: str) -> list[dict[str, Any]]:
        """The products of one products.json page, retrying transient failures."""
        for attempt in range(1, REQUEST_ATTEMPTS + 1):
            try:
                response = client.get(url)
                response.raise_for_status()
                products = response.json().get("products")
                if not isinstance(products, list):
                    raise ValueError("products.json without a products list")
                return products
            except (httpx.HTTPError, ValueError) as error:
                if attempt == REQUEST_ATTEMPTS:
                    raise
                logger.warning("page %s failed (attempt %d): %s", url, attempt, error)
                time.sleep(PAGE_PAUSE_SECONDS * attempt)
        return []

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
