from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from src.scrapers.concentration import extract_concentration
from src.scrapers.volume import extract_volume
from src.scrapers.prices import CARD_PRICES_JS, PRICE_EXTRACTION_VERSION, pick_prices

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_MS = 30000
MAX_PAGES = 150


def search_total(url: str, data: Any, category_id: str) -> int | None:
    """The category's product count from a product-search response the page requested.

    Every listing page asks the store's search API for its 12 products with
    refine=cgid=<category>; the response carries the category total. Other
    searches (other refinements, recommendations) return None.
    """
    parts = urlparse(url)
    if not parts.path.endswith("/product-search"):
        return None
    if parse_qs(parts.query).get("refine") != [f"cgid={category_id}"]:
        return None
    total = data.get("total") if isinstance(data, dict) else None
    return total if isinstance(total, int) and not isinstance(total, bool) and total >= 0 else None


# Product pages: "/<slug>/CLMC_587292.html", and a few with a numeric id,
# "/perfume-edp-gold-elixir-100ml/580587.html" (2026-09-30: Gold Elixir and
# Absolutely Blue, the 2 of 307 the scraper missed).
PRODUCT_LINK = re.compile(r"/(CLMC_\d+|\d{5,})\.html")
# Tags the product links of the page so a plain CSS selector finds them.
MARK_PRODUCT_LINKS_JS = r"""() => {
    for (const a of document.querySelectorAll("a[href*='.html']")) {
        if (/\/(CLMC_\d+|\d{5,})\.html/.test(a.getAttribute('href'))) a.setAttribute('data-bm-product', '1');
    }
}"""


def unpriced_hits(data: Any) -> set[str]:
    """productIds of a product-search response that come without a price (not on sale yet)."""
    if not isinstance(data, dict):
        return set()
    return {hit.get("productId") for hit in data.get("hits") or []
            if isinstance(hit, dict) and hit.get("productId") and hit.get("price") is None}


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
    volume_source: str | None = None  # "listing_name" or "product_page"


# Product pages show the size in their details as "Contenido: 250 Ml" or
# "Contenido: 80 ml." (individual products; sets usually have no such line).
CONTENIDO = re.compile(r"Contenido:\s*([^\n]+)", re.IGNORECASE)
DETAIL_TIMEOUT_MS = 15000     # wait for the "Contenido:" line on a product page
DETAIL_PAUSE_MS = 1000        # between product pages


def volume_from_product_page(text: str | None) -> str | None:
    """The volume in a product page's "Contenido:" line; None when there is none or it is not a size."""
    match = CONTENIDO.search(text or "")
    return extract_volume(match.group(1)) if match else None


class MaicaoScraper:
    store_name = "maicao"
    product_selector = "a[data-bm-product]"  # set by MARK_PRODUCT_LINKS_JS on each page
    brand_selector = "a[aria-label^='Ver productos de la marca']"
    out_of_stock_text = "Sin stock online"
    # The link's parent only holds brand, name and prices; the stock badge sits
    # higher up. Climb to the largest ancestor that still contains a single SKU.
    product_tile_text_js = r"""link => {
        const skuOf = anchor => (anchor.getAttribute('href').match(/\/(CLMC_\d+|\d{5,})\.html/) || [])[1];
        const sku = skuOf(link);
        let tile = link;
        while (tile.parentElement) {
            const skus = new Set(
                [...tile.parentElement.querySelectorAll("a[data-bm-product]")].map(skuOf)
            );
            if (skus.size !== 1 || !skus.has(sku)) break;
            tile = tile.parentElement;
        }
        return tile.innerText;
    }"""
    page_size = 12

    def __init__(self, category_url: str) -> None:
        self.category_url = category_url.rstrip("/") + "/"
        self.category_id = urlparse(self.category_url).path.strip("/").split("/")[-1]

    def scrape(
        self, headless: bool = True, output_path: Path | None = None
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "store": self.store_name,
            "category_url": self.category_url,
            "scraped_at": datetime.now(UTC).isoformat(),
            "price_extraction_version": PRICE_EXTRACTION_VERSION,
            "progress": {},
            "pagination": None,
            "detail_enrichment": None,
            "failures": [],
            "products": [],
        }
        # Category totals read from the search responses the page itself requests
        # (no extra requests). The loader compares the last one with the products read.
        totals: list[int] = []
        unpriced: set[str] = set()  # listed by the API without a price: not counted in site_total

        def on_response(response: Any) -> None:
            if "/product-search" not in response.url:
                return
            try:
                data = response.json()
                total = search_total(response.url, data, self.category_id)
            except Exception as error:  # body not JSON, or already gone
                logger.warning("unreadable product-search response %s: %s", response.url[:120], error)
                return
            if total is not None:
                totals.append(total)
                unpriced.update(unpriced_hits(data))

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            page = browser.new_page()
            page.set_default_timeout(DEFAULT_TIMEOUT_MS)
            page.set_default_navigation_timeout(DEFAULT_TIMEOUT_MS)
            page.on("response", on_response)
            try:
                products, pagination = self._scrape_pages(page, result, output_path)
                result["detail_enrichment"] = self._volumes_from_product_pages(page, products, result, output_path)
            except Exception as error:
                message = str(error).strip().splitlines()[0] if str(error).strip() else ""
                result["failures"].append(
                    {
                        "step": result["progress"].get("step"),
                        "url": result["progress"].get("url"),
                        "error": f"{type(error).__name__}: {message}"[:300],
                    }
                )
                logger.error(
                    "failure step=%s url=%s error=%s",
                    result["progress"].get("step"),
                    result["progress"].get("url"),
                    message,
                )
                self._write_snapshot(result, output_path)
                raise
            finally:
                browser.close()

        # site_total counts only products on sale (with a price): the loader
        # compares it with the listings read that have a price.
        pagination["site_total_reported"] = totals[-1] if totals else None
        pagination["unpriced_in_api"] = sorted(unpriced)
        pagination["site_total"] = totals[-1] - len(unpriced) if totals else None
        pagination["site_totals_seen"] = sorted(set(totals))  # more than one: the catalog changed mid-scrape
        priced = sum(1 for product in products if product.current_price)
        if not totals:
            logger.warning("category total not captured from the product-search responses")
        elif pagination["site_total"] != priced:
            logger.warning("search API reports %d products with a price (%d listed), %d scraped with a price",
                           pagination["site_total"], totals[-1], priced)
        result["pagination"] = pagination
        result["products"] = [asdict(product) for product in products]
        self._set_step(result, output_path, "done")
        return result

    def _scrape_pages(
        self, page: Page, result: dict[str, Any], output_path: Path | None
    ) -> tuple[list[ProductRecord], dict[str, Any]]:
        products_by_url: dict[str, ProductRecord] = {}
        offset = 0
        pages_fetched = 0
        site_advertised_last_offset: int | None = None
        last_page_offset = 0
        last_page_count = 0
        stop_reason = "max_pages_reached"

        while pages_fetched < MAX_PAGES:
            page_url = self.category_url if offset == 0 else f"{self.category_url}?offset={offset}"
            self._set_step(result, output_path, "listing:goto", page_url)
            page.goto(page_url, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
            page.wait_for_timeout(3000)
            self._set_step(result, output_path, "listing:extract_cards", page_url)
            page.evaluate(MARK_PRODUCT_LINKS_JS)
            links = page.locator(self.product_selector)
            link_count = links.count()
            if link_count == 0:
                stop_reason = "empty_page"
                break

            if pages_fetched == 0:
                site_advertised_last_offset = self._last_offset(page)

            known_before = len(products_by_url)
            page_urls = set()
            for index in range(link_count):
                product = self._product_from_link(links.nth(index), page.url)
                if product.url:
                    products_by_url[product.url] = product
                    page_urls.add(product.url)
            new_products = len(products_by_url) - known_before
            # Each product has two links (image and name): the page is short when
            # it has fewer *products* than the page size, not fewer links.
            page_product_count = len(page_urls)

            pages_fetched += 1
            last_page_offset = offset
            last_page_count = page_product_count
            logger.info(
                "page offset=%d links=%d products=%d new=%d total=%d",
                offset,
                link_count,
                page_product_count,
                new_products,
                len(products_by_url),
            )
            result["products"] = [asdict(product) for product in products_by_url.values()]
            if new_products == 0:
                stop_reason = "no_new_products"
                break
            if page_product_count < self.page_size:
                stop_reason = "short_page"
                break
            offset += self.page_size

        if stop_reason == "max_pages_reached":
            logger.warning("stopped after MAX_PAGES=%d pages", MAX_PAGES)

        products = list(products_by_url.values())
        return products, {
            "pages_fetched": pages_fetched,
            "page_size": self.page_size,
            "max_pages": MAX_PAGES,
            "stop_reason": stop_reason,
            "site_advertised_last_offset": site_advertised_last_offset,
            "site_total_estimate": last_page_offset + last_page_count,
            "final_products": len(products),
            "catalog_exhausted": stop_reason in {"empty_page", "short_page", "no_new_products"},
        }

    def _volumes_from_product_pages(self, page: Page, products: list[ProductRecord], result: dict[str, Any],
                                    output_path: Path | None) -> dict[str, Any]:
        """Like Preunic's technical sheet: visit only the products whose name has no volume
        and read their "Contenido:" line. A page that fails is skipped, not fatal."""
        missing = [product for product in products if not product.volume and product.url]
        stats = {"products_total": len(products), "volume_before": len(products) - len(missing),
                 "attempted": len(missing), "volume_enriched": 0, "volume_not_available": 0, "failed": 0}
        for index, product in enumerate(missing, 1):
            self._set_step(result, output_path, f"detail:volume:{index}/{len(missing)}", product.url)
            try:
                page.goto(product.url, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
                try:
                    page.wait_for_function("() => document.body && /Contenido:/i.test(document.body.innerText)",
                                           timeout=DETAIL_TIMEOUT_MS)
                except PlaywrightTimeoutError:
                    pass  # sets usually have no "Contenido:" line
                volume = volume_from_product_page(page.inner_text("body"))
            except Exception as error:
                stats["failed"] += 1
                logger.warning("product page failed %s: %s", product.url, str(error).splitlines()[0][:150])
                continue
            if volume:
                product.volume, product.volume_source = volume, "product_page"
                stats["volume_enriched"] += 1
            else:
                stats["volume_not_available"] += 1
            page.wait_for_timeout(DETAIL_PAUSE_MS)
        stats["volume_after"] = sum(1 for product in products if product.volume)
        logger.info("product pages: %s", stats)
        return stats

    def _product_from_link(self, link: Any, page_url: str) -> ProductRecord:
        card = link.locator("xpath=..")
        brand_locator = card.locator(self.brand_selector).first
        brand = brand_locator.text_content() if brand_locator.count() > 0 else None
        tile_text = link.evaluate(self.product_tile_text_js)
        current_price, list_price = pick_prices(card.evaluate(CARD_PRICES_JS))
        product_name = (link.text_content() or "").strip()
        product_url = link.get_attribute("href")
        image_url = self._attribute(card, ["img"], "src") or self._attribute(
            card, ["img"], "data-src"
        )
        volume = self._extract_volume(product_name)
        return ProductRecord(
            name=product_name,
            brand=brand.strip() if brand else None,
            current_price=current_price,
            previous_price=list_price,
            volume=volume,
            volume_source="listing_name" if volume else None,
            concentration=self._extract_concentration(product_name),
            url=urljoin(page_url, product_url) if product_url else None,
            image_url=urljoin(page_url, image_url) if image_url else None,
            availability=(
                self.out_of_stock_text if self.out_of_stock_text in tile_text else "available"
            ),
        )

    def _set_step(
        self,
        result: dict[str, Any],
        output_path: Path | None,
        step: str,
        url: str | None = None,
    ) -> None:
        result["progress"] = {
            "step": step,
            "url": url,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        logger.info("step=%s url=%s", step, url or "-")
        self._write_snapshot(result, output_path)

    @staticmethod
    def _write_snapshot(result: dict[str, Any], output_path: Path | None) -> None:
        if not output_path:
            return
        try:
            output_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as error:
            logger.warning("could not write snapshot %s: %s", output_path, error)

    @staticmethod
    def _last_offset(page: Page) -> int | None:
        offsets: list[int] = []
        for href in page.locator("a[href*='offset=']").evaluate_all(
            "elements => elements.map(element => element.href)"
        ):
            value = parse_qs(urlparse(href).query).get("offset", [None])[0]
            if value and value.isdigit():
                offsets.append(int(value))
        return max(offsets) if offsets else None

    @staticmethod
    def _attribute(container: Any, selectors: list[str], attribute: str) -> str | None:
        locator = container.locator(", ".join(selectors)).first
        if locator.count() == 0:
            return None
        return locator.get_attribute(attribute)

    @staticmethod
    def _extract_volume(value: str | None) -> str | None:
        return extract_volume(value)

    @staticmethod
    def _extract_concentration(value: str | None) -> str | None:
        return extract_concentration(value)
