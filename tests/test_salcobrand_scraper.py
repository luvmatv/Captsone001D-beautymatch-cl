"""Salcobrand scraper, with real Algolia data saved from the category page (tests/fixtures/salcobrand)."""

import json
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

import pytest

from src.scrapers.stores.salcobrand.scraper import (
    OUT_OF_STOCK,
    SalcobrandScraper,
    UnexpectedListingFilter,
    clp,
    listing_results,
    product_from_hit,
)

FIXTURES = Path(__file__).parent / "fixtures" / "salcobrand"
PAGE0 = json.loads((FIXTURES / "algolia_multiquery_page0.json").read_text(encoding="utf-8"))
HITS = json.loads((FIXTURES / "algolia_hits_selected.json").read_text(encoding="utf-8"))
CATEGORY = SalcobrandScraper.category_filter


def hit(**match):
    return next(h for h in HITS if all(h.get(k) == v for k, v in match.items()))


def test_listing_results_keep_only_the_category_listing() -> None:
    # The page's multi-query also counts Belleza (3625) and the whole catalog (13108) for its menu
    assert [r["nbHits"] for r in PAGE0["response"]["results"]] == [379, 3625, 13108]
    listing = listing_results(PAGE0["request"], PAGE0["response"], CATEGORY)
    assert len(listing) == 1
    assert (listing[0]["nbHits"], listing[0]["nbPages"], listing[0]["page"], len(listing[0]["hits"])) == (379, 16, 0, 24)


@pytest.mark.parametrize(("body", "data"), [(None, {}), ({}, None), ({"requests": []}, {"results": []})])
def test_listing_results_ignore_unexpected_payloads(body, data) -> None:
    assert listing_results(body, data, CATEGORY) == []


def test_other_categories_are_not_the_listing() -> None:
    assert listing_results(PAGE0["request"], PAGE0["response"], "Belleza > Maquillaje") == []


def multiquery(requests, results):
    """A multi-query body and response: requests as (facetFilters, hitsPerPage, extra params)."""
    body = {"requests": [{"indexName": "sb_variant_production", "params": urlencode(
        {"facetFilters": facets, "hitsPerPage": hits, "page": 0, "filters": "(timestamp_available_on < 1790603684)",
         **extra})} for facets, hits, extra in requests]}
    return body, {"results": results}


# The multi-query the category page sent on 2026-10-04 during the Cyber sale (facetFilters and
# hitsPerPage as observed): the listing itself came filtered by "cyber:Si", 183 of the 419 perfumes.
CYBER_LISTING = multiquery(
    [('[["cyber:Si"],["product_categories.lvl1:Belleza > Perfumes & Fragancias"]]', 24, {}),
     ('[["product_categories.lvl1:Belleza > Perfumes & Fragancias"]]', 0, {}),
     ('[["cyber:Si"],["product_categories.lvl0:Belleza"]]', 0, {}),
     ('[["cyber:Si"]]', 0, {})],
    [{"nbHits": 183, "nbPages": 8, "page": 0, "hits": []}, {"nbHits": 419}, {"nbHits": 2174}, {"nbHits": 0}])


def test_a_listing_filtered_by_more_than_its_category_stops_the_scrape() -> None:
    with pytest.raises(UnexpectedListingFilter, match=r"cyber:Si"):
        listing_results(*CYBER_LISTING, CATEGORY)


@pytest.mark.parametrize("extra", [
    {"facetFilters": '[["brand:Lattafa"],["product_categories.lvl1:Belleza > Perfumes & Fragancias"]]'},
    {"filters": "(timestamp_available_on < 1790603684) AND has_stock:true"},
    {"numericFilters": "normal_price<=20000"},
    {"facetFilters": "product_categories.lvl1:Belleza > Perfumes & Fragancias [["},  # not JSON: unreadable
])
def test_any_other_filter_also_stops_the_scrape(extra) -> None:
    body, data = multiquery([('[["product_categories.lvl1:Belleza > Perfumes & Fragancias"]]', 24, {})],
                            [{"nbHits": 10, "nbPages": 1, "page": 0, "hits": []}])
    params = dict(parse_qsl(body["requests"][0]["params"]))
    body["requests"][0]["params"] = urlencode({**params, **extra})
    with pytest.raises(UnexpectedListingFilter):
        listing_results(body, data, CATEGORY)


def test_the_filter_error_reaches_the_scrape_instead_of_a_warning() -> None:
    class FakePage:
        def wait_for_timeout(self, ms):
            pass

    scraper = SalcobrandScraper("https://salcobrand.cl/t/belleza/perfumes-and-fragancias")
    scraper._listing_error = UnexpectedListingFilter("filtered by cyber:Si")  # as on_response stores it
    with pytest.raises(UnexpectedListingFilter, match="cyber"):
        scraper._wait_for_page(FakePage(), {}, 0)


def test_the_listing_filtered_by_its_category_alone_is_accepted() -> None:
    # the real query of 2026-10-02 (fixture): category facet plus the site's availability window
    assert listing_results(PAGE0["request"], PAGE0["response"], CATEGORY)[0]["nbHits"] == 379


def test_every_hit_of_the_first_page_converts() -> None:
    products = [product_from_hit(h) for h in listing_results(PAGE0["request"], PAGE0["response"], CATEGORY)[0]["hits"]]
    assert all(p.name and p.brand and p.current_price and p.url for p in products)
    assert len({p.url for p in products}) == 24


def test_discounted_price_uses_the_direct_discount_and_keeps_sbpay_apart() -> None:
    source = next(h for h in HITS if h.get("direct_discount") and h.get("direct_discount_sbpay"))
    product = product_from_hit(source)
    assert product.current_price == clp(source["direct_discount"])
    assert product.previous_price == clp(source["normal_price"])
    assert product.sbpay_price == clp(source["direct_discount_sbpay"])  # extra data, never the price
    assert product.current_price != product.sbpay_price


def test_price_without_discount_has_no_list_price() -> None:
    source = next(h for h in HITS if not h.get("direct_discount"))
    product = product_from_hit(source)
    assert (product.current_price, product.previous_price) == (clp(source["normal_price"]), None)


def test_variants_sharing_a_page_get_their_own_url() -> None:
    sisterland = [product_from_hit(h) for h in HITS if h["slug"] == "perfume-benetton-sisterland-edt-80ml"]
    assert len(sisterland) == 3
    assert len({p.url for p in sisterland}) == 3
    assert all(p.url.startswith("https://salcobrand.cl/products/perfume-benetton-sisterland-edt-80ml?default_sku=")
               for p in sisterland)
    # named by scent: volume and concentration come from the slug
    assert {(p.volume, p.concentration) for p in sisterland} == {("80ml", "EDT")}


def test_sets_are_kept_with_the_volume_of_their_name() -> None:
    sets = [product_from_hit(h) for h in HITS if h["options_text"] == "Set"]
    assert sets and all(p.options_text == "Set" for p in sets)
    for product in sets:
        if "ml" in product.name.lower():
            assert product.volume


def test_availability_comes_from_has_stock() -> None:
    source = dict(hit(brand="Banderas"))
    assert product_from_hit(source).availability == "available"
    source["has_stock"] = False
    assert product_from_hit(source).availability == OUT_OF_STOCK


@pytest.mark.parametrize(("amount", "expected"), [
    (19999, "$19.999"), ("15999.0", "$15.999"), (999, "$999"), (None, None), ("", None), (0, None),
])
def test_clp(amount, expected) -> None:
    assert clp(amount) == expected


def test_products_are_deduplicated_across_pages() -> None:
    listing = listing_results(PAGE0["request"], PAGE0["response"], CATEGORY)[0]
    repeated = {0: listing, 1: {"hits": listing["hits"][:5]}}
    assert len(SalcobrandScraper._products(repeated)) == 24
