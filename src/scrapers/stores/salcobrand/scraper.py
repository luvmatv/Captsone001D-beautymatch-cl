"""Salcobrand perfume category.

The category page is rendered from Algolia: for each listing page it sends a
multi-query to the store's index (sb_variant_production), and the response
carries the products as structured records plus the exact category total
(nbHits). The scraper opens the category, walks it with the page's own "»"
control and listens to those responses. It sends no queries of its own.

robots.txt allows /t/ and /products/ (it disallows /api/, cart, checkout and
account pages, which are not used).
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

from playwright.sync_api import Page, sync_playwright

from src.scrapers.concentration import extract_concentration
from src.scrapers.prices import PRICE_EXTRACTION_VERSION, clp
from src.scrapers.volume import extract_volume

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_MS = 30000
PAGE_WAIT_SECONDS = 20     # for the Algolia response of a page
PAGE_PAUSE_MS = 3000       # between pages: the same pace as the Maicao scraper
BASE_URL = "https://salcobrand.cl"
OUT_OF_STOCK = "Sin stock online"  # same availability text the loader already knows


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
    options_text: str | None = None
    sbpay_price: str | None = None  # price paying with the store's own card (SBPay)
    algolia_object_id: str | None = None


class UnexpectedListingFilter(RuntimeError):
    """The category listing came filtered by more than its category: reading it would miss products."""


# The availability window the site adds to every query; the only filter besides the category.
AVAILABILITY_FILTER = re.compile(r"^\(timestamp_available_on < \d+\)$")


def _extra_filters(params: dict[str, str], category: str) -> list[str]:
    """The filters of a listing query other than its category (empty: the whole category)."""
    try:
        facets = json.loads(params.get("facetFilters") or "[]")
        flat = [f for group in facets for f in (group if isinstance(group, list) else [group])]
    except (ValueError, TypeError):
        return [f"unreadable facetFilters {params.get('facetFilters')!r}"]
    extra = [f for f in flat if f != f"product_categories.lvl1:{category}"]
    if params.get("filters") and not AVAILABILITY_FILTER.match(params["filters"]):
        extra.append(f"filters={params['filters']}")
    extra += [f"{name}={params[name]}" for name in ("numericFilters", "tagFilters") if params.get(name)]
    return extra


def listing_results(request_body: Any, response_data: Any, category: str) -> list[dict[str, Any]]:
    """Results of the listing query in one of the page's Algolia multi-queries.

    The page also sends counting queries (hitsPerPage=0) for the category menu;
    only the one filtered by the category that returns products is the listing.
    It must be filtered by its category alone: during a sale the page opened
    with the listing also filtered by "cyber:Si" (183 of the 419 perfumes,
    2026-10-04), and a complete-looking scrape of it would have deactivated the
    rest. Any other filter raises UnexpectedListingFilter (fail closed).
    """
    if not isinstance(request_body, dict) or not isinstance(response_data, dict):
        return []
    results = []
    for request, result in zip(request_body.get("requests", []), response_data.get("results", [])):
        params = dict(parse_qsl(request.get("params", "")))
        if category in params.get("facetFilters", "") and int(params.get("hitsPerPage") or 0) > 0:
            extra = _extra_filters(params, category)
            if extra:
                raise UnexpectedListingFilter(
                    f"the category listing is filtered by more than its category ({', '.join(extra)}): "
                    "it would not be the whole catalog")
            results.append(result)
    return results


def product_from_hit(hit: dict[str, Any]) -> ProductRecord:
    """One Algolia record -> the product fields shared with the other scrapers."""
    name = (hit.get("name") or "").strip()
    normal_price = hit.get("normal_price")
    discount = hit.get("direct_discount")
    discounted = discount not in (None, "") and normal_price and float(discount) < float(normal_price)
    options_text = (hit.get("options_text") or "").strip() or None
    slug, sku = hit.get("slug"), hit.get("sku")
    # Volume: the variant option ("100ml"), else the name, else the slug; the
    # same fallback for the concentration (Benetton Sisterland variants are
    # named by scent, the slug says "...-edt-80ml").
    slug_words = (slug or "").replace("-", " ")
    volume = extract_volume(options_text) or extract_volume(name) or extract_volume(slug_words)
    return ProductRecord(
        name=name,
        brand=(hit.get("brand") or "").strip() or None,
        current_price=clp(discount if discounted else normal_price),
        previous_price=clp(normal_price) if discounted else None,
        volume=volume,
        concentration=extract_concentration(name) or extract_concentration(slug_words),
        # default_sku tells apart variants that share a product page (3 Sisterland scents)
        url=f"{BASE_URL}/products/{slug}?default_sku={sku}" if slug and sku else None,
        image_url=hit.get("catalog_image_url"),
        availability="available" if hit.get("has_stock") else OUT_OF_STOCK,
        sku=str(sku) if sku is not None else None,
        options_text=options_text,
        sbpay_price=clp(hit.get("direct_discount_sbpay")),
        algolia_object_id=str(hit.get("objectID")) if hit.get("objectID") is not None else None,
    )


class SalcobrandScraper:
    store_name = "salcobrand"
    category_filter = "Belleza > Perfumes & Fragancias"  # product_categories.lvl1 of the listing query
    next_control = "text=»"

    def __init__(self, category_url: str) -> None:
        self.category_url = category_url
        self._listing_error: UnexpectedListingFilter | None = None

    def scrape(self, headless: bool = True, output_path: Path | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "store": self.store_name,
            "category_url": self.category_url,
            "scraped_at": datetime.now(UTC).isoformat(),
            "price_extraction_version": PRICE_EXTRACTION_VERSION,
            "progress": {},
            "pagination": None,
            "failures": [],
            "products": [],
        }
        pages: dict[int, dict[str, Any]] = {}  # Algolia page number -> listing result
        self._listing_error = None

        def on_response(response: Any) -> None:
            if "algolia.net" not in response.url or response.request.method != "POST":
                return
            try:
                found = listing_results(json.loads(response.request.post_data or "{}"), response.json(),
                                        self.category_filter)
            except UnexpectedListingFilter as error:  # stop the scrape (raised by _wait_for_page)
                self._listing_error = error
                return
            except Exception as error:  # body not JSON, or already gone
                logger.warning("unreadable Algolia response: %s", error)
                return
            for listing in found:
                if isinstance(listing.get("page"), int):
                    pages[listing["page"]] = listing

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            page = browser.new_page(locale="es-CL", viewport={"width": 1366, "height": 900})
            page.set_default_timeout(DEFAULT_TIMEOUT_MS)
            page.set_default_navigation_timeout(DEFAULT_TIMEOUT_MS)
            page.on("response", on_response)
            try:
                pagination = self._walk_pages(page, pages, result, output_path)
            except Exception as error:
                message = str(error).strip().splitlines()[0] if str(error).strip() else ""
                result["failures"].append({"step": result["progress"].get("step"), "url": page.url,
                                           "error": f"{type(error).__name__}: {message}"[:300]})
                logger.error("failure step=%s error=%s", result["progress"].get("step"), message)
                self._write_snapshot(result, output_path)
                raise
            finally:
                browser.close()

        result["pagination"] = pagination
        result["products"] = self._products(pages)
        self._set_step(result, output_path, "done")
        return result

    def _walk_pages(self, page: Page, pages: dict[int, dict], result: dict, output_path: Path | None) -> dict:
        self._set_step(result, output_path, "listing:goto", self.category_url)
        page.goto(self.category_url, wait_until="domcontentloaded")
        if not self._wait_for_page(page, pages, 0):
            raise RuntimeError("the category page did not load its Algolia listing")
        first = pages[0]
        nb_pages, site_total = first.get("nbPages") or 0, first.get("nbHits")
        logger.info("category total nbHits=%s in %s pages", site_total, nb_pages)
        stop_reason = "all_pages"
        for number in range(1, nb_pages):
            result["products"] = self._products(pages)
            self._set_step(result, output_path, f"listing:page:{number}", page.url)
            page.wait_for_timeout(PAGE_PAUSE_MS)
            control = page.locator(self.next_control).last
            if not control.count():
                stop_reason = "next_control_missing"
                break
            control.click()
            if not self._wait_for_page(page, pages, number):
                stop_reason = "page_did_not_load"
                break
        products = self._products(pages)
        totals = sorted({listing.get("nbHits") for listing in pages.values()})
        exhausted = set(pages) == set(range(nb_pages)) and len(products) == site_total
        if stop_reason == "all_pages" and not exhausted:
            stop_reason = "incomplete"
        logger.info("pages=%d/%d products=%d total=%s stop=%s", len(pages), nb_pages, len(products),
                    site_total, stop_reason)
        return {
            "pages_captured": len(pages),
            "nb_pages": nb_pages,
            "hits_per_page": first.get("hitsPerPage"),
            "stop_reason": stop_reason,
            "site_total": site_total,
            "site_totals_seen": totals,  # more than one: the catalog changed mid-scrape
            "final_products": len(products),
            "catalog_exhausted": stop_reason == "all_pages" and exhausted,
        }

    def _wait_for_page(self, page: Page, pages: dict[int, dict], number: int) -> bool:
        deadline = time.monotonic() + PAGE_WAIT_SECONDS
        while number not in pages and time.monotonic() < deadline:
            if self._listing_error:
                raise self._listing_error
            page.wait_for_timeout(250)
        if self._listing_error:
            raise self._listing_error
        return number in pages

    @staticmethod
    def _products(pages: dict[int, dict]) -> list[dict[str, Any]]:
        seen, products = set(), []
        for number in sorted(pages):
            for hit in pages[number].get("hits", []):
                key = hit.get("objectID")
                if key in seen:
                    continue
                seen.add(key)
                products.append(asdict(product_from_hit(hit)))
        return products

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
