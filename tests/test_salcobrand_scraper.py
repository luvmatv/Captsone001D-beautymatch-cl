"""Salcobrand scraper, with real Algolia data saved from the category page (tests/fixtures/salcobrand)."""

import json
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

import pytest
from playwright.sync_api import Error as PlaywrightError

from src.scrapers.stores.salcobrand.scraper import (
    CONSENT_BACKDROP,
    OUT_OF_STOCK,
    SalcobrandScraper,
    UnexpectedListingFilter,
    clp,
    dismiss_cookie_notice,
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


class FakeSalePage:
    """A category page: on load the first listing arrives (or a guard error); clicking a label sends the next one."""

    def __init__(self, scraper, pages, on_load, on_click=None):
        self.scraper, self.pages, self.on_load, self.on_click, self.clicks = scraper, pages, on_load, on_click, []

    def goto(self, url, wait_until=None):
        self.on_load(self.scraper, self.pages)

    def wait_for_timeout(self, ms):
        pass


class FakeLabel:
    def __init__(self, page, text):
        self.page, self.text = page, text

    def inner_text(self):
        return self.text

    def click(self):
        self.page.clicks.append(self.text)
        self.page.on_click(self.page.scraper, self.page.pages)


def cyber_listing(scraper, pages):  # what on_response does with the 2026-10-04 multi-query
    try:
        listing_results(*CYBER_LISTING, CATEGORY)
    except UnexpectedListingFilter as error:
        scraper._listing_error = error


def whole_category(scraper, pages):
    pages[0] = {"nbHits": 419, "nbPages": 18, "page": 0, "hits": []}


def open_listing(on_load, on_click=None, sale_labels=("Si\n183",)):
    scraper = SalcobrandScraper("https://salcobrand.cl/t/belleza/perfumes-and-fragancias")
    pages = {}
    page = FakeSalePage(scraper, pages, on_load, on_click)
    scraper._checked_sale_filters = lambda _: [FakeLabel(page, text) for text in sale_labels]
    return scraper, pages, page


def test_the_cyber_filter_is_unchecked_and_the_whole_category_read() -> None:
    scraper, pages, page = open_listing(cyber_listing, whole_category)
    assert scraper._open_listing(page, pages) == ["Si 183"]
    assert page.clicks == ["Si\n183"] and pages[0]["nbHits"] == 419 and scraper._listing_error is None


def test_without_the_cyber_panel_a_filtered_listing_still_stops_the_scrape() -> None:
    scraper, pages, page = open_listing(cyber_listing, sale_labels=())
    with pytest.raises(UnexpectedListingFilter, match="cyber"):
        scraper._open_listing(page, pages)
    assert page.clicks == []


def test_a_listing_without_filters_is_read_as_it_opens() -> None:
    scraper, pages, page = open_listing(whole_category)
    assert scraper._open_listing(page, pages) == [] and page.clicks == []


def test_another_filter_after_unchecking_still_stops_the_scrape() -> None:
    def other_filter(scraper, pages):
        scraper._listing_error = UnexpectedListingFilter("filtered by brand:Lattafa")

    scraper, pages, page = open_listing(cyber_listing, other_filter)
    with pytest.raises(UnexpectedListingFilter, match="Lattafa"):
        scraper._open_listing(page, pages)


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


# --- cookie notice (OneTrust, 2026-11-16: its backdrop took the click on "»" and the scrape stopped on page 1)

REJECT, ACCEPT, CLOSE = "#onetrust-reject-all-handler", "#onetrust-accept-btn-handler", ".onetrust-close-btn-handler"
SETTINGS_REJECT = ".ot-pc-refuse-all-handler"  # inside the settings panel: hidden until it is opened


class FakeElement:
    def __init__(self, page, selector, visible=True):
        self.page, self.selector, self.visible = page, selector, visible

    def is_visible(self):
        return self.visible

    def click(self):
        self.page.clicks.append(self.selector)
        if self.page.click_error:
            raise PlaywrightError(self.page.click_error)
        if self.selector in self.page.buttons:  # any notice button closes the notice
            self.page.notice = False
            for element in self.page.buttons.values():
                element.visible = False


class FakeLocator:
    def __init__(self, elements):
        self.elements = elements

    def count(self):
        return len(self.elements)

    def nth(self, i):
        return self.elements[i]

    @property
    def first(self):
        return self

    @property
    def last(self):
        return FakeLocator(self.elements[-1:])

    def click(self):
        self.elements[0].click()

    def wait_for(self, state=None, timeout=None):
        if self.elements and self.elements[0].page.backdrop_stays:
            raise PlaywrightError("Timeout 5000ms exceeded.")


class FakeConsentPage:
    """A page with the cookie notice showing the given buttons (visible unless listed as hidden)."""

    def __init__(self, visible=(), hidden=(), click_error=None, backdrop_stays=False):
        self.clicks, self.click_error, self.backdrop_stays = [], click_error, backdrop_stays
        self.buttons = {s: FakeElement(self, s) for s in visible}
        self.buttons.update({s: FakeElement(self, s, visible=False) for s in hidden})
        self.notice = bool(visible)
        self.url = "https://salcobrand.cl/t/belleza/perfumes-and-fragancias"

    def locator(self, selector):
        if selector == CONSENT_BACKDROP:
            return FakeLocator([FakeElement(self, selector, visible=self.notice)])
        return FakeLocator([self.buttons[selector]] if selector in self.buttons else [])

    def wait_for_timeout(self, ms):
        pass


def test_the_cookie_notice_is_rejected_when_it_offers_that() -> None:
    page = FakeConsentPage(visible=("#onetrust-pc-btn-handler", REJECT, ACCEPT))
    assert dismiss_cookie_notice(page) == "rejected"
    assert page.clicks == [REJECT] and not page.notice


@pytest.mark.parametrize(("visible", "expected", "clicked"), [
    ((CLOSE, ACCEPT), "closed", CLOSE),  # no reject: close it
    ((ACCEPT,), "accepted", ACCEPT),     # only accept: accept it
])
def test_without_a_reject_option_the_notice_is_closed_or_accepted(visible, expected, clicked) -> None:
    page = FakeConsentPage(visible=visible)
    assert dismiss_cookie_notice(page) == expected
    assert page.clicks == [clicked]


def test_hidden_buttons_of_the_settings_panel_are_not_clicked() -> None:
    page = FakeConsentPage(visible=(ACCEPT,), hidden=(SETTINGS_REJECT, REJECT))
    assert dismiss_cookie_notice(page) == "accepted" and page.clicks == [ACCEPT]


def test_without_the_notice_nothing_is_clicked() -> None:
    page = FakeConsentPage()
    assert dismiss_cookie_notice(page) is None and page.clicks == []


def test_a_notice_that_cannot_be_dismissed_does_not_raise() -> None:
    page = FakeConsentPage(visible=(REJECT,), click_error="Locator.click: Timeout 30000ms exceeded.")
    assert dismiss_cookie_notice(page) is None and page.clicks == [REJECT]


def test_a_backdrop_slow_to_go_is_only_a_warning(caplog) -> None:
    page = FakeConsentPage(visible=(REJECT,), backdrop_stays=True)
    assert dismiss_cookie_notice(page) == "rejected"
    assert "still there" in caplog.text


class FakeCategoryPage(FakeConsentPage):
    """The category: clicking "»" loads the next Algolia page, unless the notice covers the page."""

    def __init__(self, pages, nb_pages, **notice):
        super().__init__(**notice)
        self.pages, self.nb_pages, self.next_clicks = pages, nb_pages, 0
        self.next = FakeElement(self, "text=»")
        self.next.click = self.click_next

    def locator(self, selector):
        return FakeLocator([self.next]) if selector == SalcobrandScraper.next_control else super().locator(selector)

    def click_next(self):
        if self.notice:  # what happened on 2026-11-16
            raise PlaywrightError("Locator.click: Timeout 30000ms exceeded.")
        self.next_clicks += 1
        self.pages[self.next_clicks] = {"nbHits": 3, "nbPages": self.nb_pages, "page": self.next_clicks,
                                        "hits": [{"objectID": self.next_clicks, "name": "x"}]}


def walk(**notice):
    scraper = SalcobrandScraper("https://salcobrand.cl/t/belleza/perfumes-and-fragancias")
    pages = {}
    page = FakeCategoryPage(pages, 3, **notice)

    def open_listing(_page, _pages):
        pages[0] = {"nbHits": 3, "nbPages": 3, "page": 0, "hitsPerPage": 1, "hits": [{"objectID": 0, "name": "x"}]}
        return []

    scraper._open_listing = open_listing
    return scraper._walk_pages(page, pages, {"progress": {}}, None), page


def test_the_notice_is_rejected_before_paging_and_every_page_is_read() -> None:
    pagination, page = walk(visible=("#onetrust-pc-btn-handler", REJECT, ACCEPT))
    assert page.clicks[0] == REJECT and page.next_clicks == 2
    assert pagination["catalog_exhausted"] and pagination["pages_captured"] == 3
    assert pagination["cookie_notice"] == ["rejected"]


def test_without_the_notice_the_pages_are_read_as_before() -> None:
    pagination, page = walk()
    assert page.clicks == [] and pagination["catalog_exhausted"] and pagination["cookie_notice"] == []
