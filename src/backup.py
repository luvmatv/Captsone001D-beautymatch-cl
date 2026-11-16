"""Daily backup of the database, after each run (src/daily_run.py), keeping the last KEEP.

    pg_dump -Fc inside the database container -> checked with pg_restore --list
    -> copied to BACKUP_DIRECTORY as beautymatch_daily_<local date>_<time>_run<N>.dump

The container's pg_dump (PostgreSQL 17) dumps the local database by name, or a
managed one (Neon) by its URL: the container is then only the client. A managed
database must not run a newer major version than that client (pg_dump refuses).
Neon's free plan keeps 6 hours of history, so these files are the real backups.

Without the embeddings (the daily run, since 2026-11-16): pg_dump reads every
row uncompressed (it compresses on the client), and the embedding columns were
69 of the 92 MB each backup took from Neon's 5 GB of monthly transfer. So the
dump leaves out the data of raw_listings and fragrances (EMBEDDING_TABLES, their
schema stays), and export_tables writes those two tables without the embedding
column, as CSV, into <name>.tables.zip next to the dump (~23 MB in all). Both
are read while the run still holds the database writer lock, so nothing writes
in between. The embeddings come back from the local cache or are recomputed
(src/restore_backup.py, docs/daily_run.md "Restaurar un respaldo").

Only files named beautymatch_daily_*.dump (and their .tables.zip) are rotated:
backups made by hand before a change (beautymatch_<date>_pre-*.dump) are never
deleted here. BACKUP_DIRECTORY is BM_BACKUP_DIR, by default ~/bm-backups.

Restore one into a scratch database first, never straight over the live one:
    python -m src.restore_backup <file.dump> --into beautymatch_restore
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import subprocess
import zipfile
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg import sql

from src.db_config import connection_options

logger = logging.getLogger(__name__)

BACKUP_DIRECTORY = Path(os.environ.get("BM_BACKUP_DIR", Path.home() / "bm-backups"))
KEEP = 14
PREFIX = "beautymatch_daily_"
DUMP_TIMEOUT_SECONDS = 300   # ~20 MB today: a few seconds
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


class BackupFailed(RuntimeError):
    pass


def _run(command: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(command), capture_output=True, text=True, timeout=DUMP_TIMEOUT_SECONDS,
                          creationflags=NO_WINDOW)


def backup_name(run_id: int, when: datetime) -> str:
    return f"{PREFIX}{when:%Y%m%d_%H%M}_run{run_id}.dump"


# Tables whose data goes in the companion zip, without their embedding column.
EMBEDDING_TABLES = ("raw_listings", "fragrances")
TABLES_SUFFIX = ".tables.zip"


def tables_file(dump: Path) -> Path:
    """The companion of a dump made without the embedding tables' data: <name>.tables.zip."""
    return dump.with_name(dump.stem + TABLES_SUFFIX)


def rotate(directory: Path, keep: int = KEEP) -> list[str]:
    """Delete the oldest daily backups beyond `keep` (by name: the name starts with the date). Returns their names."""
    daily = sorted(directory.glob(f"{PREFIX}*.dump"))
    old = daily[:-keep] if keep > 0 else daily
    for path in old:
        path.unlink()
        tables_file(path).unlink(missing_ok=True)
    return [path.name for path in old]


def dump_command(container: str, inside: str, database: str, exclude_data: Sequence[str] = ()) -> list[str]:
    """pg_dump inside the container: a local database by name (as user postgres), a remote one by URL (with SSL).

    exclude_data: tables dumped without their rows (their schema, indexes and constraints stay).
    """
    excluded = [f"--exclude-table-data=public.{table}" for table in exclude_data]
    if "://" not in database:
        return ["exec", container, "pg_dump", "-U", "postgres", "-Fc", *excluded, "-f", inside, database]
    options = connection_options(database)
    url = database + (("&" if "?" in database else "?") + "sslmode=" + options["sslmode"] if options else "")
    return ["exec", container, "pg_dump", "-Fc", *excluded, "-f", inside, f"--dbname={url}"]


TABLE_COLUMNS = """
SELECT column_name FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = %s AND column_name <> 'embedding'
ORDER BY ordinal_position
"""


def export_tables(connection: psycopg.Connection, path: Path, tables: Sequence[str] = EMBEDDING_TABLES) -> dict:
    """Write each table without its embedding column as <table>.csv into the zip at path, plus manifest.json.

    Checks that every CSV has as many rows as the table; raises BackupFailed if not.
    Returns the manifest: {"format": 1, "tables": {table: {"columns": [...], "rows": n}}}.
    """
    manifest: dict = {"format": 1, "tables": {}}
    expected = {}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for table in tables:
            columns = [row[0] for row in connection.execute(TABLE_COLUMNS, (table,)).fetchall()]
            expected[table] = connection.execute(
                sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))).fetchone()[0]
            copy_sql = sql.SQL("COPY {} ({}) TO STDOUT (FORMAT csv, HEADER)").format(
                sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, columns)))
            with archive.open(f"{table}.csv", "w") as out, connection.cursor().copy(copy_sql) as copy:
                for data in copy:
                    out.write(data)
            manifest["tables"][table] = {"columns": columns, "rows": expected[table]}
    with zipfile.ZipFile(path) as archive:   # read back: every CSV has the table's rows
        for table in tables:
            with archive.open(f"{table}.csv") as written:
                rows = sum(1 for _ in csv.reader(io.TextIOWrapper(written, encoding="utf-8", newline=""))) - 1
            if rows != expected[table]:
                raise BackupFailed(f"export {table}: {rows} rows in the CSV, {expected[table]} in the table")
    with zipfile.ZipFile(path, "a", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
    return manifest


def export_tables_from(database_url: str) -> Callable[[Path], dict]:
    """export_tables over its own read-only connection to database_url (what the daily run passes)."""
    def export(path: Path) -> dict:
        with psycopg.connect(database_url, **connection_options(database_url)) as connection:
            connection.read_only = True
            return export_tables(connection, path)
    return export


def backup_database(run_id: int, *, docker: str, container: str, database: str,
                    directory: Path = BACKUP_DIRECTORY, keep: int = KEEP, runner: Runner = _run,
                    now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
                    tables: Callable[[Path], dict] | None = None) -> dict:
    """Dump, check, copy and rotate. Raises BackupFailed with what went wrong; nothing half-written is kept.

    database: the local database's name, or a remote database's URL (never logged: it has the password).
    tables: an export_tables function (export_tables_from): the dump then leaves out the data of
    EMBEDDING_TABLES and tables(path) writes them, without embeddings, to <name>.tables.zip.
    Without it, a complete dump as before.
    """
    name = backup_name(run_id, now())
    inside = f"/tmp/{name}"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    partial = target.with_suffix(".partial")
    tables_target = tables_file(target)
    tables_partial = tables_target.with_name(tables_target.name + ".partial")
    exclude = EMBEDDING_TABLES if tables is not None else ()

    def step(what: str, command: Sequence[str]) -> subprocess.CompletedProcess:
        result = runner(command)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip().splitlines()
            raise BackupFailed(f"{what}: {detail[-1] if detail else f'exit {result.returncode}'}")
        return result

    manifest = None
    try:
        step("pg_dump", [docker, *dump_command(container, inside, database, exclude)])
        listing = step("pg_restore --list", [docker, "exec", container, "pg_restore", "--list", inside]).stdout
        entries = sum(1 for line in listing.splitlines() if line.strip() and not line.startswith(";"))
        if entries == 0:
            raise BackupFailed("pg_restore --list: the dump has no entries")
        step("docker cp", [docker, "cp", f"{container}:{inside}", str(partial)])
        if tables is not None:
            try:
                manifest = tables(tables_partial)
            except BackupFailed:
                raise
            except Exception as error:
                raise BackupFailed(f"export tables: {error}") from error
            tables_partial.replace(tables_target)
        partial.replace(target)
    except BaseException:
        partial.unlink(missing_ok=True)
        tables_partial.unlink(missing_ok=True)
        if manifest is not None:   # the zip was moved but the dump was not: keep neither
            tables_target.unlink(missing_ok=True)
        raise
    finally:
        runner([docker, "exec", container, "rm", "-f", inside])  # best effort: the container's /tmp
    deleted = rotate(directory, keep)
    size = target.stat().st_size + (tables_target.stat().st_size if manifest is not None else 0)
    logger.info("backup: %s%s (%.1f MB, %d entries); kept the last %d, deleted %s",
                name, f" + {tables_target.name} (no embeddings)" if manifest is not None else "",
                size / 1e6, entries, keep, deleted or "none")
    report = {"file": str(target), "bytes": size, "entries": entries, "deleted": deleted}
    if manifest is not None:
        report["tables_file"] = str(tables_target)
        report["table_rows"] = {table: info["rows"] for table, info in manifest["tables"].items()}
    return report
