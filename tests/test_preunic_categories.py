"""Preunic's catalog in several categories (since 2026-10-14) and the alerts that stop deactivation.

Real listings (tests/fixtures/preunic/categories_20261014.json): on 2026-10-13
/t/perfumes-y-fragancias held 479; on 2026-10-14 it held 77 and /t/perfume
405, none in both, 3 of them new.
"""

import json
from pathlib import Path

import pytest

from src.loader import raw_listings
from src.loader.preunic_alerts import (
    STORE,
    drop_alerts,
    listing_totals,
    new_listing_alert,
    preunic_alerts,
)
from src.loader.raw_listings import load_file
from src.scrapers.prices import PRICE_EXTRACTION_VERSION
from src.scrapers.stores.preunic import categories as preunic_categories
from src.scrapers.stores.preunic import scraper as preunic
from src.scrapers.stores.preunic.scraper import PreunicScraper, ProductRecord
from tests.test_loader import active_urls, connection, preunic_rules  # noqa: F401  (fixtures)

REAL = json.loads((Path(__file__).parent / "fixtures" / "preunic" / "categories_20261014.json")
                  .read_text(encoding="utf-8"))
FRAGANCIAS, PERFUME = "https://preunic.cl/t/perfumes-y-fragancias", "https://preunic.cl/t/perfume"
NEW_SLUGS = {"body-misy-juicy-bomb-02", "body-misy-juicy-bomb-03", "body-misy-juicy-bomb-04"}
CARDS_13 = REAL["2026-10-13"]["cards"]
CARDS_14 = {category["category_url"]: category for category in REAL["2026-10-14"]}


# ----------------------------------------------------------------- config


def test_the_categories_come_from_the_config_file() -> None:
    assert preunic_categories.category_urls() == [FRAGANCIAS, PERFUME]


@pytest.mark.parametrize("content", [
    "{}", '{"preunic": {"category_urls": []}}', '{"preunic": {"category_urls": ["preunic.cl/t/perfume"]}}', "not json",
])
def test_a_broken_config_is_refused(tmp_path, content) -> None:
    path = tmp_path / "scraping.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="category_urls"):
        preunic_categories.category_urls(path)


# ----------------------------------------------------------------- the scraper


class FakePlaywright:
    def __init__(self) -> None:
        self.chromium, self.url = self, "https://preunic.cl"

    def __enter__(self): return self
    def __exit__(self, *exc): return False
    def launch(self, headless=True): return self
    def new_page(self): return self
    def set_default_timeout(self, ms): pass
    def set_default_navigation_timeout(self, ms): pass
    def close(self): pass


def record(card: str, price: str = "$10.000") -> ProductRecord:
    return ProductRecord(name=card, brand="Test", current_price=price, previous_price=None, volume="100 ml",
                         concentration="EDT", url=f"https://preunic.cl/products/{card}", image_url=None,
                         availability="available")


def scrape(monkeypatch, tmp_path, passes: dict[str, list]) -> tuple[dict, list[str]]:
    """scrape() over the configured categories; passes[url] = listing passes (cards, total, batch_ends) or errors."""
    calls = []

    def read_listing(self, page, result, output_path, step, url=None):
        calls.append(f"{url} {step}")
        current = passes[url].pop(0)
        if isinstance(current, Exception):
            raise current
        cards, site_total, batch_ends = current
        info = {"initial_products": min(24, len(cards)), "load_more_clicks": len(batch_ends) - 1,
                "final_products": len(cards), "site_total": site_total, "catalog_exhausted": True,
                "batch_ends": batch_ends}
        return info, [record(*card) if isinstance(card, tuple) else record(card) for card in cards]

    async def no_details(self, products, result, output_path, headless):
        return None

    monkeypatch.setattr(preunic, "sync_playwright", FakePlaywright)
    monkeypatch.setattr(PreunicScraper, "_read_listing", read_listing)
    monkeypatch.setattr(PreunicScraper, "_enrich_detail_fields", no_details)
    result = PreunicScraper([FRAGANCIAS, PERFUME]).scrape(output_path=tmp_path / "p.json")
    return result, calls


def real_pass(url: str, cards=None, total=None):
    category = CARDS_14[url]
    return (category["cards"] if cards is None else cards,
            category["site_total"] if total is None else total, category["batch_ends"])


def test_the_two_real_categories_make_482_listings(monkeypatch, tmp_path) -> None:
    result, calls = scrape(monkeypatch, tmp_path, {FRAGANCIAS: [real_pass(FRAGANCIAS)], PERFUME: [real_pass(PERFUME)]})
    assert calls == [f"{FRAGANCIAS} listing", f"{PERFUME} cat2:listing"]
    pagination = result["pagination"]
    assert [(c["category_url"], c["site_total"], c["urls_distinct"], c["listing_complete"])
            for c in pagination["categories"]] == [(FRAGANCIAS, 77, 77, True), (PERFUME, 405, 405, True)]
    assert (pagination["urls_distinct"], pagination["site_total"], pagination["in_several_categories"],
            pagination["listing_complete"], pagination["catalog_exhausted"]) == (482, 482, 0, True, True)
    urls = [p["url"] for p in result["products"]]
    assert len(urls) == len(set(urls)) == 482
    assert len({u.rsplit("/", 1)[1] for u in urls} - set(CARDS_13)) == 3  # the 3 new listings
    assert result["category_urls"] == [FRAGANCIAS, PERFUME] and result["category_url"] == FRAGANCIAS


def test_a_category_that_fails_leaves_the_others_prices(monkeypatch, tmp_path) -> None:
    result, _ = scrape(monkeypatch, tmp_path, {FRAGANCIAS: [real_pass(FRAGANCIAS)],
                                               PERFUME: [TimeoutError("cat2:listing:wait_cards timed out")]})
    pagination = result["pagination"]
    assert pagination["categories"][1]["error"] == "TimeoutError: cat2:listing:wait_cards timed out"
    assert (pagination["listing_complete"], pagination["catalog_exhausted"], pagination["site_total"]) \
        == (False, False, None)
    assert len(result["products"]) == 77 and result["progress"]["step"] == "done"
    assert result["failures"][0]["step"] == "cat2:listing:goto"


def test_every_category_failing_is_a_failed_scrape(monkeypatch, tmp_path) -> None:
    with pytest.raises(RuntimeError, match="every Preunic category failed"):
        scrape(monkeypatch, tmp_path, {FRAGANCIAS: [TimeoutError("a")], PERFUME: [TimeoutError("b")]})


def test_a_category_that_does_not_match_its_total(monkeypatch, tmp_path) -> None:
    # A tie in /t/perfume at 23|24, in both passes: 404 of 405
    tied = list(CARDS_14[PERFUME]["cards"])
    tied[24] = tied[23]
    result, calls = scrape(monkeypatch, tmp_path, {FRAGANCIAS: [real_pass(FRAGANCIAS)],
                                                   PERFUME: [real_pass(PERFUME, tied), real_pass(PERFUME, tied)]})
    assert calls[-1] == f"{PERFUME} cat2:listing2"  # read twice
    pagination = result["pagination"]
    perfume = pagination["categories"][1]
    assert (perfume["listing_complete"], perfume["urls_distinct"]) == (False, 404)
    assert perfume["union_rejected"]["condition"] == "union_matches_total"
    assert (pagination["listing_complete"], pagination["urls_distinct"]) == (False, 481)


def test_a_listing_in_two_categories_counts_once(monkeypatch, tmp_path) -> None:
    shared = CARDS_14[PERFUME]["cards"][:5]
    fragancias = CARDS_14[FRAGANCIAS]["cards"] + shared
    other_price = [(card, "$9.990") for card in shared[:2]] + CARDS_14[PERFUME]["cards"][2:]
    result, _ = scrape(monkeypatch, tmp_path, {FRAGANCIAS: [real_pass(FRAGANCIAS, fragancias, 82)],
                                               PERFUME: [real_pass(PERFUME, other_price)]})
    pagination = result["pagination"]
    assert (pagination["urls_distinct"], pagination["in_several_categories"], pagination["site_total"]) \
        == (482, 5, 487)
    assert pagination["price_differs_between_categories"] == 2 and pagination["listing_complete"]
    assert len(result["products"]) == 482
    by_url = {p["url"]: p for p in result["products"]}
    assert by_url[f"https://preunic.cl/products/{shared[0]}"]["current_price"] == "$10.000"  # the first category's


# ----------------------------------------------------------------- alert rules


def test_listing_totals_of_old_and_new_files() -> None:
    old = {"progress": {"step": "done"}, "category_url": FRAGANCIAS + "/",
           "pagination": {"site_total": 2, "catalog_exhausted": True},
           "products": [{"url": "u1"}, {"url": "u2"}]}
    assert listing_totals(old) == {FRAGANCIAS: 2, STORE: 2}
    assert listing_totals({**old, "pagination": {"site_total": 3}}) is None  # not whole
    assert listing_totals({**old, "progress": {"step": "detail:enrich"}}) is None
    new = {"progress": {"step": "done"}, "pagination": {"urls_distinct": 482, "categories": [
        {"category_url": FRAGANCIAS, "site_total": 77, "listing_complete": True},
        {"category_url": PERFUME, "site_total": 405, "listing_complete": True}]}}
    assert listing_totals(new) == {FRAGANCIAS: 77, PERFUME: 405, STORE: 482}
    new["pagination"]["categories"][1]["listing_complete"] = False
    assert listing_totals(new) is None


def test_a_drop_of_more_than_10_percent_alerts() -> None:
    alerts, notes = drop_alerts([{STORE: 479}, {STORE: 77}])
    assert alerts == ["ALERT: store total dropped from 479 to 77 (-84%, more than 10%; run 1 of 3 at this total): "
                      "nothing deactivated"] and notes == []
    assert drop_alerts([{STORE: 100}, {STORE: 91}]) == ([], [])  # -9 %
    assert drop_alerts([{STORE: 100}, {STORE: 85}, {STORE: 100}]) == ([], [])  # back up


def test_the_same_lower_total_three_runs_in_a_row_is_accepted() -> None:
    history = [{STORE: 100}, {STORE: 85}, {STORE: 85}]
    assert "run 2 of 3" in drop_alerts(history)[0][0]
    alerts, notes = drop_alerts(history + [{STORE: 85}])
    assert alerts == [] and notes == ["store: total 85 accepted as the new baseline after 3 runs in a row at it (was 100)"]
    assert drop_alerts(history + [{STORE: 85}, {STORE: 85}]) == ([], [])  # the new baseline holds
    assert "run 1 of 3" in drop_alerts([{STORE: 100}, {STORE: 85}, {STORE: 86}])[0][0]  # not the same total


def test_a_category_drop_alerts_only_if_the_store_drops_too() -> None:
    a, b = "https://x/t/a", "https://x/t/b"
    alerts, notes = drop_alerts([{a: 479, STORE: 479}, {a: 77, b: 405, STORE: 482}])
    assert alerts == [] and notes == ["category /t/a: total 479 -> 77 while the store's total holds (479 -> 482): "
                                      "a reorganization, new baseline"]
    alerts, _ = drop_alerts([{a: 479, STORE: 479}, {a: 77, b: 300, STORE: 377}])
    assert [alert.split(" total")[0] for alert in alerts] == ["ALERT: category /t/a", "ALERT: store"]


def test_a_new_category_never_alerts() -> None:
    a, b = "https://x/t/a", "https://x/t/b"
    assert drop_alerts([{a: 100, STORE: 100}, {a: 100, b: 5, STORE: 105}]) == ([], [])
    alerts, _ = drop_alerts([{a: 100, STORE: 100}, {a: 80, b: 5, STORE: 85}])  # the store drops; b is new
    assert not any("/t/b" in alert for alert in alerts)


def test_too_many_new_listings_alert() -> None:
    assert new_listing_alert(known_in_store=482, known_read=479, read=482) == []  # the 3 of 2026-10-14
    assert new_listing_alert(known_in_store=482, known_read=100, read=115) == [
        "ALERT: 15 of 115 listings read are new to the store (13%, more than 10%; did its URLs change?): "
        "nothing deactivated"]
    assert new_listing_alert(known_in_store=0, known_read=0, read=479) == []  # a store's first load


# ----------------------------------------------------------------- loading


@pytest.fixture
def alerts(monkeypatch, preunic_rules):
    """teststore behaves like Preunic, alerts included."""
    monkeypatch.setitem(raw_listings.STORE_ALERTS, "teststore", preunic_alerts)


def card(token: str) -> dict:
    return {"url": f"https://test.example/{token}", "name": f"Perfume Test {token} EDP 100 ml", "brand": "Test",
            "current_price": "$10.000", "previous_price": None, "availability": "available"}


def write(directory: Path, hour: int, tokens: list[str], pagination: dict, category_url=None) -> Path:
    path = directory / f"teststore_2030010{hour}.json"
    path.write_text(json.dumps({
        "store": "teststore", "scraped_at": f"2030-01-01T{hour:02d}:00:00+00:00", "category_url": category_url,
        "price_extraction_version": PRICE_EXTRACTION_VERSION, "progress": {"step": "done"},
        "pagination": pagination, "products": [card(t) for t in tokens]}), encoding="utf-8")
    return path


def one_category(total: int) -> dict:  # a file of before 2026-10-15
    return {"catalog_exhausted": True, "site_total": total, "listing_complete": True}


def category(url: str, total: int, distinct: int | None = None, error: str | None = None) -> dict:
    distinct = total if distinct is None else distinct
    return {"category_url": url, "site_total": None if error else total, "urls_distinct": distinct,
            "catalog_exhausted": not error, "listing_source": "first_pass",
            "listing_complete": not error and distinct == total, **({"error": error} if error else {})}


def categories(*items: dict, distinct: int, overlap: int = 0) -> dict:
    return {"categories": list(items), "urls_distinct": distinct, "in_several_categories": overlap,
            "catalog_exhausted": all(not c.get("error") for c in items),
            "site_total": sum(c["site_total"] or 0 for c in items),
            "listing_complete": all(c["listing_complete"] for c in items)}


REORGANIZED = ("category /t/perfumes-y-fragancias: total 479 -> 77 while the store's total holds (479 -> 482): "
               "a reorganization, new baseline")


def test_the_real_split_loads_482_listings_complete(connection, alerts, tmp_path) -> None:
    fragancias, perfume = CARDS_14[FRAGANCIAS]["cards"], CARDS_14[PERFUME]["cards"]
    split = categories(category(FRAGANCIAS, 77), category(PERFUME, 405), distinct=482)

    stats = load_file(connection, write(tmp_path, 0, CARDS_13, one_category(479), FRAGANCIAS), deactivate_missing=True)
    assert stats["complete"] and stats["alerts"] == []

    # 2026-10-14: the old scraper read only the 77 of /t/perfumes-y-fragancias: the store itself dropped
    stats = load_file(connection, write(tmp_path, 1, fragancias, one_category(77), FRAGANCIAS), deactivate_missing=True)
    assert not stats["complete"] and (stats["deactivated"], stats["prices_added"]) == (0, 77)
    assert any("store total dropped from 479 to 77 (-84%" in a for a in stats["alerts"])

    # the next run reads both categories: 482 listings, 3 new; /t/perfumes-y-fragancias at 77 with the store
    # holding is a reorganization, not a loss: no alert, complete
    stats = load_file(connection, write(tmp_path, 2, fragancias + perfume, split), deactivate_missing=True)
    assert (stats["complete"], stats["alerts"]) == (True, [])
    assert (stats["inserted"], stats["prices_added"], stats["deactivated"]) == (3, 482, 0)
    assert REORGANIZED in stats["notes"]
    assert len(active_urls(connection)) == 482

    stats = load_file(connection, write(tmp_path, 3, fragancias + perfume, split), deactivate_missing=True)
    assert (stats["complete"], stats["alerts"], stats["deactivated"]) == (True, [], 0)
    assert not any("baseline" in note for note in stats["notes"])  # 77 is the baseline now


def test_479_to_77_plus_405_directly_is_complete(connection, alerts, tmp_path) -> None:
    fragancias, perfume = CARDS_14[FRAGANCIAS]["cards"], CARDS_14[PERFUME]["cards"]
    load_file(connection, write(tmp_path, 0, CARDS_13, one_category(479), FRAGANCIAS), deactivate_missing=True)
    split = categories(category(FRAGANCIAS, 77), category(PERFUME, 405), distinct=482)
    stats = load_file(connection, write(tmp_path, 1, fragancias + perfume, split), deactivate_missing=True)
    assert (stats["complete"], stats["alerts"], stats["deactivated"], stats["inserted"]) == (True, [], 0, 3)
    assert REORGANIZED in stats["notes"]


def test_a_real_store_drop_still_alerts(connection, alerts, tmp_path) -> None:
    # 479 -> 77 + 300: the store lost 102 listings (-21 %, under the 25 % limit)
    fragancias, perfume = CARDS_14[FRAGANCIAS]["cards"], CARDS_14[PERFUME]["cards"][:300]
    load_file(connection, write(tmp_path, 0, CARDS_13, one_category(479), FRAGANCIAS), deactivate_missing=True)
    shrunk = categories(category(FRAGANCIAS, 77), category(PERFUME, 300), distinct=377)
    stats = load_file(connection, write(tmp_path, 1, fragancias + perfume, shrunk), deactivate_missing=True)
    assert (stats["complete"], stats["deactivated"], stats["prices_added"]) == (False, 0, 377)
    assert stats["alerts"] == [
        "ALERT: category /t/perfumes-y-fragancias total dropped from 479 to 77 (-84%, more than 10%; run 1 of 3 "
        "at this total): nothing deactivated",
        "ALERT: store total dropped from 479 to 377 (-21%, more than 10%; run 1 of 3 at this total): "
        "nothing deactivated"]
    new = len(set(perfume) - set(CARDS_13))
    assert len(active_urls(connection)) == 479 + new  # nothing deactivated, the new ones added


def test_a_category_that_disappears(connection, alerts, tmp_path) -> None:
    fragancias, perfume = CARDS_14[FRAGANCIAS]["cards"], CARDS_14[PERFUME]["cards"]
    split = categories(category(FRAGANCIAS, 77), category(PERFUME, 405), distinct=482)
    load_file(connection, write(tmp_path, 0, fragancias + perfume, split), deactivate_missing=True)
    # /t/perfume no longer shows any product card
    gone = categories(category(FRAGANCIAS, 77),
                      category(PERFUME, 0, error="NoProductCards: no product card (a[href^='/products/']) within 30 s"),
                      distinct=77)
    stats = load_file(connection, write(tmp_path, 1, fragancias, gone), deactivate_missing=True)
    assert (stats["complete"], stats["deactivated"], stats["prices_added"]) == (False, 0, 77)
    assert stats["stop_reason"] == "category_failed:/t/perfume"
    assert len(active_urls(connection)) == 482


def test_a_drop_alert_loads_the_prices_and_deactivates_nothing(connection, alerts, tmp_path) -> None:
    tokens = [f"p{n}" for n in range(100)]
    load_file(connection, write(tmp_path, 0, tokens, one_category(100), FRAGANCIAS), deactivate_missing=True)
    # -15 %: under the 25 % limit, it would deactivate 15 listings without the alert
    stats = load_file(connection, write(tmp_path, 1, tokens[:85], one_category(85), FRAGANCIAS), deactivate_missing=True)
    assert (stats["complete"], stats["deactivated"], stats["prices_added"]) == (False, 0, 85)
    assert len(active_urls(connection)) == 100
    stats = load_file(connection, write(tmp_path, 2, tokens[:85], one_category(85), FRAGANCIAS), deactivate_missing=True)
    assert stats["deactivated"] == 0 and "run 2 of 3" in stats["alerts"][0]
    stats = load_file(connection, write(tmp_path, 3, tokens[:85], one_category(85), FRAGANCIAS), deactivate_missing=True)
    assert (stats["complete"], stats["alerts"], stats["deactivated"]) == (True, [], 15)  # accepted: a real change
    assert "store: total 85 accepted as the new baseline after 3 runs in a row at it (was 100)" in stats["notes"]


def test_too_many_new_listings_stop_deactivation(connection, alerts, tmp_path) -> None:
    load_file(connection, write(tmp_path, 0, [f"p{n}" for n in range(100)], one_category(100), FRAGANCIAS),
              deactivate_missing=True)
    renamed = [f"p{n}" for n in range(85)] + [f"new{n}" for n in range(15)]  # 15 % new URLs, 15 missing
    stats = load_file(connection, write(tmp_path, 1, renamed, one_category(100), FRAGANCIAS), deactivate_missing=True)
    assert (stats["complete"], stats["deactivated"], stats["inserted"], stats["prices_added"]) == (False, 0, 15, 100)
    assert stats["alerts"] == ["ALERT: 15 of 100 listings read are new to the store (15%, more than 10%; did its "
                               "URLs change?): nothing deactivated"]
    assert len(active_urls(connection)) == 115


def test_loading_a_failed_category(connection, alerts, tmp_path) -> None:
    tokens = [f"p{n}" for n in range(20)]
    load_file(connection, write(tmp_path, 0, tokens, one_category(20), FRAGANCIAS), deactivate_missing=True)
    failed = categories(category(FRAGANCIAS, 5), category(PERFUME, 15, error="TimeoutError: x"), distinct=5)
    stats = load_file(connection, write(tmp_path, 1, tokens[:5], failed), deactivate_missing=True)
    assert (stats["complete"], stats["deactivated"], stats["prices_added"]) == (False, 0, 5)
    assert stats["stop_reason"] == "category_failed:/t/perfume"
    assert "scrape did not end cleanly (category_failed:/t/perfume)" in stats["notes"]


def test_loading_a_category_that_does_not_match(connection, alerts, tmp_path) -> None:
    tokens = [f"p{n}" for n in range(20)]
    load_file(connection, write(tmp_path, 0, tokens, one_category(20), FRAGANCIAS), deactivate_missing=True)
    short = categories(category(FRAGANCIAS, 5), category(PERFUME, 15, distinct=14), distinct=19)
    stats = load_file(connection, write(tmp_path, 1, tokens[:19], short), deactivate_missing=True)
    assert (stats["complete"], stats["deactivated"]) == (False, 0)
    assert any(note.startswith("category /t/perfume: 14 distinct listings, the page reports 15")
               for note in stats["notes"])


def test_loading_listings_in_two_categories(connection, alerts, tmp_path) -> None:
    tokens = [f"p{n}" for n in range(20)]  # 8 + 15 cards, 3 of them in both categories
    overlap = categories(category(FRAGANCIAS, 8), category(PERFUME, 15), distinct=20, overlap=3)
    stats = load_file(connection, write(tmp_path, 0, tokens, overlap), deactivate_missing=True)
    assert stats["complete"] and (stats["prices_added"], stats["inserted"]) == (20, 20)
    assert "3 listings in more than one category (counted once)" in stats["notes"]
    stats = load_file(connection, write(tmp_path, 1, tokens, overlap), deactivate_missing=True)  # the next day
    assert stats["complete"] and stats["alerts"] == [] and stats["prices_added"] == 20
