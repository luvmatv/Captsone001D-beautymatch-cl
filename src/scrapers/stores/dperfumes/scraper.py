"""dperfumes (dperfumes.cl), a WooCommerce store.

The WooCommerce Store API (/wp-json/wc/store/v1/products) is public and
returns the catalog as JSON, with the brand, size and concentration as
product attributes. The scraper reads the perfumery categories with plain
HTTP requests (no browser), 10 products a page: robots.txt disallows any URL
with per_page=, so the default page size is used (~160 pages). Out-of-stock
products are included and marked as such.

The API states the total of the requested categories (X-WP-Total header):
the loader treats a scrape as complete only if it saw exactly that many
distinct products (pagination.products_seen, exclusions included).

Not every product is loaded. Excluded here, so no later step ever sees them:
- testers ("Tester" in the name or the URL);
- decants: their category is not in the API on 2026-10-04, excluded in case
  they appear;
- refills ("Recarga"): a refill pack, not the bottle. A "Recargable" bottle
  is the product itself and stays;
- deodorants sold alone (a gift set that includes one stays, like in the
  other stores);
- gift sets with a body lotion;
- soaps sold alone (not a perfume).
The result counts the exclusions by reason.

Brand: the "Marcas" attribute (pa_marcas). Size: the name's and the
"Formato" attribute's; when both are given and disagree (the name says 25 ml
and the attribute 125 ml), the size is unknown.
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

from src.loader.conversions import to_volume_ml
from src.scrapers.concentration import extract_concentration
from src.scrapers.prices import PRICE_EXTRACTION_VERSION, clp
from src.scrapers.volume import extract_volume

logger = logging.getLogger(__name__)

BASE_URL = "https://dperfumes.cl"
API_PATH = "/wp-json/wc/store/v1/products"
# Perfumery categories (slugs). The store also sells hair care, cosmetics,
# home fragrances and accessories, which are not read.
CATEGORIES = ("perfumes", "perfumes-nicho", "sets-de-regalo", "brumas")
MAX_PAGES = 400            # 4000 products; the four categories had 1622 on 2026-10-04
PAGE_PAUSE_SECONDS = 0.5   # each request already takes ~1.8 s on the store's side
REQUEST_TIMEOUT_SECONDS = 60
REQUEST_ATTEMPTS = 3
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/130.0 Safari/537.36")
OUT_OF_STOCK = "Sin stock online"  # same availability text the loader already knows

TESTER = re.compile(r"\btester\b", re.IGNORECASE)
DECANT = re.compile(r"\bdecants?\b", re.IGNORECASE)
REFILL = re.compile(r"\brecarga\b|\brefill\b", re.IGNORECASE)
GIFT_SET = re.compile(r"\b(?:set|cofre|cofe|estuche|kit)\b|\+", re.IGNORECASE)  # "Cofe": the store's typo
DEODORANT = re.compile(r"\bdesodorante\b|\bdeo\b", re.IGNORECASE)
LOTION = re.compile(r"\bloci[oó]n\b|\blotion\b", re.IGNORECASE)
SOAP = re.compile(r"\bjab[oó]n\b", re.IGNORECASE)


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
    woocommerce_id: str | None = None
    categories: list[str] | None = None
    volume_note: str | None = None  # why the volume is unknown, when the sources disagree


def _name(product: dict[str, Any]) -> str:
    return " ".join(html.unescape(product.get("name") or "").split())


def _attribute(product: dict[str, Any], taxonomy: str) -> list[str]:
    for attribute in product.get("attributes") or []:
        if attribute.get("taxonomy") == taxonomy:
            return [html.unescape(term.get("name") or "").strip() for term in attribute.get("terms") or []]
    return []


def exclusion_reason(product: dict[str, Any]) -> str | None:
    """Why a Store API product is not loaded, or None when it is a perfume to load."""
    name = _name(product)
    slug = product.get("slug") or ""
    categories = {category.get("slug") for category in product.get("categories") or []}
    if TESTER.search(name) or TESTER.search(slug.replace("-", " ")):
        return "tester"
    if DECANT.search(name) or any(DECANT.search(category or "") for category in categories):
        return "decant"
    if REFILL.search(name):
        return "refill"
    gift_set = bool(GIFT_SET.search(name))
    if DEODORANT.search(name) and not gift_set:
        return "deodorant"
    if gift_set and LOTION.search(name):
        return "set_with_lotion"
    if SOAP.search(name) and not gift_set:
        return "not_a_perfume"
    return None


def volume_of(name: str, formats: list[str]) -> tuple[str | None, str | None]:
    """(volume, note): the name's size and the Formato attribute's; unknown when both are given and disagree."""
    from_name = extract_volume(name)
    from_attribute = extract_volume(formats[0]) if formats else None
    if from_name and from_attribute and to_volume_ml(from_name) != to_volume_ml(from_attribute):
        return None, f"name says {from_name}, Formato says {formats[0]}"
    return from_name or from_attribute, None


def product_from_store_api(product: dict[str, Any]) -> ProductRecord:
    """One Store API product -> the product fields shared with the other scrapers."""
    name = _name(product)
    prices = product.get("prices") or {}
    price, regular = prices.get("price"), prices.get("regular_price")
    discounted = regular not in (None, "") and price not in (None, "") and int(regular) > int(price)
    volume, note = volume_of(name, _attribute(product, "pa_formato"))
    concentration = extract_concentration(name) or next(
        (found for found in map(extract_concentration, _attribute(product, "pa_concentracion")) if found), None)
    brands = _attribute(product, "pa_marcas")
    images = product.get("images") or []
    return ProductRecord(
        name=name,
        brand=brands[0] if brands else None,
        current_price=clp(price),
        previous_price=clp(regular) if discounted else None,
        volume=volume,
        concentration=concentration,
        url=product.get("permalink"),
        image_url=images[0].get("src") if images else None,
        availability="available" if product.get("is_in_stock") else OUT_OF_STOCK,
        sku=(product.get("sku") or "").strip() or None,
        woocommerce_id=str(product["id"]) if product.get("id") is not None else None,
        categories=sorted(category.get("slug") for category in product.get("categories") or []),
        volume_note=note,
    )


class DperfumesScraper:
    store_name = "dperfumes"

    def __init__(self, base_url: str = BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self.catalog_url = f"{self.base_url}{API_PATH}"

    def scrape(self, headless: bool = True, output_path: Path | None = None) -> dict[str, Any]:
        """Read every page of the perfumery categories. headless is accepted for the CLI's sake: no browser is used."""
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
                category_ids = self._category_ids(client, result, output_path)
                result["pagination"] = self._walk_pages(client, category_ids, result, output_path)
            except Exception as error:
                message = str(error).strip().splitlines()[0] if str(error).strip() else ""
                result["failures"].append({"step": result["progress"].get("step"), "url": result["progress"].get("url"),
                                           "error": f"{type(error).__name__}: {message}"[:300]})
                logger.error("failure step=%s error=%s", result["progress"].get("step"), message)
                self._write_snapshot(result, output_path)
                raise
        self._set_step(result, output_path, "done")
        return result

    def _category_ids(self, client: httpx.Client, result: dict[str, Any], output_path: Path | None) -> str:
        """The IDs of CATEGORIES, comma-separated; fails if one is missing (a renamed category would lose products)."""
        url = f"{self.catalog_url}/categories"
        self._set_step(result, output_path, "listing:categories", url)
        by_slug = {category.get("slug"): category.get("id") for category in self._get(client, url)[0]}
        missing = [slug for slug in CATEGORIES if slug not in by_slug]
        if missing:
            raise ValueError(f"categories not found: {missing}")
        return ",".join(str(by_slug[slug]) for slug in CATEGORIES)

    def _walk_pages(self, client: httpx.Client, category_ids: str, result: dict[str, Any],
                    output_path: Path | None) -> dict[str, Any]:
        seen: set[Any] = set()
        excluded: Counter = Counter()
        products: list[dict[str, Any]] = []
        site_total, total_pages = None, None
        stop_reason, pages_read, number = "max_pages_reached", 0, 1
        while number <= MAX_PAGES:
            url = f"{self.catalog_url}?category={category_ids}&page={number}"
            self._set_step(result, output_path, f"listing:page:{number}", url)
            batch, headers = self._get(client, url)
            pages_read += 1
            if number == 1:
                site_total = _int_header(headers, "x-wp-total")
                total_pages = _int_header(headers, "x-wp-totalpages")
            if not batch:
                stop_reason = "empty_page"  # before the last page the API announced: the listing shrank
                break
            for product in batch:
                if product.get("id") in seen:
                    continue
                seen.add(product.get("id"))
                reason = exclusion_reason(product)
                if reason:
                    excluded[reason] += 1
                    continue
                products.append(asdict(product_from_store_api(product)))
            result["products"] = products
            if total_pages is not None and number >= total_pages:
                stop_reason = "all_pages"
                break
            number += 1
            time.sleep(PAGE_PAUSE_SECONDS)
        logger.info("pages=%d seen=%d products=%d excluded=%s site_total=%s stop=%s",
                    pages_read, len(seen), len(products), dict(excluded), site_total, stop_reason)
        return {
            "pages_read": pages_read,
            "total_pages": total_pages,
            "stop_reason": stop_reason,
            "catalog_exhausted": stop_reason == "all_pages",
            "categories": list(CATEGORIES),
            "site_total": site_total,       # products the API reports for the categories, exclusions included
            "products_seen": len(seen),     # distinct products read, exclusions included
            "final_products": len(products),
            "excluded": dict(sorted(excluded.items())),
            "unknown_volume_disagreement": sum(1 for product in products if product["volume_note"]),
        }

    @staticmethod
    def _get(client: httpx.Client, url: str) -> tuple[list[dict[str, Any]], httpx.Headers]:
        """A JSON list from the Store API and the response headers, retrying transient failures."""
        for attempt in range(1, REQUEST_ATTEMPTS + 1):
            try:
                response = client.get(url)
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, list):
                    raise ValueError("the Store API did not return a list")
                return body, response.headers
            except (httpx.HTTPError, ValueError) as error:
                if attempt == REQUEST_ATTEMPTS:
                    raise
                logger.warning("request %s failed (attempt %d): %s", url, attempt, error)
                time.sleep(5 * attempt)
        return [], httpx.Headers()

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


def _int_header(headers: httpx.Headers, name: str) -> int | None:
    value = headers.get(name)
    return int(value) if value and value.isdigit() else None
