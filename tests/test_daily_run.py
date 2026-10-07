"""The daily run with fake scrapers, embeddings and matching.

Database tests run in beautymatch_test (see conftest.py) with fake stores,
inside a transaction that is rolled back.
"""

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
import pytest

from src import daily_run
from src.daily_run import ScrapeOutcome, StoreRow, run, run_status
from src.db_lock import acquire_writer_lock, lock_holder
from src.loader import raw_listings
from src.matching import pipeline
from src.scrapers.prices import PRICE_EXTRACTION_VERSION
from tests.test_db_lock import has_keepalives


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


def test_preunic_total_mismatch_marks_the_store_partial(connection, monkeypatch, tmp_path) -> None:
    monkeypatch.setitem(raw_listings.CLEAN_STOP, "teststore", raw_listings._preunic_stop)
    monkeypatch.setitem(raw_listings.COMPLETENESS, "teststore", raw_listings._matches_site_total)

    def scrape_with_total(directory):
        path = write_scrape(directory, "teststore", 3, hour=5)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["pagination"] = {"catalog_exhausted": True, "site_total": 4}  # the page says 4, 3 were read
        path.write_text(json.dumps(data), encoding="utf-8")
        return ScrapeOutcome("teststore", path, duration=1.0)

    status = run(lambda: connection, ["teststore"], directory=tmp_path,
                 scrape=fake_scraper(tmp_path, {"teststore": scrape_with_total}), embed=lambda c: 0, match=lambda c: {})
    _, stores = recorded(connection)
    assert status == "partial"
    assert stores == [("teststore", "partial", False, 3, 0, "catalog_exhausted", None)]
    notes = connection.execute("SELECT notes FROM scrape_run_stores ORDER BY run_store_id DESC LIMIT 1").fetchone()[0]
    assert "read 3 listings, the store reports 4" in notes


def test_maicao_without_a_total_falls_back_to_coverage_and_says_so(connection, monkeypatch, tmp_path, caplog) -> None:
    monkeypatch.setitem(raw_listings.COMPLETENESS, "teststore", raw_listings._site_total_or_coverage)
    caplog.set_level("INFO", logger="daily_run")
    status = run(lambda: connection, ["teststore"], directory=tmp_path,  # write_scrape has no site_total
                 scrape=fake_scraper(tmp_path, {"teststore": ok_scrape("teststore")}),
                 embed=lambda c: 0, match=lambda c: {})
    notes = connection.execute("SELECT notes FROM scrape_run_stores ORDER BY run_store_id DESC LIMIT 1").fetchone()[0]
    assert status == "ok"  # first load: nothing active before, coverage passes
    assert notes == ["store total not captured: used the 80% coverage rule"]
    assert "store total not captured: used the 80% coverage rule" in caplog.text  # in the run log too


def test_embedding_and_matching_failures_keep_the_prices(connection, tmp_path) -> None:
    def broken(_):
        raise RuntimeError("boom")
    status = run(lambda: connection, ["teststore"], directory=tmp_path,
                 scrape=fake_scraper(tmp_path, {"teststore": ok_scrape("teststore")}), embed=broken, match=broken)
    (_, state, _, errors, _), stores = recorded(connection)
    assert status == state == "partial"
    assert errors == ["embeddings: boom", "matching: boom"]
    assert stores[0][3] == 3  # prices were loaded anyway


def test_the_daily_run_loads_the_embedding_model_offline(connection, monkeypatch, tmp_path) -> None:
    from src.matching import embeddings
    calls = []
    monkeypatch.setattr(embeddings, "embed_listings", lambda c, **kwargs: calls.append(kwargs) or 0)
    run(lambda: connection, ["teststore"], skip_scrape=True, directory=tmp_path, match=lambda c: {})  # default embed
    assert calls == [{"show_progress": False, "offline": True}]


def test_a_missing_model_fails_the_embedding_step_but_keeps_the_prices(connection, monkeypatch, tmp_path) -> None:
    from src.matching import embeddings

    def not_downloaded(c, **kwargs):
        raise embeddings.ModelNotDownloaded("embedding model is not downloaded ... --download-model")

    monkeypatch.setattr(embeddings, "embed_listings", not_downloaded)
    status = run(lambda: connection, ["teststore"], directory=tmp_path,
                 scrape=fake_scraper(tmp_path, {"teststore": ok_scrape("teststore")}), match=lambda c: {})
    (_, state, _, errors, _), stores = recorded(connection)
    assert status == state == "partial"
    assert errors == ["embeddings: embedding model is not downloaded ... --download-model"]
    assert stores[0][3] == 3  # the prices of the run are loaded


def test_run_lock_admits_one_holder(tmp_path) -> None:
    first, second = daily_run.RunLock(tmp_path / "daily_run.lock"), daily_run.RunLock(tmp_path / "daily_run.lock")
    assert first.acquire()
    assert not second.acquire()
    assert second.holder().startswith(f"pid {os.getpid()} since ")
    first.release()
    assert second.acquire()
    second.release()


def test_run_lock_is_held_across_processes_and_freed_when_the_holder_dies(tmp_path) -> None:
    # Another process takes the lock, like a second daily run would.
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import sys, time; from pathlib import Path; from src.daily_run import RunLock; "
         f"lock = RunLock(Path(r'{tmp_path}') / 'daily_run.lock'); print(lock.acquire(), flush=True); time.sleep(60)"],
        stdout=subprocess.PIPE, text=True, cwd=Path(__file__).parent.parent)
    try:
        assert holder.stdout.readline().strip() == "True"
        lock = daily_run.RunLock(tmp_path / "daily_run.lock")
        assert not lock.acquire()
        # (on Windows holder.pid is the venv launcher; the lock belongs to its child interpreter)
        assert lock.holder().startswith("pid ")
    finally:
        # Dies without releasing (the whole tree: on Windows the venv launcher's
        # child interpreter is the one holding the lock): the OS frees the lock.
        daily_run._kill_tree(holder)
        holder.wait()
    deadline = time.monotonic() + 10
    while not lock.acquire() and time.monotonic() < deadline:
        time.sleep(0.2)
    assert lock.handle is not None
    lock.release()


def test_a_second_run_does_nothing_and_says_so(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(daily_run, "RUNS_DIRECTORY", tmp_path)
    monkeypatch.setattr(sys, "argv", ["daily_run", "--skip-scrape"])
    monkeypatch.setattr(daily_run, "ensure_database",
                        lambda url: pytest.fail("a skipped run must not touch the database"))
    running = daily_run.RunLock(tmp_path / "daily_run.lock")
    assert running.acquire()
    try:
        with pytest.raises(SystemExit) as exit_:
            daily_run.main()
    finally:
        running.release()
    assert exit_.value.code == 3
    summary = (tmp_path / "summary.log").read_text(encoding="utf-8")
    assert "SKIPPED  another daily run is in progress (pid" in summary
    assert not list(tmp_path.glob("run_*.log"))  # no run started


def test_a_complete_run_does_not_block_itself(connection, monkeypatch, tmp_path) -> None:
    # fake scrapers, then the real loading, embeddings and matching: none of them takes the
    # writer lock again (only the entry points do), so the run that holds it is never stopped
    monkeypatch.setattr(pipeline, "export_review_queue", lambda listings, plan: tmp_path / "queue.csv")
    summary = tmp_path / "runs" / "summary.log"
    status = run(lambda: connection, list(STORES), directory=tmp_path, summary_path=summary,
                 scrape=fake_scraper(tmp_path, {"teststore": ok_scrape("teststore"),
                                                "teststore2": ok_scrape("teststore2")}))
    assert status == "ok", summary.read_text(encoding="utf-8")
    (run_id, run_state, finished, errors, embedded), stores = recorded(connection)
    assert (run_state, finished, errors) == ("ok", True, [])
    assert [(store, state) for store, state, *_ in stores] == [("teststore", "ok"), ("teststore2", "ok")]
    assert lock_holder(connection).startswith("daily_run")  # still held by the run's connection


def test_a_run_while_another_process_writes_is_skipped(connection, database_url, tmp_path) -> None:
    scraped = []
    summary = tmp_path / "summary.log"
    runs_before = connection.execute("SELECT count(*) FROM scrape_runs").fetchone()[0]
    with psycopg.connect(database_url, autocommit=True) as other:
        acquire_writer_lock(other, r"daily_run C:\other\copy")
        status = run(lambda: connection, list(STORES), directory=tmp_path, summary_path=summary,
                     scrape=lambda store: scraped.append(store), embed=lambda c: 0, match=lambda c: {})
    assert status == "skipped" and scraped == []
    assert connection.execute("SELECT count(*) FROM scrape_runs").fetchone()[0] == runs_before
    line = summary.read_text(encoding="utf-8").splitlines()[-1]
    assert "SKIPPED" in line and r"another process is writing to the database: daily_run C:\other\copy" in line


def test_a_run_that_loses_its_lock_writes_nothing_more(connection, tmp_path) -> None:
    def scrape_then_lose_the_lock(store):
        outcome = ok_scrape(store)(tmp_path)
        connection.execute("SELECT pg_advisory_unlock_all()")  # as if the session had been reset
        return outcome

    summary = tmp_path / "summary.log"
    status = run(lambda: connection, ["teststore"], directory=tmp_path, summary_path=summary,
                 scrape=scrape_then_lose_the_lock, embed=lambda c: 0, match=lambda c: {})
    assert status == "failed"
    loaded = connection.execute("SELECT count(*) FROM raw_listings rl JOIN stores s USING (store_id) "
                                "WHERE s.name = 'teststore'").fetchone()[0]
    assert loaded == 0  # stopped before loading
    assert "lock: daily_run" in summary.read_text(encoding="utf-8").splitlines()[-1]


def test_the_loader_by_hand_stops_while_another_process_writes(database_url, monkeypatch, tmp_path) -> None:
    path = write_scrape(tmp_path, "teststore", 2, hour=5)
    monkeypatch.setattr(sys, "argv", ["raw_listings", "--database-url", database_url, str(path)])
    with psycopg.connect(database_url, autocommit=True) as other:
        acquire_writer_lock(other, "daily_run")
        with pytest.raises(SystemExit, match="another process is writing to the database: daily_run"):
            raw_listings.main()


class Opened(Exception):
    """Raised by a stub to stop an entry point once its writer connection is open."""


def test_every_entry_point_holds_the_lock_on_a_keepalive_connection(database_url, monkeypatch, tmp_path) -> None:
    keepalives = []

    def stop_here(connection, *args, **kwargs):
        keepalives.append(has_keepalives(connection))
        raise Opened

    # the daily run: its connection to the database
    def fake_run(connect, stores, **kwargs):
        stop_here(connect())

    monkeypatch.setenv("HF_HUB_OFFLINE", "0")  # main sets it; restored afterwards
    monkeypatch.setattr(daily_run, "RUNS_DIRECTORY", tmp_path / "runs")
    monkeypatch.setattr(daily_run, "configure_logging", lambda path: None)
    monkeypatch.setattr(daily_run, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["daily_run", "--database-url", database_url])
    with pytest.raises(SystemExit):  # the stub's exception ends as a crashed run (exit 2)
        daily_run.main()

    # the loader and the matching pipeline by hand
    monkeypatch.setattr(raw_listings, "load_file", stop_here)
    monkeypatch.setattr(sys, "argv", ["raw_listings", "--database-url", database_url,
                                      str(write_scrape(tmp_path, "teststore", 2, hour=5))])
    with pytest.raises(Opened):
        raw_listings.main()
    monkeypatch.setattr(pipeline, "run_matching", stop_here)
    monkeypatch.setattr(sys, "argv", ["pipeline", "--database-url", database_url])
    with pytest.raises(Opened):
        pipeline.main()

    assert keepalives == [True, True, True]


# ------------------------------------------------------------------- network


class FakeClock:
    """time.monotonic and time.sleep for wait_for_network: sleeping moves the clock, nothing waits."""

    def __init__(self):
        self.now = 0.0
        self.checks: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def resolver(clock: FakeClock, up: Callable[[str, float], bool]):
    """A fake DNS: up(host, seconds since the start) says whether the host resolves then."""
    def resolve(host: str) -> bool:
        clock.checks.append(clock.now)
        return up(host, clock.now)
    return resolve


def wait(up: Callable[[str, float], bool], hosts=("preunic.cl", "www.maicao.cl")) -> tuple[bool, FakeClock]:
    clock = FakeClock()
    ready = daily_run.wait_for_network(list(hosts), resolve=resolver(clock, up), sleep=clock.sleep, clock=clock)
    return ready, clock


def test_with_network_the_run_starts_after_two_resolutions_30_s_apart() -> None:
    ready, clock = wait(lambda host, t: True)
    assert ready and clock.now == 30


def test_one_store_domain_failing_is_not_a_network_outage() -> None:
    ready, clock = wait(lambda host, t: host == "www.maicao.cl")
    assert ready and clock.now == 30


def test_a_short_connection_does_not_start_the_run() -> None:
    # like 2026-10-07 09:01: the Wi-Fi up for about a minute between outages
    ready, clock = wait(lambda host, t: t == 60 or t >= 300)
    assert ready and clock.now == 330  # not at 60: it had to resolve again at 90


def test_without_network_it_gives_up_after_10_minutes() -> None:
    ready, clock = wait(lambda host, t: False)
    assert not ready and clock.now == 600
    assert sorted(set(clock.checks)) == [30.0 * i for i in range(21)]  # every 30 s, from 0 to 600


def test_a_run_without_network_is_skipped_before_touching_the_database(connection, tmp_path) -> None:
    scraped, connected, asked = [], [], []
    summary = tmp_path / "summary.log"
    runs_before = connection.execute("SELECT count(*) FROM scrape_runs").fetchone()[0]

    def no_network(hosts):
        asked.append(hosts)
        return False

    status = run(lambda: connected.append(True) or connection, list(STORES), directory=tmp_path,
                 summary_path=summary, network=no_network, scrape=lambda store: scraped.append(store),
                 embed=lambda c: 0, match=lambda c: {})
    assert status == "skipped"
    assert asked == [["teststore.example", "teststore2.example"]]
    assert scraped == [] and connected == []  # no database connection: no writer lock, no scrape_runs row
    assert connection.execute("SELECT count(*) FROM scrape_runs").fetchone()[0] == runs_before
    line = summary.read_text(encoding="utf-8").splitlines()[-1]
    assert "SKIPPED" in line
    assert "sin red: ningún dominio de tienda resolvió 2 veces seguidas en 10 min " \
           "(teststore.example, teststore2.example)" in line


def test_a_run_with_network_goes_on(connection, tmp_path) -> None:
    asked = []
    status = run(lambda: connection, list(STORES), directory=tmp_path, network=lambda hosts: asked.append(hosts) or True,
                 scrape=fake_scraper(tmp_path, {"teststore": ok_scrape("teststore"),
                                                "teststore2": ok_scrape("teststore2")}),
                 embed=lambda c: 0, match=lambda c: {})
    assert status == "ok" and len(asked) == 1


def test_loading_pending_files_does_not_need_the_network(connection, tmp_path) -> None:
    status = run(lambda: connection, list(STORES), directory=tmp_path, skip_scrape=True,
                 network=lambda hosts: pytest.fail("--skip-scrape scrapes nothing: no network check"),
                 embed=lambda c: 0, match=lambda c: {})
    assert status == "ok"


def test_the_scheduled_run_checks_the_network(database_url, monkeypatch, tmp_path) -> None:
    passed = {}

    def fake_run(connect, stores, **kwargs):
        passed.update(kwargs)
        return "ok"

    monkeypatch.setenv("HF_HUB_OFFLINE", "0")  # main sets it; restored afterwards
    monkeypatch.setattr(daily_run, "RUNS_DIRECTORY", tmp_path / "runs")
    monkeypatch.setattr(daily_run, "configure_logging", lambda path: None)
    monkeypatch.setattr(daily_run, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["daily_run", "--database-url", database_url])
    with pytest.raises(SystemExit) as exit_:
        daily_run.main()
    assert exit_.value.code == 0 and passed["network"] is daily_run.wait_for_network


def test_every_daily_store_has_a_domain_to_check() -> None:
    for store in daily_run.SCRAPERS:
        assert urlsplit(raw_listings.STORES[store]).hostname.endswith(".cl")


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
    assert set(daily_run.SCRAPERS) <= set(raw_listings.STORES) - set(STORES)


def test_matched_stores_are_scraped_daily() -> None:
    from src.matching.pipeline import MATCHING_STORES
    assert set(MATCHING_STORES) <= set(daily_run.SCRAPERS)  # every matched store is scraped daily
