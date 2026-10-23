"""Dreams Parfums scraper, with real listing cards saved on 2026-10-22 (tests/fixtures/dreamsparfums).

Each fixture card is preceded by a "<!-- case: ... -->" comment naming what it represents.
"""

import re
from pathlib import Path

import pytest

from src.scrapers.stores.dreamsparfums import scraper as module
from src.scrapers.stores.dreamsparfums.scraper import (
    CARD,
    USER_AGENT,
    DreamsparfumsScraper,
    exclusion_reason,
    parse_card,
    product_record,
)

FIXTURE = (Path(__file__).parent / "fixtures" / "dreamsparfums" / "listing_cards.html").read_text(encoding="utf-8")
CASES = {case: card for case, card in re.findall(
    r"<!-- case: (\w+) -->\s*(<article\s+class=\"theme-block product-block[^\"]*\".*?</article>)", FIXTURE, re.S)}


def card(case):
    return CARD.findall(CASES[case])[0]


def test_a_discounted_card_converts() -> None:
    fields = parse_card(card("discounted"))
    product = product_record(fields)
    assert product.name == "212 100 ML EDT CAROLINA HERRERA" and product.brand == "CAROLINA HERRERA"
    assert (product.current_price, product.previous_price) == ("$76.630", "$104.990")
    assert (product.volume, product.concentration) == ("100 ML", "EDT")
    assert product.url == "https://dreamsparfums.cl/212-regular-100-ml-edt-de-carolina-herrera"
    assert product.image_url.startswith("https://cdnx.jumpseller.com/")
    assert product.availability == "available"  # the listing shows only products in stock
    assert (product.sku, product.jumpseller_id, product.stock) == ("120030", "30620046", 6)


def test_a_card_without_discount_has_no_list_price() -> None:
    product = product_record(parse_card(card("no_discount")))
    assert product.current_price == "$80.690" and product.previous_price is None


@pytest.mark.parametrize(("case", "reason"), [
    ("discounted", None),
    ("no_discount", None),
    ("set_with_deodorant", None),         # a set that includes a deodorant stays, like in the other stores
    ("tester", "tester"),
    ("tester_url_without_word", "tester"),  # "MOD VANILLA TESTER ...": the URL lacks the word, the name has it
    ("body_lotion", "body_lotion"),
    ("deodorant", "deodorant"),
])
def test_exclusion_reason(case, reason) -> None:
    assert exclusion_reason(parse_card(card(case))) == reason


def test_a_tester_only_in_the_url_and_a_set_with_lotion() -> None:
    fields = parse_card(card("discounted"))
    assert exclusion_reason(dict(fields, path="/212-tester-100-ml-edt-de-carolina-herrera")) == "tester"
    assert exclusion_reason(dict(fields, name="212 100 ML EDT + BODY LOTION 100 ML CAROLINA HERRERA")) == "set_with_lotion"


def test_a_card_missing_a_required_field_is_not_read() -> None:
    broken = card("discounted").replace("product-block__price", "product-block__cost")
    assert parse_card(broken) is None


def page(cards, number, total, last):
    links = " ".join(f'<a href="/perfumes?page={n}">{n}</a>' for n in range(1, last + 1))
    first = (number - 1) * 30 + 1
    return f"<p>{first}-{first + len(cards) - 1} de {total} productos</p><nav>{links}</nav>" + "".join(cards)


class FakeScraper(DreamsparfumsScraper):
    """Serves listing pages built from fixture cards, without the network."""

    def __init__(self, pages, total=None):
        super().__init__()
        self.pages, self.requested = pages, []
        self.total = sum(len(p) for p in pages) if total is None else total

    def _get(self, client, url):
        self.requested.append((url, client.headers.get("user-agent")))
        number = int(url.rsplit("page=", 1)[1])
        cards = self.pages[number - 1] if number <= len(self.pages) else []
        return page(cards, number, self.total, len(self.pages))


@pytest.fixture
def pauses(monkeypatch):
    slept = []
    monkeypatch.setattr(module.time, "sleep", slept.append)
    return slept


ALL_CASES = [CASES[case] for case in CASES]


def test_scrape_reads_every_announced_page_politely(pauses) -> None:
    scraper = FakeScraper([ALL_CASES[:4], ALL_CASES[4:]])
    result = scraper.scrape()
    pagination = result["pagination"]
    assert (pagination["stop_reason"], pagination["catalog_exhausted"]) == ("all_pages", True)
    assert pagination["site_total"] == pagination["products_seen"] == 7
    assert pagination["excluded"] == {"body_lotion": 1, "deodorant": 1, "tester": 2}
    assert len(result["products"]) == pagination["final_products"] == 3
    # only the listing and its pagination, with one fixed user agent and a pause between pages
    assert [url for url, _ in scraper.requested] == ["https://dreamsparfums.cl/perfumes?page=1",
                                                     "https://dreamsparfums.cl/perfumes?page=2"]
    assert {agent for _, agent in scraper.requested} == {USER_AGENT}
    assert not any(word in url for url, _ in scraper.requested for word in ("filter", "sorting", "search", "min=", "max="))
    assert pauses == [module.PAGE_PAUSE_SECONDS]


def test_an_early_empty_page_is_not_a_clean_stop(pauses, caplog) -> None:
    pagination = FakeScraper([ALL_CASES[:2], [], ALL_CASES[2:]], total=7).scrape()["pagination"]
    assert (pagination["stop_reason"], pagination["catalog_exhausted"], pagination["empty_page"]) == ("empty_page", False, 2)
    assert "empty page 2 of 3 announced (site_total=7, products read so far=2)" in caplog.text


def test_an_unreadable_card_is_counted_and_the_listing_falls_short(pauses, caplog) -> None:
    broken = ALL_CASES[0].replace("product-block__price", "product-block__cost")
    pagination = FakeScraper([[broken] + ALL_CASES[1:]], total=7).scrape()["pagination"]
    assert pagination["unparsed_cards"] == 1 and pagination["products_seen"] == 6 != pagination["site_total"]
    assert "1 cards could not be read" in caplog.text
