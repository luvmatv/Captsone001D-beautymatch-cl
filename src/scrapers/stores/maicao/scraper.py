from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

from playwright.sync_api import Page, sync_playwright


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
    page_size = 12

    def __init__(self, category_url: str) -> None:
        self.category_url = category_url.rstrip("/") + "/"

    def scrape(self, headless: bool = True) -> dict[str, Any]:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            page = browser.new_page()
            try:
                products, pagination = self._scrape_pages(page)
            finally:
                browser.close()

        return {
            "store": self.store_name,
            "category_url": self.category_url,
            "scraped_at": datetime.now(UTC).isoformat(),
            "pagination": pagination,
            "products": [asdict(product) for product in products],
        }

    def _scrape_pages(self, page: Page) -> tuple[list[ProductRecord], dict[str, Any]]:
        products_by_url: dict[str, ProductRecord] = {}
        offset = 0
        pages_fetched = 0
        site_advertised_last_offset: int | None = None
        last_page_offset = 0
        last_page_count = 0

        while True:
            page_url = self.category_url if offset == 0 else f"{self.category_url}?offset={offset}"
            page.goto(page_url, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            links = page.locator(self.product_selector)
            page_product_count = links.count()
            if page_product_count == 0:
                break

            if pages_fetched == 0:
                site_advertised_last_offset = self._last_offset(page)

            for index in range(page_product_count):
                product = self._product_from_link(links.nth(index), page.url)
                if product.url:
                    products_by_url[product.url] = product

            pages_fetched += 1
            last_page_offset = offset
            last_page_count = page_product_count
            if page_product_count < self.page_size:
                break
            offset += self.page_size

        products = list(products_by_url.values())
        return products, {
            "pages_fetched": pages_fetched,
            "page_size": self.page_size,
            "site_advertised_last_offset": site_advertised_last_offset,
            "site_total_estimate": last_page_offset + last_page_count,
            "final_products": len(products),
            "catalog_exhausted": page_product_count < self.page_size,
        }

    def _product_from_link(self, link: Any, page_url: str) -> ProductRecord:
        card = link.locator("xpath=..")
        brand_locator = card.locator("a[aria-label^='Ver productos de la marca']").first
        brand = brand_locator.text_content()
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
