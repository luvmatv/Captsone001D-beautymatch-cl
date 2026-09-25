from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from playwright.sync_api import (
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)
from playwright.async_api import async_playwright


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


class PreunicScraper:
    store_name = "preunic"
    product_selector = "a[href^='/products/']"
    load_more_text = "Cargar más productos"

    def __init__(self, category_url: str) -> None:
        self.category_url = category_url

    def scrape(
        self, headless: bool = True, output_path: Path | None = None
    ) -> dict[str, Any]:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            page = browser.new_page()
            try:
                page.goto(self.category_url, wait_until="domcontentloaded")
                page.wait_for_timeout(6000)
                pagination = self._load_all_products(page)
                products = self._extract_products(page)
            finally:
                browser.close()

        result = {
            "store": self.store_name,
            "category_url": self.category_url,
            "scraped_at": datetime.now(UTC).isoformat(),
            "pagination": pagination,
            "detail_enrichment": {
                "concurrency": 5,
                "attempted": sum(
                    1 for product in products if not product.concentration and product.url
                ),
                "completed": 0,
                "enriched": 0,
                "failed": 0,
            },
            "products": [asdict(product) for product in products],
        }
        self._write_snapshot(result, output_path)
        asyncio.run(self._enrich_detail_fields(products, result, output_path, headless))
        self._write_snapshot(result, output_path)
        return result

    def _extract_products(self, page: Page) -> list[ProductRecord]:
        cards = page.locator(self.product_selector)
        if cards.count() > 0:
            return [
                self._product_from_card(cards.nth(index).locator("xpath=.."), page.url)
                for index in range(cards.count())
            ]
        return self._extract_json_ld_products(page)

    def _load_all_products(self, page: Page) -> dict[str, Any]:
        initial_count = page.locator(self.product_selector).count()
        load_more_clicks = 0
        max_loads = 100

        for _ in range(max_loads):
            button = page.get_by_text(self.load_more_text, exact=True)
            if button.count() == 0 or not button.is_visible():
                break

            before_count = page.locator(self.product_selector).count()
            button.dispatch_event("click")
            try:
                page.wait_for_function(
                    "args => document.querySelectorAll(args[0]).length > args[1]",
                    arg=[self.product_selector, before_count],
                    timeout=10000,
                )
            except PlaywrightTimeoutError:
                break
            after_count = page.locator(self.product_selector).count()
            load_more_clicks += 1
            if after_count <= before_count:
                break

        final_count = page.locator(self.product_selector).count()
        return {
            "initial_products": initial_count,
            "load_more_clicks": load_more_clicks,
            "final_products": final_count,
            "catalog_exhausted": page.get_by_text(
                self.load_more_text, exact=True
            ).count() == 0,
        }

    async def _enrich_detail_fields(
        self,
        products: list[ProductRecord],
        result: dict[str, Any],
        output_path: Path | None,
        headless: bool,
    ) -> None:
        semaphore = asyncio.Semaphore(5)
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=headless)
            context = await browser.new_context()

            async def enrich(product: ProductRecord) -> None:
                async with semaphore:
                    page = await context.new_page()
                    try:
                        await page.goto(
                            product.url, wait_until="domcontentloaded", timeout=30000
                        )
                        description_heading = page.locator(
                            "h2", has_text="Descripción del producto"
                        ).first
                        await description_heading.wait_for(timeout=15000)
                        description = await description_heading.locator(
                            "xpath=.."
                        ).inner_text()
                        product.concentration = self._extract_concentration(description)
                        if product.concentration:
                            result["detail_enrichment"]["enriched"] += 1
                    except Exception:
                        result["detail_enrichment"]["failed"] += 1
                    finally:
                        result["detail_enrichment"]["completed"] += 1
                        self._write_snapshot(result, output_path)
                        await page.close()

            await asyncio.gather(
                *(enrich(product) for product in products if not product.concentration and product.url)
            )
            await context.close()
            await browser.close()

    @staticmethod
    def _write_snapshot(result: dict[str, Any], output_path: Path | None) -> None:
        if output_path:
            output_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    def _product_from_card(self, card: Any, page_url: str) -> ProductRecord:
        text_values = [value.strip() for value in card.locator("p").all_text_contents()]
        prices = re.findall(r"\$[\d.]+", card.inner_text())
        product_name = text_values[1] if len(text_values) > 1 else self._text(
            card, ["[itemprop='name']", ".product-name", "h2", "h3"]
        )
        previous_price = next(
            (price for price in prices[1:] if price != prices[0]), None
        ) if prices else None
        product_url = self._attribute(card, ["a[href]"], "href")
        image_url = self._attribute(card, ["img"], "src") or self._attribute(
            card, ["img"], "data-src"
        )
        return ProductRecord(
            name=product_name or "",
            brand=text_values[0] if text_values else None,
            current_price=prices[0] if prices else None,
            previous_price=previous_price,
            volume=self._extract_volume(product_name),
            concentration=self._extract_concentration(product_name),
            url=urljoin(page_url, product_url) if product_url else None,
            image_url=urljoin(page_url, image_url) if image_url else None,
            availability=self._text(
                card, ["[itemprop='availability']", ".availability", ".stock"]
            ),
        )

    def _extract_json_ld_products(self, page: Page) -> list[ProductRecord]:
        products: list[ProductRecord] = []
        for raw_json in page.locator("script[type='application/ld+json']").all_text_contents():
            try:
                data = json.loads(raw_json)
            except json.JSONDecodeError:
                continue
            candidates = data if isinstance(data, list) else [data]
            for candidate in candidates:
                if not isinstance(candidate, dict) or candidate.get("@type") != "Product":
                    continue
                offers = candidate.get("offers", {})
                products.append(
                    ProductRecord(
                        name=str(candidate.get("name", "")),
                        brand=self._json_ld_brand(candidate.get("brand")),
                        current_price=self._json_ld_value(offers.get("price")),
                        previous_price=None,
                        volume=None,
                        concentration=None,
                        url=candidate.get("url"),
                        image_url=self._json_ld_image(candidate.get("image")),
                        availability=offers.get("availability"),
                    )
                )
        return products

    @staticmethod
    def _text(container: Any, selectors: list[str]) -> str | None:
        locator = container.locator(", ".join(selectors)).first
        if locator.count() == 0:
            return None
        value = locator.text_content()
        return value.strip() if value else None

    @staticmethod
    def _attribute(container: Any, selectors: list[str], attribute: str) -> str | None:
        locator = container.locator(", ".join(selectors)).first
        if locator.count() == 0:
            return None
        return locator.get_attribute(attribute)

    @staticmethod
    def _json_ld_brand(value: Any) -> str | None:
        if isinstance(value, dict):
            value = value.get("name")
        return str(value) if value else None

    @staticmethod
    def _json_ld_value(value: Any) -> str | None:
        return str(value) if value is not None else None

    @staticmethod
    def _json_ld_image(value: Any) -> str | None:
        if isinstance(value, list):
            return str(value[0]) if value else None
        return str(value) if value else None

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
        concentration_patterns = (
            (r"\beau\s+de\s+parfum\b", "EDP"),
            (r"\beau\s+de\s+toilette\b", "EDT"),
            (r"\beau\s+de\s+cologne\b", "EDC"),
            (r"\bedp\b", "EDP"),
            (r"\bedt\b", "EDT"),
            (r"\bedc\b", "EDC"),
            (r"\bparfum\b", "PARFUM"),
        )
        for pattern, normalized in concentration_patterns:
            if re.search(pattern, value, re.IGNORECASE):
                return normalized
        return None
