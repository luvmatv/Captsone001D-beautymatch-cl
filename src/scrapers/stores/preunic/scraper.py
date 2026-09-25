from __future__ import annotations

import asyncio
import json
import logging
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

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_MS = 30000
DETAIL_WAIT_TIMEOUT_MS = 15000
PRODUCT_DEADLINE_SECONDS = 75
PAGE_CLOSE_TIMEOUT_SECONDS = 10
SNAPSHOT_EVERY = 25


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
        result: dict[str, Any] = {
            "store": self.store_name,
            "category_url": self.category_url,
            "scraped_at": datetime.now(UTC).isoformat(),
            "progress": {},
            "pagination": None,
            "detail_enrichment": None,
            "failures": [],
            "products": [],
        }
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            page = browser.new_page()
            page.set_default_timeout(DEFAULT_TIMEOUT_MS)
            page.set_default_navigation_timeout(DEFAULT_TIMEOUT_MS)
            try:
                self._set_step(result, output_path, "listing:goto", self.category_url)
                page.goto(
                    self.category_url,
                    wait_until="domcontentloaded",
                    timeout=DEFAULT_TIMEOUT_MS,
                )
                page.wait_for_timeout(6000)
                self._set_step(result, output_path, "listing:load_more", self.category_url)
                pagination = self._load_all_products(page)
                self._set_step(result, output_path, "listing:extract_cards", self.category_url)
                products = self._extract_products(page)
            except Exception as error:
                self._record_failure(result, result["progress"]["step"], page.url, error)
                self._write_snapshot(result, output_path)
                raise
            finally:
                browser.close()

        concentration_before = sum(1 for product in products if product.concentration)
        result["pagination"] = pagination
        result["products"] = [asdict(product) for product in products]
        result["detail_enrichment"] = {
            "concurrency": 5,
            "products_total": len(products),
            "concentration_before": concentration_before,
            "concentration_after": concentration_before,
            "attempted": sum(
                1 for product in products if not product.concentration and product.url
            ),
            "completed": 0,
            "enriched": 0,
            "failed": 0,
            "timed_out": 0,
        }
        self._set_step(result, output_path, "detail:enrich")
        try:
            asyncio.run(self._enrich_detail_fields(products, result, output_path, headless))
        except KeyboardInterrupt:
            self._finalize(result, products)
            self._set_step(result, output_path, "interrupted")
            raise
        self._finalize(result, products)
        self._set_step(result, output_path, "done")
        return result

    @staticmethod
    def _finalize(result: dict[str, Any], products: list[ProductRecord]) -> None:
        result["products"] = [asdict(product) for product in products]
        result["detail_enrichment"]["concentration_after"] = sum(
            1 for product in products if product.concentration
        )

    def _extract_products(self, page: Page) -> list[ProductRecord]:
        cards = page.locator(self.product_selector)
        logger.info("extracting %d product cards", cards.count())
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
                logger.warning("load_more produced no new products within 10s; stopping")
                break
            after_count = page.locator(self.product_selector).count()
            load_more_clicks += 1
            logger.info("load_more click=%d products=%d", load_more_clicks, after_count)
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
        stats = result["detail_enrichment"]
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=headless)
            context = await browser.new_context()
            context.set_default_timeout(DEFAULT_TIMEOUT_MS)
            context.set_default_navigation_timeout(DEFAULT_TIMEOUT_MS)

            async def read_concentration(
                product: ProductRecord, state: dict[str, Any]
            ) -> str | None:
                state["step"] = "detail:new_page"
                state["page"] = await context.new_page()
                page = state["page"]
                state["step"] = "detail:goto"
                logger.debug("step=%s url=%s", state["step"], product.url)
                await page.goto(
                    product.url, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS
                )
                state["step"] = "detail:wait_description"
                logger.debug("step=%s url=%s", state["step"], product.url)
                description_heading = page.locator(
                    "h2", has_text="Descripción del producto"
                ).first
                await description_heading.wait_for(timeout=DETAIL_WAIT_TIMEOUT_MS)
                state["step"] = "detail:read_description"
                logger.debug("step=%s url=%s", state["step"], product.url)
                description = await description_heading.locator("xpath=..").inner_text(
                    timeout=DEFAULT_TIMEOUT_MS
                )
                return self._extract_concentration(description)

            async def enrich(product: ProductRecord) -> None:
                async with semaphore:
                    state: dict[str, Any] = {"step": "detail:queued", "page": None}
                    try:
                        product.concentration = await asyncio.wait_for(
                            read_concentration(product, state), PRODUCT_DEADLINE_SECONDS
                        )
                        if product.concentration:
                            stats["enriched"] += 1
                    except asyncio.TimeoutError:
                        stats["timed_out"] += 1
                        self._record_failure(
                            result,
                            state["step"],
                            product.url,
                            f"product deadline of {PRODUCT_DEADLINE_SECONDS}s exceeded",
                        )
                    except Exception as error:
                        stats["failed"] += 1
                        self._record_failure(result, state["step"], product.url, error)
                    finally:
                        if state["page"] is not None:
                            try:
                                await asyncio.wait_for(
                                    state["page"].close(), PAGE_CLOSE_TIMEOUT_SECONDS
                                )
                            except Exception as error:
                                logger.warning("page.close failed url=%s: %s", product.url, error)
                        stats["completed"] += 1
                        if (
                            stats["completed"] % SNAPSHOT_EVERY == 0
                            or stats["completed"] == stats["attempted"]
                        ):
                            logger.info(
                                "detail progress %d/%d enriched=%d failed=%d timed_out=%d",
                                stats["completed"],
                                stats["attempted"],
                                stats["enriched"],
                                stats["failed"],
                                stats["timed_out"],
                            )
                            result["products"] = [asdict(item) for item in products]
                            self._write_snapshot(result, output_path)

            try:
                await asyncio.gather(
                    *(
                        enrich(product)
                        for product in products
                        if not product.concentration and product.url
                    )
                )
            finally:
                try:
                    await asyncio.wait_for(context.close(), PAGE_CLOSE_TIMEOUT_SECONDS)
                    await asyncio.wait_for(browser.close(), PAGE_CLOSE_TIMEOUT_SECONDS)
                except Exception as error:
                    logger.warning("browser shutdown failed: %s", error)

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
    def _record_failure(
        result: dict[str, Any], step: str, url: str | None, error: Exception | str
    ) -> None:
        message = str(error).strip().splitlines()[0] if str(error).strip() else ""
        if isinstance(error, Exception):
            message = f"{type(error).__name__}: {message}"
        result["failures"].append({"step": step, "url": url, "error": message[:300]})
        logger.warning("failure step=%s url=%s error=%s", step, url, message[:300])

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
