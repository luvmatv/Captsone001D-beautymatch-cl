"""Loader rules: when a scrape counts as complete, deactivation, unfinished files,
embedding reset and pending files.

The database tests run in beautymatch_test (see conftest.py) with a fake store
("teststore"), inside a transaction that is rolled back.
"""

import json

import psycopg
import pytest

from src.loader import raw_listings
from src.loader.raw_listings import (
    ScrapeError,
    load_file,
    pending_files,
    read_scrape,
    scrape_stop,
)
from src.scrapers.prices import PRICE_EXTRACTION_VERSION


@pytest.mark.parametrize(("data", "expected"), [
    ({"store": "preunic", "progress": {"step": "done"}, "pagination": {"catalog_exhausted": True}},
     (True, "catalog_exhausted")),
    ({"store": "preunic", "progress": {"step": "done"}, "pagination": {"catalog_exhausted": False}},
     (False, "load_more_stopped")),
    ({"store": "maicao", "progress": {"step": "done"}, "pagination": {"stop_reason": "short_page"}},
     (True, "short_page")),
    ({"store": "maicao", "progress": {"step": "done"}, "pagination": {"stop_reason": "max_pages_reached"}},
     (False, "max_pages_reached")),
    ({"store": "maicao", "progress": {"step": "done"}, "pagination": {"stop_reason": "empty_page"}},
     (False, "empty_page")),
    ({"store": "preunic", "progress": {"step": "detail:enrich"}, "pagination": {"catalog_exhausted": True}},
     (False, "unfinished:detail:enrich")),
])
def test_scrape_stop(data, expected) -> None:
    assert scrape_stop(data) == expected


def test_unfinished_scrape_is_rejected_unless_allowed(tmp_path) -> None:
    path = tmp_path / "maicao_x.json"
    path.write_text(json.dumps({"store": "maicao", "progress": {"step": "listing:goto"},
                                "price_extraction_version": PRICE_EXTRACTION_VERSION, "products": []}))
    with pytest.raises(ScrapeError, match="did not finish"):
        read_scrape(path)
    assert read_scrape(path, allow_unfinished=True)["store"] == "maicao"


# ------------------------------------------------------------------ database


@pytest.fixture
def connection(monkeypatch, database_url):
    monkeypatch.setitem(raw_listings.STORES, "teststore", "https://test.example")
    monkeypatch.setitem(raw_listings.CLEAN_STOP, "teststore", raw_listings._maicao_stop)
    with psycopg.connect(database_url) as connection:
        # Open the outer transaction now: load_file's transaction() is only a
        # savepoint (rolled back below) if a transaction is already in progress;
        # otherwise it would commit.
        connection.execute("SELECT 1")
        try:
            yield connection
        finally:
            connection.rollback()
            leaked = connection.execute("SELECT count(*) FROM stores WHERE name = 'teststore'").fetchone()[0]
            connection.rollback()
            assert leaked == 0, "test rows were committed to the database"


def product(n, price="$10.000", name=None):
    return {"url": f"https://test.example/p{n}", "name": name or f"Perfume Test {n} EDP 100 ml", "brand": "Test",
            "current_price": price, "previous_price": None, "availability": "available"}


def write_scrape(directory, products, *, hour=0, step="done", stop="short_page", pagination=None):
    scraped_at = f"2030-01-01T{hour:02d}:00:00+00:00"
    path = directory / f"teststore_2030010{hour}.json"
    path.write_text(json.dumps({
        "store": "teststore", "scraped_at": scraped_at, "price_extraction_version": PRICE_EXTRACTION_VERSION,
        "progress": {"step": step}, "pagination": pagination or {"stop_reason": stop}, "products": products,
    }), encoding="utf-8")
    return path


@pytest.fixture
def preunic_rules(monkeypatch):
    """teststore behaves like Preunic: complete only if the listings read match the page's total."""
    monkeypatch.setitem(raw_listings.CLEAN_STOP, "teststore", raw_listings._preunic_stop)
    monkeypatch.setitem(raw_listings.INCOMPLETE_REASON, "teststore", raw_listings._matches_site_total)


def preunic_pagination(site_total):
    return {"catalog_exhausted": True, "site_total": site_total}


def active_urls(connection):
    return {url for (url,) in connection.execute(
        "SELECT listing_url FROM raw_listings rl JOIN stores s USING (store_id) "
        "WHERE s.name = 'teststore' AND rl.is_active").fetchall()}


def prices(connection, n):
    return [p for (p,) in connection.execute(
        "SELECT ph.price FROM price_history ph JOIN raw_listings rl USING (raw_listing_id) "
        "WHERE rl.listing_url = %s ORDER BY ph.scraped_at", (f"https://test.example/p{n}",)).fetchall()]


def test_complete_scrape_deactivates_missing_listings(connection, tmp_path) -> None:
    load_file(connection, write_scrape(tmp_path, [product(n) for n in range(10)], hour=0), deactivate_missing=True)
    stats = load_file(connection, write_scrape(tmp_path, [product(n) for n in range(9)], hour=1),
                      deactivate_missing=True)
    assert stats["complete"] and stats["deactivated"] == 1
    assert "https://test.example/p9" not in active_urls(connection)

    # it comes back in a later scrape: active again
    load_file(connection, write_scrape(tmp_path, [product(n) for n in range(10)], hour=2), deactivate_missing=True)
    assert len(active_urls(connection)) == 10


def test_nothing_is_deactivated_without_the_flag(connection, tmp_path) -> None:
    load_file(connection, write_scrape(tmp_path, [product(n) for n in range(10)], hour=0))
    stats = load_file(connection, write_scrape(tmp_path, [product(n) for n in range(9)], hour=1))
    assert stats["complete"] and stats["deactivated"] == 0
    assert len(active_urls(connection)) == 10


def test_scrape_that_did_not_end_cleanly_deactivates_nothing(connection, tmp_path) -> None:
    load_file(connection, write_scrape(tmp_path, [product(n) for n in range(10)], hour=0))
    stats = load_file(connection, write_scrape(tmp_path, [product(n) for n in range(9)], hour=1,
                                               stop="max_pages_reached"), deactivate_missing=True)
    assert not stats["complete"] and stats["deactivated"] == 0
    assert stats["prices_added"] == 9  # prices are still loaded
    assert any("did not end cleanly" in note for note in stats["notes"])
    assert len(active_urls(connection)) == 10


def test_short_scrape_deactivates_nothing(connection, tmp_path) -> None:
    load_file(connection, write_scrape(tmp_path, [product(n) for n in range(10)], hour=0))
    stats = load_file(connection, write_scrape(tmp_path, [product(n) for n in range(7)], hour=1),
                      deactivate_missing=True)  # 70 % < 80 %
    assert not stats["complete"] and stats["deactivated"] == 0
    assert any("70%" in note for note in stats["notes"])
    assert len(active_urls(connection)) == 10


def test_preunic_deactivates_when_the_listings_read_match_the_page_total(connection, preunic_rules, tmp_path) -> None:
    load_file(connection, write_scrape(tmp_path, [product(n) for n in range(10)], hour=0,
                                       pagination=preunic_pagination(10)), deactivate_missing=True)
    # 7 of 10 would fail the 80 % rule, but the page itself says the catalog has 7 now
    stats = load_file(connection, write_scrape(tmp_path, [product(n) for n in range(7)], hour=1,
                                               pagination=preunic_pagination(7)), deactivate_missing=True)
    assert stats["complete"] and stats["deactivated"] == 3
    assert len(active_urls(connection)) == 7


def test_preunic_total_mismatch_loads_prices_but_deactivates_nothing(connection, preunic_rules, tmp_path) -> None:
    load_file(connection, write_scrape(tmp_path, [product(n) for n in range(10)], hour=0,
                                       pagination=preunic_pagination(10)))
    stats = load_file(connection, write_scrape(tmp_path, [product(n) for n in range(9)], hour=1,
                                               pagination=preunic_pagination(10)), deactivate_missing=True)
    assert not stats["complete"] and stats["deactivated"] == 0
    assert stats["prices_added"] == 9
    assert "read 9 listings, the page shows 10" in stats["notes"]
    assert len(active_urls(connection)) == 10


def test_preunic_scrape_without_a_total_deactivates_nothing(connection, preunic_rules, tmp_path) -> None:
    load_file(connection, write_scrape(tmp_path, [product(n) for n in range(10)], hour=0,
                                       pagination=preunic_pagination(10)))
    old_format = {"catalog_exhausted": True}  # scrapes made before site_total existed
    stats = load_file(connection, write_scrape(tmp_path, [product(n) for n in range(9)], hour=1,
                                               pagination=old_format), deactivate_missing=True)
    assert not stats["complete"] and stats["deactivated"] == 0
    assert any("did not show a product total" in note for note in stats["notes"])


def test_unfinished_scrape_adds_prices_of_known_listings_only(connection, tmp_path) -> None:
    load_file(connection, write_scrape(tmp_path, [product(0), product(1)], hour=0))
    unfinished = write_scrape(tmp_path, [product(0, "$9.000", name="Renamed EDT 50 ml"), product(2)],
                              hour=1, step="detail:enrich")
    stats = load_file(connection, unfinished, allow_unfinished=True, deactivate_missing=True)
    assert stats["mode"] == "prices_only" and not stats["complete"]
    assert (stats["prices_added"], stats["skipped"], stats["deactivated"]) == (1, 1, 0)
    assert prices(connection, 0) == [10000, 9000]
    assert connection.execute(  # attributes of a half-enriched scrape are not trusted
        "SELECT raw_name FROM raw_listings WHERE listing_url = 'https://test.example/p0'").fetchone()[0] \
        == "Perfume Test 0 EDP 100 ml"
    assert "https://test.example/p2" not in active_urls(connection)  # new listing waits for a finished scrape


def test_renamed_listing_loses_its_embedding(connection, tmp_path) -> None:
    load_file(connection, write_scrape(tmp_path, [product(0), product(1)], hour=0))
    connection.execute("UPDATE raw_listings SET embedding = array_fill(0.1, ARRAY[768])::vector "
                       "WHERE listing_url LIKE 'https://test.example/%'")
    load_file(connection, write_scrape(tmp_path, [product(0, name="Perfume Test 0 Intense EDP 100 ml"), product(1)],
                                       hour=1))
    embedded = dict(connection.execute(
        "SELECT listing_url, embedding IS NOT NULL FROM raw_listings WHERE listing_url LIKE 'https://test.example/%'"
    ).fetchall())
    assert embedded == {"https://test.example/p0": False, "https://test.example/p1": True}


def test_pending_files_are_the_ones_newer_than_the_last_loaded_price(connection, tmp_path) -> None:
    load_file(connection, write_scrape(tmp_path, [product(0)], hour=1))
    older = write_scrape(tmp_path, [product(0)], hour=0)
    newer = [write_scrape(tmp_path, [product(0)], hour=h) for h in (3, 2)]
    write_scrape(tmp_path, [], hour=4)  # a scraper that died before finding products
    assert pending_files(connection, "teststore", tmp_path) == sorted(newer)
    assert older not in pending_files(connection, "teststore", tmp_path)
