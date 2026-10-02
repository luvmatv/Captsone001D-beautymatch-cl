"""Beauty Perfumes scraper, with real products.json records saved on 2026-10-02 (tests/fixtures/beautyperfumes).

Each fixture product carries a "_case" key naming what it represents.
"""

import json
from pathlib import Path

import pytest

from src.scrapers.stores.beautyperfumes import scraper as module
from src.scrapers.stores.beautyperfumes.scraper import (
    OUT_OF_STOCK,
    BeautyPerfumesScraper,
    exclusion_reason,
    product_from_shopify,
)

PRODUCTS = json.loads((Path(__file__).parent / "fixtures" / "beautyperfumes" / "products_selected.json")
                      .read_text(encoding="utf-8"))


def case(name):
    return next(p for p in PRODUCTS if p["_case"] == name)


@pytest.mark.parametrize(("name", "reason"), [
    ("perfume_discounted_in_stock", None),
    ("perfume_without_list_price", None),
    ("perfume_out_of_stock", None),
    ("set", None),
    ("splash", None),
    ("same_bottle_not_tester", None),
    # testers: no single field marks all of them
    ("tester_title", "tester"),              # title and type
    ("tester_title_only", "tester"),         # "... TESTER", type "Perfume"
    ("tester_type_only", "tester"),          # type "Tester", title without the word
    ("tester_handle_only", "tester"),        # handle "...-tester-original"
    ("tester_description_only", "tester"),   # "IMPORTANTE: Tester sin tapa y sin celofán"
    ("tester_t_suffix", "tester"),           # "(T)": the store's own tester mark
    ("deodorant", "not_a_perfume"),
    ("cream", "not_a_perfume"),
    ("home_fragrance", "not_a_perfume"),
    ("unwrapped", "unwrapped"),              # "(SIN CELOFAN)"
])
def test_exclusion_reason(name, reason) -> None:
    assert exclusion_reason(case(name)) == reason


def test_decants_are_excluded() -> None:
    # none in the catalog on 2026-10-02: a made-up one, from a real product
    decant = dict(case("perfume_discounted_in_stock"), title="DOLCE & GABBANA LIGHT BLUE DECANT 10ML EDP (M)")
    assert exclusion_reason(decant) == "decant"


def test_t_suffix_is_only_the_store_mark() -> None:
    # "(T)" must be written like that; a "T" in a name is not a tester mark
    product = dict(case("perfume_discounted_in_stock"), title="TOMMY T GIRL 100ML EDT (M)")
    assert exclusion_reason(product) is None


def test_discounted_product_converts() -> None:
    product = product_from_shopify(case("perfume_discounted_in_stock"))
    assert product.name == "DOLCE & GABBANA LIGHT BLUE 100ML EDP (M) NEW"
    assert product.brand == "Dolce & Gabbana"
    assert (product.current_price, product.previous_price) == ("$69.900", "$79.900")
    assert (product.volume, product.concentration) == ("100ML", "EDP")
    assert product.url == f"https://beautyperfumes.cl/products/{case('perfume_discounted_in_stock')['handle']}"
    assert product.availability == "available"
    assert product.image_url and product.shopify_id


def test_without_list_price_and_out_of_stock() -> None:
    product = product_from_shopify(case("perfume_without_list_price"))
    assert (product.current_price, product.previous_price) == ("$15.900", None)
    assert product.availability == OUT_OF_STOCK


def test_list_price_not_above_the_price_is_not_a_discount() -> None:
    source = case("perfume_discounted_in_stock")
    same = dict(source, variants=[dict(source["variants"][0], compare_at_price=source["variants"][0]["price"])])
    assert product_from_shopify(same).previous_price is None


class FakeScraper(BeautyPerfumesScraper):
    """Serves fixture products as products.json pages, without the network."""

    def __init__(self, pages):
        super().__init__()
        self.pages, self.requested = pages, []

    def _fetch_page(self, client, url):
        self.requested.append(url)
        number = int(url.rsplit("page=", 1)[1])
        return self.pages[number - 1] if number <= len(self.pages) else []


@pytest.fixture(autouse=True)
def no_pause(monkeypatch):
    monkeypatch.setattr(module, "PAGE_PAUSE_SECONDS", 0)


def test_scrape_reads_until_the_empty_page_and_counts_the_exclusions(tmp_path) -> None:
    # the first product again on page 2: Shopify can repeat a product across pages
    scraper = FakeScraper([PRODUCTS[:9], PRODUCTS[9:] + PRODUCTS[:1]])
    output = tmp_path / "beautyperfumes_test.json"
    result = scraper.scrape(output_path=output)

    assert len(scraper.requested) == 3 and scraper.requested[-1].endswith("limit=250&page=3")
    pagination = result["pagination"]
    assert (pagination["stop_reason"], pagination["catalog_exhausted"]) == ("empty_page", True)
    assert pagination["products_seen"] == len(PRODUCTS)
    assert pagination["excluded"] == {"not_a_perfume": 3, "tester": 6, "unwrapped": 1}
    assert pagination["site_total"] is None
    loaded = {p["name"] for p in result["products"]}
    assert len(result["products"]) == pagination["final_products"] == 6
    assert "DOLCE & GABBANA LIGHT BLUE CAPRI IN LOVE 100ML EDP (M)" in loaded
    assert not any("TESTER" in name or "(T)" in name for name in loaded)
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["progress"]["step"] == "done" and saved["store"] == "beautyperfumes"


def test_scrape_stops_at_the_page_limit(monkeypatch) -> None:
    monkeypatch.setattr(module, "MAX_PAGES", 2)
    result = FakeScraper([PRODUCTS[:1], PRODUCTS[1:2], PRODUCTS[2:3]]).scrape()
    assert (result["pagination"]["stop_reason"], result["pagination"]["catalog_exhausted"]) == ("max_pages_reached", False)


def test_a_failing_page_is_recorded_and_raised(tmp_path) -> None:
    class Failing(FakeScraper):
        def _fetch_page(self, client, url):
            raise module.httpx.ConnectError("connection refused")

    output = tmp_path / "beautyperfumes_test.json"
    with pytest.raises(module.httpx.ConnectError):
        Failing([]).scrape(output_path=output)
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["progress"]["step"] == "listing:page:1" and "ConnectError" in saved["failures"][0]["error"]
