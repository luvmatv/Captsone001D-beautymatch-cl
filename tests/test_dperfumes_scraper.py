"""dperfumes scraper, with real Store API records saved on 2026-10-04 (tests/fixtures/dperfumes; images,
descriptions removed).

Each fixture product carries a "_case" key naming what it represents.
"""

import json
from pathlib import Path

import httpx
import pytest

from src.scrapers.stores.dperfumes import scraper as module
from src.scrapers.stores.dperfumes.scraper import (
    CATEGORIES,
    OUT_OF_STOCK,
    DperfumesScraper,
    exclusion_reason,
    product_from_store_api,
    volume_of,
)

PRODUCTS = json.loads((Path(__file__).parent / "fixtures" / "dperfumes" / "products_selected.json")
                      .read_text(encoding="utf-8"))


def case(name):
    return next(p for p in PRODUCTS if p["_case"] == name)


@pytest.mark.parametrize(("name", "reason"), [
    ("perfume_discounted_in_stock", None),
    ("perfume_without_list_price", None),
    ("perfume_out_of_stock", None),
    ("volume_disagreement", None),
    ("volume_only_in_attribute", None),
    ("concentration_only_in_attribute", None),
    ("brand_with_entity", None),
    ("gift_set", None),               # "Set ... 80 ml + 12.5 ml": gift sets stay
    ("miniatures_set", None),         # "Set Miniaturas ... 5 x 4.5 ml"
    ("set_with_deodorant", None),     # a set that includes a deodorant stays, like in the other stores
    ("refillable_bottle", None),      # "Recargable": the bottle itself
    ("body_mist", None),
    ("tester", "tester"),
    ("refill", "refill"),             # "Recarga": the refill pack
    ("deodorant", "deodorant"),
    ("set_with_lotion", "set_with_lotion"),
    ("soap", "not_a_perfume"),
])
def test_exclusion_reason(name, reason) -> None:
    assert exclusion_reason(case(name)) == reason


def test_decants_are_excluded() -> None:
    # their category was not in the API on 2026-10-04: made-up ones, from a real product
    source = case("perfume_discounted_in_stock")
    assert exclusion_reason(dict(source, name="Decant 1 Million Parfum 10 ml – Rabanne")) == "decant"
    assert exclusion_reason(dict(source, categories=[{"slug": "decants"}])) == "decant"


def test_tester_in_the_url_only() -> None:
    source = case("perfume_discounted_in_stock")
    assert exclusion_reason(dict(source, slug="tester-1-million-parfum-50-ml-rabanne")) == "tester"


def test_discounted_product_converts() -> None:
    product = product_from_store_api(case("perfume_discounted_in_stock"))
    assert product.name == "1 Million Parfum 50 ml – Rabanne"
    assert product.brand == "Rabanne"
    assert (product.current_price, product.previous_price) == ("$85.120", "$112.000")
    assert (product.volume, product.concentration) == ("50 ml", "PARFUM")
    assert product.url == case("perfume_discounted_in_stock")["permalink"]
    assert product.availability == "available"
    assert (product.sku, product.woocommerce_id) == (case("perfume_discounted_in_stock")["sku"], "12822")


def test_without_list_price_and_out_of_stock() -> None:
    assert product_from_store_api(case("perfume_without_list_price")).previous_price is None  # regular = price
    assert product_from_store_api(case("perfume_out_of_stock")).availability == OUT_OF_STOCK


def test_brand_comes_from_the_attribute_unescaped() -> None:
    assert product_from_store_api(case("brand_with_entity")).brand == "Dolce & Gabbana"


def test_volume_is_unknown_when_name_and_attribute_disagree() -> None:
    product = product_from_store_api(case("volume_disagreement"))  # name 25 ml, Formato 125 ml
    assert product.volume is None
    assert product.volume_note == "name says 25 ml, Formato says 125 ml"


@pytest.mark.parametrize(("name", "formats", "expected"), [
    ("Sedley Eau de Parfum 125 ml – Parfums de Marly", ["125 ml"], ("125 ml", None)),
    ("Sedley Eau de Parfum 125 ml – Parfums de Marly", [], ("125 ml", None)),
    ("Vaporizador Globe Trotter Zinc Edition – Maison Francis Kurkdjian", ["11 ml"], ("11 ml", None)),
    ("Set Irresistible Givenchy Eau de Parfum 80 ml + 12.5 ml – Givenchy", ["Set 80 ml + 12.5 ml"], ("80 ml", None)),
    ("Kenzo Homme Sport Extreme Eau de Toilette 50 ml – Kenzo", ["100 ml"],
     (None, "name says 50 ml, Formato says 100 ml")),
])
def test_volume_of(name, formats, expected) -> None:
    assert volume_of(name, formats) == expected


def test_concentration_falls_back_to_the_attribute() -> None:
    assert product_from_store_api(case("concentration_only_in_attribute")).concentration == "EDP"


class FakeScraper(DperfumesScraper):
    """Serves fixture products as Store API pages of a given size, without the network."""

    def __init__(self, pages, total=None, categories=CATEGORIES):
        super().__init__()
        self.pages, self.requested = pages, []
        self.total = sum(len(page) for page in pages) if total is None else total
        self.categories = categories

    def _get(self, client, url):
        self.requested.append(url)
        if url.endswith("/categories"):
            return [{"slug": slug, "id": 100 + i} for i, slug in enumerate(self.categories)], httpx.Headers()
        number = int(url.rsplit("page=", 1)[1])
        headers = httpx.Headers({"X-WP-Total": str(self.total), "X-WP-TotalPages": str(len(self.pages))})
        return (self.pages[number - 1] if number <= len(self.pages) else []), headers


@pytest.fixture(autouse=True)
def no_pause(monkeypatch):
    monkeypatch.setattr(module, "PAGE_PAUSE_SECONDS", 0)


def test_scrape_reads_the_announced_pages_and_counts_the_exclusions(tmp_path) -> None:
    pages = [PRODUCTS[i:i + 10] for i in range(0, len(PRODUCTS), 10)]
    scraper = FakeScraper(pages)
    output = tmp_path / "dperfumes_test.json"
    result = scraper.scrape(output_path=output)

    assert scraper.requested[0].endswith("/categories")
    assert scraper.requested[1].endswith("?category=100,101,102,103&page=1")
    assert len(scraper.requested) == 1 + len(pages)  # no request past the announced last page
    assert not any("per_page" in url for url in scraper.requested)  # disallowed by robots.txt
    pagination = result["pagination"]
    assert (pagination["stop_reason"], pagination["catalog_exhausted"]) == ("all_pages", True)
    assert pagination["site_total"] == pagination["products_seen"] == len(PRODUCTS)
    assert pagination["excluded"] == {"deodorant": 1, "not_a_perfume": 1, "refill": 1, "set_with_lotion": 1,
                                      "tester": 1}
    assert len(result["products"]) == pagination["final_products"] == len(PRODUCTS) - 5
    assert pagination["unknown_volume_disagreement"] == 1
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["progress"]["step"] == "done" and saved["store"] == "dperfumes"


def test_a_product_repeated_across_pages_is_seen_once() -> None:
    result = FakeScraper([PRODUCTS[:3], PRODUCTS[2:5]], total=5).scrape()
    assert result["pagination"]["products_seen"] == 5


def test_an_early_empty_page_is_not_a_clean_stop() -> None:
    # the API announced 3 pages but the second came back empty: the listing shrank mid-scrape
    scraper = FakeScraper([PRODUCTS[:2], [], PRODUCTS[2:4]], total=6)
    pagination = scraper.scrape()["pagination"]
    assert (pagination["stop_reason"], pagination["catalog_exhausted"]) == ("empty_page", False)


def test_a_missing_category_fails_the_scrape(tmp_path) -> None:
    output = tmp_path / "dperfumes_test.json"
    with pytest.raises(ValueError, match="brumas"):
        FakeScraper([PRODUCTS[:2]], categories=CATEGORIES[:-1]).scrape(output_path=output)
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["progress"]["step"] == "listing:categories" and "brumas" in saved["failures"][0]["error"]
