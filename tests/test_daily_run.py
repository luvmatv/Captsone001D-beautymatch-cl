"""The daily run with fake scrapers, embeddings and matching.

Database tests run in beautymatch_test (see conftest.py) with fake stores,
inside a transaction that is rolled back.
"""

import json
from pathlib import Path

import psycopg
import pytest

from src import daily_run
from src.daily_run import ScrapeOutcome, StoreRow, run, run_status
from src.loader import raw_listings
from src.scrapers.prices import PRICE_EXTRACTION_VERSION


@pytest.mark.parametrize(("statuses", "prices", "errors", "expected"), [
    (["ok", "ok"], [5, 5], [], "ok"),
    ([], [], [], "ok"),
    (["ok", "failed"], [5, None], [], "partial"),
    (["ok", "ok"], [5, 5], ["matching: boom"], "partial"),
    (["partial"], [3], [], "partial"),
    (["failed", "failed"], [None, None], [], "failed"),
    ([], [], ["matching: boom"], "failed"),
])
def test_run_status(statuses, prices, errors, expected) -> None:
    rows = [StoreRow("s", status, prices_added=p) for status, p in zip(statuses, prices)]
    assert run_status(rows, errors) == expected


# ------------------------------------------------------------------ database

STORES = ("teststore", "teststore2")


@pytest.fixture
def connection(monkeypatch, database_url):
    for store in STORES:
        monkeypatch.setitem(raw_listings.STORES, store, f"https://{store}.example")
        monkeypatch.setitem(raw_listings.CLEAN_STOP, store, raw_listings._maicao_stop)
    with psycopg.connect(database_url) as connection:
        connection.execute("SELECT 1")  # an open transaction turns every transaction() below into a savepoint
        try:
            yield connection
        finally:
            connection.rollback()
            leaked = connection.execute("SELECT count(*) FROM stores WHERE name = ANY(%s)", (list(STORES),)).fetchone()[0]
            connection.rollback()
            assert leaked == 0, "test rows were committed to the database"


def write_scrape(directory: Path, store: str, n: int, *, hour: int, step="done", stop="short_page") -> Path:
    path = directory / f"{store}_2030010{hour}.json"
    path.write_text(json.dumps({
        "store": store, "scraped_at": f"2030-01-01T{hour:02d}:00:00+00:00",
        "price_extraction_version": PRICE_EXTRACTION_VERSION, "progress": {"step": step},
        "pagination": {"stop_reason": stop},
        "products": [{"url": f"https://{store}.example/p{i}", "name": f"Perfume {i} EDP 100 ml", "brand": "Test",
                      "current_price": "$10.000", "availability": "available"} for i in range(n)],
    }), encoding="utf-8")
    return path


def fake_scraper(directory: Path, results: dict):
    """results: store -> callable(directory) returning an outcome."""
    return lambda store: results[store](directory)


def ok_scrape(store, n=3, hour=5):
    def scrape(directory):
        return ScrapeOutcome(store, write_scrape(directory, store, n, hour=hour), duration=1.0)
    return scrape


def timed_out_scrape(store, n=0, hour=5):
    def scrape(directory):
        path = write_scrape(directory, store, n, hour=hour, step="listing:goto")
        return ScrapeOutcome(store, path, duration=1800.0, error="timeout after 30 min", stop_reason="timeout")
    return scrape


def recorded(connection):
    run = connection.execute(
        "SELECT run_id, status::text, finished_at IS NOT NULL, errors, embeddings_added FROM scrape_runs "
        "ORDER BY run_id DESC LIMIT 1").fetchone()
    stores = connection.execute(
        "SELECT store, status::text, is_backfill, prices_added, listings_deactivated, stop_reason, error "
        "FROM scrape_run_stores WHERE run_id = %s ORDER BY store, scraped_at NULLS LAST", (run[0],)).fetchall()
    return run, stores


def test_a_failed_store_does_not_block_the_others(connection, tmp_path) -> None:
    matched = []
    summary = tmp_path / "runs" / "summary.log"
    status = run(lambda: connection, list(STORES), directory=tmp_path, summary_path=summary,
                 scrape=fake_scraper(tmp_path, {"teststore": ok_scrape("teststore"),
                                                "teststore2": timed_out_scrape("teststore2")}),
                 embed=lambda c: 0, match=lambda c: matched.append(True) or {"listing_status": {}})
    assert status == "partial"
    assert matched  # matching still ran
    line = summary.read_text(encoding="utf-8").splitlines()[-1]
    assert "PARTIAL" in line and "teststore ok 3 prod +3 precios" in line
    assert "teststore2 failed [timeout]" in line and "errores 1" in line
    (run_id, run_state, finished, errors, _), stores = recorded(connection)
    assert (run_state, finished, errors) == ("partial", True, [])
    assert stores[0][:4] == ("teststore", "ok", False, 3)
    assert stores[1][0:2] == ("teststore2", "failed") and stores[1][5] == "timeout"
    assert "timeout" in stores[1][6]


def test_unfinished_scrape_with_known_listings_is_partial(connection, tmp_path) -> None:
    write_scrape(tmp_path, "teststore", 3, hour=1)
    run(lambda: connection, ["teststore"], skip_scrape=True, directory=tmp_path,
        embed=lambda c: 0, match=lambda c: {})
    status = run(lambda: connection, ["teststore"], directory=tmp_path,
                 scrape=fake_scraper(tmp_path, {"teststore": timed_out_scrape("teststore", n=2, hour=2)}),
                 embed=lambda c: 0, match=lambda c: {})
    _, stores = recorded(connection)
    assert status == "partial"
    assert stores == [("teststore", "partial", False, 2, 0, "timeout", "timeout after 30 min")]


def test_pending_files_are_backfilled_and_only_the_newest_deactivates(connection, tmp_path) -> None:
    write_scrape(tmp_path, "teststore", 5, hour=1)
    run(lambda: connection, ["teststore"], skip_scrape=True, directory=tmp_path, embed=lambda c: 0, match=lambda c: {})
    # the database was down on the run of hour 2: its file is still on disk
    write_scrape(tmp_path, "teststore", 4, hour=2)
    status = run(lambda: connection, ["teststore"], directory=tmp_path,
                 scrape=fake_scraper(tmp_path, {"teststore": ok_scrape("teststore", n=5, hour=3)}),
                 embed=lambda c: 0, match=lambda c: {})
    _, stores = recorded(connection)
    assert status == "ok"
    assert [(s[2], s[3], s[4]) for s in stores] == [(True, 4, 0), (False, 5, 0)]  # backfill, then today's


def test_embedding_and_matching_failures_keep_the_prices(connection, tmp_path) -> None:
    def broken(_):
        raise RuntimeError("boom")
    status = run(lambda: connection, ["teststore"], directory=tmp_path,
                 scrape=fake_scraper(tmp_path, {"teststore": ok_scrape("teststore")}), embed=broken, match=broken)
    (_, state, _, errors, _), stores = recorded(connection)
    assert status == state == "partial"
    assert errors == ["embeddings: boom", "matching: boom"]
    assert stores[0][3] == 3  # prices were loaded anyway


def test_database_down_still_scrapes(tmp_path) -> None:
    scraped = []
    summary = tmp_path / "summary.log"
    status = run(lambda: None, ["teststore"], directory=tmp_path, summary_path=summary,
                 scrape=lambda store: scraped.append(store) or ScrapeOutcome(store, tmp_path / "x.json", 1.0),
                 embed=lambda c: 0, match=lambda c: {})
    assert status == "failed" and scraped == ["teststore"]
    assert "FAILED" in summary.read_text(encoding="utf-8")


def test_scrapers_run_with_the_console_interpreter(monkeypatch, tmp_path) -> None:
    (tmp_path / "python.exe").touch()
    monkeypatch.setattr(daily_run.sys, "executable", str(tmp_path / "pythonw.exe"))
    assert daily_run._console_python() == str(tmp_path / "python.exe")
    monkeypatch.setattr(daily_run.sys, "executable", str(tmp_path / "python.exe"))
    assert daily_run._console_python() == str(tmp_path / "python.exe")


def test_scrapers_are_known_stores() -> None:
    assert set(daily_run.SCRAPERS) == set(raw_listings.STORES) - set(STORES)
