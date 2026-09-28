"""Daily run: scrape every store, load prices, embed new listings and match.

Usage:
    python -m src.daily_run                   # full run
    python -m src.daily_run --stores maicao   # only some stores
    python -m src.daily_run --skip-scrape     # load pending files, embed, match
    python -m src.daily_run --status          # last runs, from the database

Each step is independent: a store whose scraper fails does not stop the
others, and prices already loaded stay loaded if embeddings or matching fail.
Every run is recorded in scrape_runs / scrape_run_stores (database/004), in
artifacts/runs/run_<timestamp>.log (details) and as one line in
artifacts/runs/summary.log (to check the runs without a terminal).

If the database is down the scrapers still run; their files are loaded by the
next run (every scrape file newer than the store's last loaded price).

Exit code: 0 when the run is "ok", 1 when "partial" or "failed" (visible in
the Windows Task Scheduler as the last run result).
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from src.loader.raw_listings import DEFAULT_DATABASE_URL, RAW_DIRECTORY, STORES, ScrapeError, load_file, pending_files

logger = logging.getLogger("daily_run")

SCRAPERS = {"preunic": "src.cli", "maicao": "src.maicao_cli"}  # module run with --output <path>
RUNS_DIRECTORY = Path("artifacts/runs")
SCRAPE_TIMEOUT_MINUTES = 30   # a normal scrape takes 2-5 minutes
DATABASE_WAIT_SECONDS = 180   # how long to wait for Docker Desktop + the container
DB_CONTAINER = os.environ.get("BM_DB_CONTAINER", "bm-pg")
# The scheduled task runs pythonw.exe (no console). Console programs started
# from it would each open a window, so they are started with CREATE_NO_WINDOW.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _console_python() -> str:
    """python.exe next to pythonw.exe: scrapers print to a pipe, which needs a console-mode interpreter."""
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe" and (executable.parent / "python.exe").exists():
        return str(executable.parent / "python.exe")
    return sys.executable


# ------------------------------------------------------------------- scraping


@dataclass
class ScrapeOutcome:
    store: str
    path: Path
    duration: float
    error: str | None = None       # None = the scraper process exited cleanly
    stop_reason: str | None = None  # timeout / exit_code_<n>, when it did not


def _kill_tree(process: subprocess.Popen) -> None:
    # Killing only python.exe on Windows leaves Chromium running.
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True,
                       creationflags=NO_WINDOW)
    else:
        process.kill()


def scrape_store(store: str, timeout_minutes: float = SCRAPE_TIMEOUT_MINUTES,
                 directory: Path = RAW_DIRECTORY) -> ScrapeOutcome:
    """Run one store's scraper in its own process, with a time limit."""
    path = directory / f"{store}_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    command = [_console_python(), "-m", SCRAPERS[store], "--output", str(path)]
    logger.info("[%s] scraping -> %s", store, path)
    started = time.monotonic()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                               creationflags=NO_WINDOW)
    outcome = ScrapeOutcome(store, path, 0.0)
    try:
        output, _ = process.communicate(timeout=timeout_minutes * 60)
    except subprocess.TimeoutExpired:
        _kill_tree(process)
        output, _ = process.communicate()
        outcome.error, outcome.stop_reason = f"timeout after {timeout_minutes:g} min", "timeout"
    else:
        if process.returncode != 0:
            outcome.error = f"scraper exited with code {process.returncode}"
            outcome.stop_reason = f"exit_code_{process.returncode}"
    outcome.duration = time.monotonic() - started
    for line in (output or "").splitlines():
        logger.info("[%s]   %s", store, line)
    if outcome.error:
        logger.error("[%s] %s (%.0fs)", store, outcome.error, outcome.duration)
    else:
        logger.info("[%s] scraped in %.0fs", store, outcome.duration)
    return outcome


# ------------------------------------------------------------------- database


def database_ready(database_url: str) -> bool:
    try:
        with psycopg.connect(database_url, connect_timeout=5) as connection:
            connection.execute("SELECT 1")
        return True
    except psycopg.OperationalError:
        return False


def _find_docker() -> tuple[str | None, str | None]:
    """(docker CLI, Docker Desktop executable), None when not found."""
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "DockerDesktop"
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Docker" / "Docker"
    cli = shutil.which("docker") or next(
        (str(p) for p in (local / "resources/bin/docker.exe", program_files / "resources/bin/docker.exe")
         if p.exists()), None)
    desktop = next((str(p) for p in (local / "Docker Desktop.exe", program_files / "Docker Desktop.exe")
                    if p.exists()), None)
    return cli, desktop


def ensure_database(database_url: str, wait_seconds: float = DATABASE_WAIT_SECONDS) -> bool:
    """Is the database up? If not, try to start Docker Desktop and the container."""
    if database_ready(database_url):
        return True
    cli, desktop = _find_docker()
    logger.warning("database not answering; starting Docker Desktop and container %s", DB_CONTAINER)
    if cli is None:
        logger.error("docker CLI not found")
        return False

    def docker_up() -> bool:
        return subprocess.run([cli, "info"], capture_output=True, timeout=30, creationflags=NO_WINDOW).returncode == 0

    if not docker_up() and desktop:
        subprocess.Popen([desktop])
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if docker_up():
            subprocess.run([cli, "start", DB_CONTAINER], capture_output=True, timeout=60, creationflags=NO_WINDOW)
            if database_ready(database_url):
                logger.info("database is up")
                return True
        time.sleep(5)
    logger.error("database still down after %.0fs", wait_seconds)
    return False


# ------------------------------------------------------------------ run log


@dataclass
class StoreRow:
    """One scrape_run_stores row."""
    store: str
    status: str
    file: str | None = None
    scraped_at: datetime | None = None
    is_backfill: bool = False
    stop_reason: str | None = None
    products_scraped: int | None = None
    listings_new: int | None = None
    listings_updated: int | None = None
    prices_added: int | None = None
    listings_deactivated: int | None = None
    rows_skipped: int | None = None
    duration_seconds: float | None = None
    notes: list[str] = field(default_factory=list)
    error: str | None = None


INSERT_STORE_ROW = """
INSERT INTO scrape_run_stores (run_id, store, file, scraped_at, is_backfill, status, stop_reason, products_scraped,
    listings_new, listings_updated, prices_added, listings_deactivated, rows_skipped, duration_seconds, notes, error)
VALUES (%(run_id)s, %(store)s, %(file)s, %(scraped_at)s, %(is_backfill)s, %(status)s::run_status, %(stop_reason)s,
    %(products_scraped)s, %(listings_new)s, %(listings_updated)s, %(prices_added)s, %(listings_deactivated)s,
    %(rows_skipped)s, %(duration_seconds)s, %(notes)s, %(error)s)
"""


def run_status(rows: list[StoreRow], errors: list[str]) -> str:
    """ok: everything worked. failed: no price was loaded. partial: anything in between."""
    if not errors and rows and all(row.status == "ok" for row in rows):
        return "ok"
    if not errors and not rows:
        return "ok"  # nothing to do (e.g. --skip-scrape with no pending files)
    return "partial" if any(row.prices_added for row in rows) else "failed"


def load_store(connection: psycopg.Connection, store: str, own: ScrapeOutcome | None,
               directory: Path = RAW_DIRECTORY) -> list[StoreRow]:
    """Load this run's file of the store plus any pending older ones."""
    files = pending_files(connection, store, directory)
    rows = []
    for path in files:
        is_own = own is not None and path.resolve() == own.path.resolve()
        row = StoreRow(store, "failed", file=path.name, is_backfill=not is_own)
        started = time.monotonic()
        try:
            # Deactivate only from the newest file; load_file itself refuses when it is not complete.
            stats = load_file(connection, path, deactivate_missing=path == files[-1], allow_unfinished=True)
        except (ScrapeError, psycopg.Error) as error:
            row.error = str(error)
            logger.error("[%s] loading %s failed: %s", store, path.name, error)
        else:
            row.status = "ok" if stats["complete"] else "partial" if stats["prices_added"] else "failed"
            row.scraped_at, row.stop_reason, row.notes = stats["scraped_at"], stats["stop_reason"], stats["notes"]
            row.products_scraped, row.rows_skipped = stats["products"], stats["skipped"]
            row.listings_new, row.listings_updated = stats["inserted"], stats["updated"]
            row.prices_added, row.listings_deactivated = stats["prices_added"], stats["deactivated"]
            logger.info("[%s] loaded %s: %s, %d products, +%d prices, %d new, %d deactivated%s", store, path.name,
                        row.status, row.products_scraped, row.prices_added, row.listings_new,
                        row.listings_deactivated, f" ({'; '.join(row.notes)})" if row.notes else "")
        row.duration_seconds = time.monotonic() - started + (own.duration if is_own else 0)
        if is_own and own.error:
            row.stop_reason = own.stop_reason
            row.error = "; ".join(filter(None, [own.error, row.error]))
            if row.status == "ok":  # the process failed after writing a complete file: still not clean
                row.status = "partial"
        rows.append(row)
    if own is not None and not any(not row.is_backfill for row in rows):
        # The scraper left no loadable file (no products, or it died at the start).
        rows.append(StoreRow(store, "failed", file=own.path.name if own.path.exists() else None,
                             stop_reason=own.stop_reason, duration_seconds=round(own.duration, 1),
                             error=own.error or "the scrape file has no products"))
        logger.error("[%s] nothing loaded from this run's scrape: %s", store, rows[-1].error)
    return rows


# ------------------------------------------------------------------------ run


def summary_line(started: datetime, status: str, rows: list[StoreRow], errors: list[str],
                 embeddings_added: int | None, log_path: Path | None) -> str:
    """One line per run for artifacts/runs/summary.log."""
    stores = " | ".join(
        f"{row.store}{' (backfill)' if row.is_backfill else ''} {row.status}"
        + (f" {row.products_scraped} prod +{row.prices_added} precios" if row.prices_added is not None else "")
        + (f" [{row.stop_reason}]" if row.status != "ok" and row.stop_reason else "")
        for row in rows
    ) or "sin tiendas cargadas"
    errors_count = len(errors) + sum(1 for row in rows if row.error)
    return (f"{started.astimezone():%Y-%m-%d %H:%M}  {status.upper():8} {stores} | "
            f"embeddings +{embeddings_added or 0} | errores {errors_count}"
            + (f" | {log_path.name}" if log_path else ""))


def run(
    connection_factory: Callable[[], psycopg.Connection | None],
    stores: list[str],
    *,
    skip_scrape: bool = False,
    scrape: Callable[[str], ScrapeOutcome] = scrape_store,
    embed: Callable[[psycopg.Connection], int] | None = None,
    match: Callable[[psycopg.Connection], dict] | None = None,
    directory: Path = RAW_DIRECTORY,
    log_path: Path | None = None,
    summary_path: Path | None = None,
) -> str:
    """One daily run; returns its status. connection_factory returns None when the database is down."""
    started = datetime.now(UTC)

    def write_summary(status: str, rows: list[StoreRow], errors: list[str], embeddings_added: int | None) -> None:
        if summary_path is not None:
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            with summary_path.open("a", encoding="utf-8") as summary:
                summary.write(summary_line(started, status, rows, errors, embeddings_added, log_path) + "\n")

    if embed is None:
        from src.matching.embeddings import embed_listings
        embed = lambda connection: embed_listings(connection, show_progress=False)  # noqa: E731
    if match is None:
        from src.matching.pipeline import run_matching
        match = run_matching

    connection = connection_factory()
    run_id = None
    if connection is not None:
        run_id = connection.execute("INSERT INTO scrape_runs (log_path) VALUES (%s) RETURNING run_id",
                                    (str(log_path) if log_path else None,)).fetchone()[0]
        logger.info("run %s started", run_id)
    else:
        logger.error("database unavailable: scraping only; the next run will load these files")

    outcomes = {} if skip_scrape else {store: scrape(store) for store in stores}
    if connection is None:
        write_summary("failed", [], ["database unavailable: files will be loaded by the next run"], None)
        return "failed"

    rows: list[StoreRow] = []
    errors: list[str] = []
    for store in stores:
        rows += load_store(connection, store, outcomes.get(store), directory)
    for row in rows:
        connection.execute(INSERT_STORE_ROW, {**row.__dict__, "run_id": run_id,
                                              "duration_seconds": round(row.duration_seconds or 0, 1)})

    embeddings_added = None
    try:
        embeddings_added = embed(connection)
        logger.info("embeddings: %d listings", embeddings_added)
    except (Exception, SystemExit) as error:  # load_model raises SystemExit on a wrong model
        errors.append(f"embeddings: {error}")
        logger.exception("embeddings failed")

    pipeline_stats = None
    try:
        pipeline_stats = match(connection)
        logger.info("matching: %s", pipeline_stats.get("listing_status"))
    except Exception as error:
        errors.append(f"matching: {error}")
        logger.exception("matching failed")

    status = run_status(rows, errors)
    connection.execute(
        """UPDATE scrape_runs SET finished_at = now(), status = %s::run_status, embeddings_added = %s,
               pipeline_stats = %s, errors = %s WHERE run_id = %s""",
        (status, embeddings_added, Jsonb(pipeline_stats) if pipeline_stats else None, errors, run_id),
    )
    logger.info("run %s finished: %s", run_id, status)
    write_summary(status, rows, errors, embeddings_added)
    return status


# --------------------------------------------------------------------- status


STATUS_QUERY = """
SELECT r.run_id, r.started_at, r.finished_at, r.status::text, r.embeddings_added, r.pipeline_stats, r.errors,
       coalesce(json_agg(s ORDER BY s.store, s.scraped_at) FILTER (WHERE s.run_store_id IS NOT NULL), '[]')
FROM scrape_runs r LEFT JOIN scrape_run_stores s ON s.run_id = r.run_id
GROUP BY r.run_id ORDER BY r.run_id DESC LIMIT %s
"""


def print_status(connection: psycopg.Connection, limit: int) -> None:
    runs = connection.execute(STATUS_QUERY, (limit,)).fetchall()
    if not runs:
        print("No runs yet.")
    for run_id, started, finished, status, embedded, pipeline, errors, stores in runs:
        end = f"{finished.astimezone():%H:%M}" if finished else "-- (interrupted or running)"
        print(f"run {run_id}  {started.astimezone():%Y-%m-%d %H:%M} -> {end}  {status.upper()}")
        for s in stores:
            line = (f"    {s['store']:8} {s['status']:8}"
                    + (" backfill" if s["is_backfill"] else "")
                    + (f" {s['products_scraped']} products, +{s['prices_added']} prices, "
                       f"{s['listings_new']} new, {s['listings_deactivated']} deactivated"
                       if s["prices_added"] is not None else "")
                    + (f" [{s['stop_reason']}]" if s["stop_reason"] else ""))
            print(line)
            for note in s["notes"] or []:
                print(f"             note: {note}")
            if s["error"]:
                print(f"             ERROR: {s['error']}")
        if pipeline:
            print(f"    embeddings +{embedded or 0} | matching: {pipeline.get('listing_status')}")
        for error in errors or []:
            print(f"    ERROR: {error}")


# ----------------------------------------------------------------------- main


def configure_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    handlers: list[logging.Handler] = [logging.FileHandler(log_path, encoding="utf-8")]
    if sys.stdout is not None:  # None under pythonw.exe (the scheduled task)
        handlers.append(logging.StreamHandler(sys.stdout))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily scrape, load, embed and match")
    parser.add_argument("--stores", default=",".join(SCRAPERS),
                        help=f"comma-separated stores (default: {','.join(SCRAPERS)})")
    parser.add_argument("--skip-scrape", action="store_true", help="only load pending files, embed and match")
    parser.add_argument("--timeout", type=float, default=SCRAPE_TIMEOUT_MINUTES,
                        help="minutes before a scraper is killed")
    parser.add_argument("--status", nargs="?", const=10, type=int, metavar="N", help="show the last N runs")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    args = parser.parse_args()

    if args.status is not None:
        with psycopg.connect(args.database_url) as connection:
            print_status(connection, args.status)
        return

    stores = [store.strip() for store in args.stores.split(",") if store.strip()]
    unknown = [store for store in stores if store not in SCRAPERS or store not in STORES]
    if unknown:
        parser.error(f"unknown stores: {', '.join(unknown)}")

    log_path = RUNS_DIRECTORY / f"run_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.log"
    configure_logging(log_path)
    logger.info("daily run: stores=%s skip_scrape=%s log=%s", stores, args.skip_scrape, log_path)

    opened: list[psycopg.Connection] = []

    def connect() -> psycopg.Connection | None:
        if not ensure_database(args.database_url):
            return None
        opened.append(psycopg.connect(args.database_url, autocommit=True))  # each step commits on its own
        return opened[-1]

    try:
        status = run(connect, stores, skip_scrape=args.skip_scrape,
                     scrape=lambda store: scrape_store(store, args.timeout), log_path=log_path,
                     summary_path=RUNS_DIRECTORY / "summary.log")
    except Exception:
        # The run row stays 'running' without finished_at: visible in --status.
        logger.exception("daily run crashed")
        sys.exit(2)
    finally:
        for connection in opened:
            connection.close()
    sys.exit(0 if status == "ok" else 1)


if __name__ == "__main__":
    main()
