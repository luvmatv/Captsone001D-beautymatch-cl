from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

from playwright.sync_api import Page, sync_playwright

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_MS = 30000
MAX_PAGES = 150


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


class MaicaoScraper:
    store_name = "maicao"
    product_selector = "a[href*='/CLMC_']"
    brand_selector = "a[aria-label^='Ver productos de la marca']"
    page_size = 12

    def __init__(self, category_url: str) -> None:
        self.category_url = category_url.rstrip("/") + "/"

    def scrape(
        self, headless: bool = True, output_path: Path | None = None
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "store": self.store_name,
            "category_url": self.category_url,
            "scraped_at": datetime.now(UTC).isoformat(),
            "progress": {},
            "pagination": None,
            "failures": [],
            "products": [],
        }
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            page = browser.new_page()
            page.set_default_timeout(DEFAULT_TIMEOUT_MS)
            page.set_default_navigation_timeout(DEFAULT_TIMEOUT_MS)
            try:
                products, pagination = self._scrape_pages(page, result, output_path)
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
            links = page.locator(self.product_selector)
            page_product_count = links.count()
            if page_product_count == 0:
                stop_reason = "empty_page"
                break

            if pages_fetched == 0:
                site_advertised_last_offset = self._last_offset(page)

            known_before = len(products_by_url)
            for index in range(page_product_count):
                product = self._product_from_link(links.nth(index), page.url)
                if product.url:
                    products_by_url[product.url] = product
            new_products = len(products_by_url) - known_before

            pages_fetched += 1
            last_page_offset = offset
            last_page_count = page_product_count
            logger.info(
                "page offset=%d cards=%d new=%d total=%d",
                offset,
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

    def _product_from_link(self, link: Any, page_url: str) -> ProductRecord:
        card = link.locator("xpath=..")
        brand_locator = card.locator(self.brand_selector).first
        brand = brand_locator.text_content() if brand_locator.count() > 0 else None
        card_text = card.inner_text()
        prices = re.findall(r"\$[\d.]+", card_text)
        product_name = (link.text_content() or "").strip()
        product_url = link.get_attribute("href")
        image_url = self._attribute(card, ["img"], "src") or self._attribute(
            card, ["img"], "data-src"
        )
        previous_price = next(
            (price for price in prices[1:] if price != prices[0]), None
        ) if prices else None
        return ProductRecord(
            name=product_name,
            brand=brand.strip() if brand else None,
            current_price=prices[0] if prices else None,
            previous_price=previous_price,
            volume=self._extract_volume(product_name),
            concentration=self._extract_concentration(product_name),
            url=urljoin(page_url, product_url) if product_url else None,
            image_url=urljoin(page_url, image_url) if image_url else None,
            availability="Sin stock online" if "Sin stock online" in card_text else "available",
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
        if not value:
            return None
        match = re.search(r"\b\d+(?:[.,]\d+)?\s*(?:ml|l|un)\b", value, re.IGNORECASE)
        return match.group(0) if match else None

    @staticmethod
    def _extract_concentration(value: str | None) -> str | None:
        if not value:
            return None
        patterns = (
            (r"\beau\s+de\s+parfum\b", "EDP"),
            (r"\beau\s+de\s+toilette\b", "EDT"),
            (r"\beau\s+de\s+cologne\b", "EDC"),
            (r"\bedp\b", "EDP"),
            (r"\bedt\b", "EDT"),
            (r"\bedc\b", "EDC"),
            (r"\bparfum\b", "PARFUM"),
        )
        for pattern, normalized in patterns:
            if re.search(pattern, value, re.IGNORECASE):
                return normalized
        return None
