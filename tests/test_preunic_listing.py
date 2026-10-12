"""Preunic's listing read twice when the category's order ties repeat and drop cards (listing.py).

The cases come from real scrapes (tests/fixtures/preunic/listing_ties.json):
2026-09-25 (two passes, a different tie in each), 2026-10-08 (run 38, one tie)
and 2026-10-12 (run 43, four ties at 311|312, 407|408 and 455|456).
"""

import asyncio
import json
from pathlib import Path

import pytest

from src.scrapers.stores.preunic import scraper as preunic
from src.scrapers.stores.preunic.listing import (
    FIRST_PASS,
    SECOND_PASS,
    UNION,
    ListingPass,
    choose_listing,
    near_a_batch_boundary,
)
from src.scrapers.stores.preunic.scraper import PreunicScraper, ProductRecord

CASES = json.loads((Path(__file__).parent / "fixtures" / "preunic" / "listing_ties.json")
                   .read_text(encoding="utf-8"))["cases"]
BASE = "https://preunic.cl/products/"
TIE_SLUGS_1012 = {  # run 43: repeated -> missing, side by side at the same cut
    "estuche-perfume-etienne-essence-aura-edp-100-ml-perfumero-10-ml",
    "set-perfume-hello-kitty-edt-espejo",
    "set-perfume-mujer-glow-edt-lapiz",
    "agatha-ruiz-de-la-prada-mujer-beso",
}
MISSING_1012 = {
    "estuche-millionaire-red-lust-100ml-red-lust-30ml-after-shave-100ml",
    "etienne-eau-the-parfum-euphoria-55-ml-crema-corporal-50-g",
    "etienne-eau-the-parfum-sparkling-rose-55-ml-crema-corporal-50-g",
    "estuche-beso-eau-de-toilette-50-ml-de-beso-en-beso-eau-de-toilette-10-ml",
}


def listing_pass(case: str, which: str, cards: list[str] | None = None, site_total: int | None = None) -> ListingPass:
    data = CASES[case][which]
    cards = data["cards"] if cards is None else cards
    return ListingPass([BASE + card for card in cards], data["site_total"] if site_total is None else site_total,
                       data["batch_ends"])


def slugs(urls) -> set[str]:
    return {url.removeprefix(BASE) for url in urls}


def with_tie(cards: list[str], cut: int) -> list[str]:
    """The same listing with a tie at the cut cut-1|cut: the card before it shows up twice, the one at it never."""
    tied = list(cards)
    tied[cut] = tied[cut - 1]
    return tied


# ------------------------------------------------------------- batch boundaries


@pytest.mark.parametrize(("position", "near"), [
    (311, True), (312, True), (310, True), (313, True),  # cut 311|312, one card either side
    (309, False), (314, False),
    (406, True), (409, True), (457, True), (458, False),
    (478, False),  # the last card of the listing is not a cut between two batches
])
def test_near_a_batch_boundary(position, near) -> None:
    assert near_a_batch_boundary(position, CASES["2026-10-12"]["first"]["batch_ends"]) is near


def test_run_43_four_ties_sit_at_the_batch_boundaries() -> None:
    first = listing_pass("2026-10-12", "first")
    repeated = {slug: spots["positions"] for spots in first.repeated() for slug in slugs([spots["url"]])}
    assert repeated == {
        "estuche-perfume-etienne-essence-aura-edp-100-ml-perfumero-10-ml": [310, 312],
        "set-perfume-hello-kitty-edt-espejo": [406, 408],
        "set-perfume-mujer-glow-edt-lapiz": [407, 409],
        "agatha-ruiz-de-la-prada-mujer-beso": [455, 456],
    }
    assert (len(first.urls), len(set(first.urls)), first.site_total) == (479, 475, 479)
    assert not first.complete()
    assert all(near_a_batch_boundary(p, first.batch_ends) for spots in repeated.values() for p in spots)


# ---------------------------------------------------------------- the decision


def test_a_complete_first_pass_is_used_as_it_is() -> None:
    second = listing_pass("2026-10-12", "second")  # 479 distinct of 479
    decision = choose_listing(second, None)
    assert (decision["listing_source"], decision["listing_complete"], len(decision["urls"])) == (FIRST_PASS, True, 479)


def test_without_a_second_pass_the_first_stands_incomplete() -> None:
    decision = choose_listing(listing_pass("2026-10-12", "first"), None)
    assert (decision["listing_source"], decision["listing_complete"], len(decision["urls"])) == (FIRST_PASS, False, 475)


@pytest.mark.parametrize("case", ["2026-10-08", "2026-10-12"])
def test_a_complete_second_pass_is_used_alone(case) -> None:
    decision = choose_listing(listing_pass(case, "first"), listing_pass(case, "second"))
    assert decision["listing_source"] == SECOND_PASS and decision["listing_complete"]
    assert len(decision["urls"]) == CASES[case]["second"]["site_total"]
    assert decision["recovered"] == [] and decision["union_rejected"] is None


def test_two_passes_with_different_ties_make_a_complete_union() -> None:
    # 2026-09-25: each pass lost the card the other one repeated
    decision = choose_listing(listing_pass("2026-09-25", "first"), listing_pass("2026-09-25", "second"))
    assert (decision["listing_source"], decision["listing_complete"], len(decision["urls"])) == (UNION, True, 500)
    assert slugs(decision["recovered"]) == {"perfume-mujer-plaisance-hot-blossom-edp-100-ml"}


def test_run_43_four_ties_are_recovered_by_a_union() -> None:
    # The second pass also hits a tie, at another cut (23|24): neither pass alone is complete.
    second_cards = with_tie(CASES["2026-10-12"]["second"]["cards"], 24)
    first, second = listing_pass("2026-10-12", "first"), listing_pass("2026-10-12", "second", second_cards)
    assert not first.complete() and not second.complete()
    decision = choose_listing(first, second)
    assert (decision["listing_source"], decision["listing_complete"], len(decision["urls"])) == (UNION, True, 479)
    assert slugs(decision["recovered"]) == MISSING_1012
    assert decision["union_rejected"] is None


def test_a_union_across_a_page_total_change_is_rejected() -> None:
    # A listing entered between the passes (480), and the second pass also hit a tie
    second_cards = with_tie(CASES["2026-10-12"]["second"]["cards"], 24)
    decision = choose_listing(listing_pass("2026-10-12", "first"),
                              listing_pass("2026-10-12", "second", second_cards, site_total=480))
    assert decision["listing_source"] == UNION and not decision["listing_complete"]
    assert decision["union_rejected"]["condition"] == "same_page_total"
    assert decision["union_rejected"]["detail"] == "the page reported 479 then 480 products"


def test_a_second_pass_that_matches_its_own_total_is_used_alone() -> None:
    # A listing left between the passes: the second pass is one whole moment of the catalog
    second_cards = CASES["2026-10-12"]["second"]["cards"][:-1]
    decision = choose_listing(listing_pass("2026-10-12", "first"),
                              listing_pass("2026-10-12", "second", second_cards, site_total=478))
    assert (decision["listing_source"], decision["listing_complete"], len(decision["urls"])) == (SECOND_PASS, True, 478)


def test_a_union_that_does_not_match_the_total_is_rejected() -> None:
    # Both passes lose the same card at the same cut: the union is still one short
    cards = CASES["2026-10-12"]["second"]["cards"]
    decision = choose_listing(listing_pass("2026-10-12", "second", with_tie(cards, 24)),
                              listing_pass("2026-10-12", "second", with_tie(cards, 24)))
    assert decision["union_rejected"]["condition"] == "union_matches_total"
    assert "478 distinct listings, the page reports 479" in decision["union_rejected"]["detail"]


def test_a_catalog_change_hidden_in_a_union_is_rejected() -> None:
    # The harmful coincidence: between the passes a listing leaves and another one enters (the
    # total stays 479), and the second pass misses the same card as the first at 311|312. The union
    # then counts 479, but the listing that left (position 200 in the first pass) is not at a cut.
    cards = with_tie(CASES["2026-10-12"]["second"]["cards"], 312)
    left = cards[200]
    cards[200] = "a-new-listing"
    decision = choose_listing(listing_pass("2026-10-12", "first"), listing_pass("2026-10-12", "second", cards))
    assert len(decision["urls"]) == 479 and not decision["listing_complete"]
    rejected = decision["union_rejected"]
    assert rejected["condition"] == "differences_at_batch_boundaries"
    assert {slug for spots in rejected["listings"] for slug in slugs([spots["url"]])} == {left, "a-new-listing"}


# ------------------------------------------------------------- the scraper


class FakePlaywright:
    def __init__(self) -> None:
        self.chromium, self.url = self, "https://preunic.cl/t/perfumes-y-fragancias"

    def __enter__(self): return self
    def __exit__(self, *exc): return False
    def launch(self, headless=True): return self
    def new_page(self): return self
    def set_default_timeout(self, ms): pass
    def set_default_navigation_timeout(self, ms): pass
    def close(self): pass


def product(slug: str) -> ProductRecord:
    return ProductRecord(name=slug, brand="Test", current_price="$10.000", previous_price=None, volume="100 ml",
                         concentration="EDT", url=BASE + slug, image_url=None, availability="available")


def scrape_with(monkeypatch, tmp_path, passes) -> tuple[dict, list[str]]:
    """Run scrape() with listing passes taken from the fixture (or an exception), no browser."""
    calls = []

    def read_listing(self, page, result, output_path, step):
        calls.append(step)
        current = passes[len(calls) - 1]
        if isinstance(current, Exception):
            raise current
        cards, site_total, batch_ends = current
        info = {"initial_products": 24, "load_more_clicks": len(batch_ends) - 1, "final_products": len(cards),
                "site_total": site_total, "catalog_exhausted": True, "batch_ends": batch_ends}
        return info, [product(card) for card in cards]

    async def no_details(self, products, result, output_path, headless):
        return None

    monkeypatch.setattr(preunic, "sync_playwright", FakePlaywright)
    monkeypatch.setattr(PreunicScraper, "_read_listing", read_listing)
    monkeypatch.setattr(PreunicScraper, "_enrich_detail_fields", no_details)
    result = PreunicScraper("https://preunic.cl/t/perfumes-y-fragancias").scrape(output_path=tmp_path / "p.json")
    return result, calls


def fixture_pass(case: str, which: str, cards=None):
    data = CASES[case][which]
    return cards if cards is not None else data["cards"], data["site_total"], data["batch_ends"]


def test_scrape_reads_the_listing_once_when_it_matches_the_total(monkeypatch, tmp_path) -> None:
    result, calls = scrape_with(monkeypatch, tmp_path, [fixture_pass("2026-10-12", "second")])
    assert calls == ["listing"]
    pagination = result["pagination"]
    assert (pagination["listing_source"], pagination["listing_complete"], pagination["urls_distinct"]) \
        == (FIRST_PASS, True, 479)
    assert pagination["cards_read"] == 479 and pagination["urls_repeated"] == [] and len(pagination["passes"]) == 1
    assert len(result["products"]) == 479 and result["progress"]["step"] == "done"


def test_scrape_run_43_reads_twice_and_records_both_passes(monkeypatch, tmp_path) -> None:
    second_cards = with_tie(CASES["2026-10-12"]["second"]["cards"], 24)
    result, calls = scrape_with(monkeypatch, tmp_path, [fixture_pass("2026-10-12", "first"),
                                                        fixture_pass("2026-10-12", "second", second_cards)])
    assert calls == ["listing", "listing2"]
    pagination = result["pagination"]
    assert (pagination["listing_source"], pagination["listing_complete"]) == (UNION, True)
    assert (pagination["cards_read"], pagination["urls_distinct"], pagination["site_total"]) == (958, 479, 479)
    assert {slug for spots in pagination["urls_repeated"] for slug in slugs([spots["url"]])} == TIE_SLUGS_1012
    assert slugs(pagination["recovered"]) == MISSING_1012
    assert [(p["cards"], p["distinct"]) for p in pagination["passes"]] == [(479, 475), (479, 478)]
    assert pagination["batch_ends"][:3] == [24, 48, 72] and pagination["union_rejected"] is None
    urls = [p["url"] for p in result["products"]]
    assert len(urls) == len(set(urls)) == 479  # one product per listing
    assert MISSING_1012 <= slugs(urls)


def test_scrape_records_why_a_union_was_rejected(monkeypatch, tmp_path) -> None:
    second_cards = with_tie(CASES["2026-10-12"]["second"]["cards"], 24)
    result, _ = scrape_with(monkeypatch, tmp_path, [fixture_pass("2026-10-12", "first"),
                                                    (second_cards, 480, CASES["2026-10-12"]["second"]["batch_ends"])])
    pagination = result["pagination"]
    assert pagination["listing_complete"] is False
    assert pagination["union_rejected"] == {"condition": "same_page_total",
                                            "detail": "the page reported 479 then 480 products"}
    assert len(result["products"]) == 479  # the prices of every listing seen are kept


def test_a_failed_second_pass_leaves_the_first_one_incomplete(monkeypatch, tmp_path) -> None:
    result, calls = scrape_with(monkeypatch, tmp_path, [fixture_pass("2026-10-12", "first"),
                                                        TimeoutError("listing2:wait_cards timed out")])
    assert calls == ["listing", "listing2"]
    pagination = result["pagination"]
    assert (pagination["listing_source"], pagination["listing_complete"]) == (FIRST_PASS, False)
    assert pagination["second_pass_error"] == "TimeoutError: listing2:wait_cards timed out"
    assert len(result["products"]) == 475 and result["progress"]["step"] == "done"


def test_no_page_total_no_second_pass(monkeypatch, tmp_path) -> None:
    cards, _, batch_ends = fixture_pass("2026-10-12", "first")
    result, calls = scrape_with(monkeypatch, tmp_path, [(cards, None, batch_ends)])
    assert calls == ["listing"] and result["pagination"]["listing_complete"] is False
