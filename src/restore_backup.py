"""Restore a daily backup into a NEW database of the local container (bm-pg).

    python -m src.restore_backup ~/bm-backups/beautymatch_daily_<...>_run<N>.dump --into beautymatch_restore
    python -m src.restore_backup <file.dump> --into beautymatch_restore --no-cache   # embeddings stay NULL

The target database must not exist (createdb refuses otherwise): this never
writes over a database that is in use. Steps for a backup made without the
embeddings (it has <name>.tables.zip next to it, src/backup.py):

1. pg_restore --section=pre-data: the tables, still without indexes and constraints.
2. pg_restore --section=data: every table's rows but raw_listings' and fragrances'.
3. raw_listings and fragrances from the zip's CSVs, with embedding NULL.
4. pg_restore --section=post-data: indexes, keys and foreign keys, checked
   against all the rows.
5. raw_listings.embedding from the local cache (src/matching/embedding_cache.py)
   for every listing it has: the same vectors, byte for byte.

A complete dump (the ones before 2026-11-16) is restored as is, in one step.
What may still be missing is printed at the end: listings without a vector
(python -m src.matching.embeddings) and fragrances.embedding, which the
pipeline recomputes from its listings (python -m src.matching.pipeline). Both
with DATABASE_URL pointing to the restored database: see docs/daily_run.md.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import zipfile
from collections.abc import Callable, Sequence
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from src.backup import EMBEDDING_TABLES, tables_file
from src.loader.raw_listings import DEFAULT_DATABASE_URL
from src.matching.embedding_cache import CACHE_PATH, EmbeddingCache

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


class RestoreFailed(RuntimeError):
    pass


def _run(command: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(command), capture_output=True, text=True, timeout=600, creationflags=NO_WINDOW)


def vector_text(vector) -> str:
    """A float32 vector as pgvector text. Each value is written exactly, so the column gets the same float4s."""
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


def load_tables(connection: psycopg.Connection, archive_path: Path) -> dict[str, int]:
    """COPY each CSV of the zip into its table (the columns the manifest names). Returns the rows per table."""
    loaded = {}
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        for table, info in manifest["tables"].items():
            copy_sql = sql.SQL("COPY {} ({}) FROM STDIN (FORMAT csv, HEADER)").format(
                sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, info["columns"])))
            with archive.open(f"{table}.csv") as source, connection.cursor() as cursor:
                with cursor.copy(copy_sql) as copy:
                    while data := source.read(1 << 16):
                        copy.write(data)
                count = cursor.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))).fetchone()[0]
            if count != info["rows"]:
                raise RestoreFailed(f"{table}: {count} rows restored, the backup has {info['rows']}")
            loaded[table] = count
    return loaded


def fill_embeddings(connection: psycopg.Connection, cache: EmbeddingCache) -> int:
    """raw_listings.embedding from the cache, for the listings that have none. Returns how many were filled."""
    connection.execute("CREATE TEMP TABLE cached_vectors (raw_listing_id uuid PRIMARY KEY, embedding vector)")
    with connection.cursor().copy("COPY cached_vectors (raw_listing_id, embedding) FROM STDIN") as copy:
        for listing_id, vector in cache.items():
            copy.write_row((listing_id, vector_text(vector)))
    filled = connection.execute(
        """UPDATE raw_listings rl SET embedding = c.embedding FROM cached_vectors c
           WHERE rl.raw_listing_id = c.raw_listing_id AND rl.embedding IS NULL""").rowcount
    connection.execute("DROP TABLE cached_vectors")
    return filled


def restore(dump: Path, into: str, *, docker: str, container: str = "bm-pg", cache: EmbeddingCache | None,
            runner: Runner = _run, connect: Callable[[str], psycopg.Connection] | None = None) -> dict:
    """Create `into` in the container and restore dump (and its .tables.zip, if any) into it."""
    if not dump.is_file():
        raise RestoreFailed(f"{dump} does not exist")
    tables = tables_file(dump)
    inside = f"/tmp/restore_{dump.name}"
    url = make_conninfo(DEFAULT_DATABASE_URL, dbname=into)
    connect = connect or (lambda u: psycopg.connect(u, autocommit=True))

    def step(what: str, command: Sequence[str]) -> None:
        result = runner([docker, *command])
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip().splitlines()
            raise RestoreFailed(f"{what}: {detail[-1] if detail else f'exit {result.returncode}'}")

    pg_restore = ["exec", container, "pg_restore", "-U", "postgres", "-d", into, "--no-owner", "--no-privileges",
                  "--exit-on-error"]
    report: dict = {"database": into, "with_tables_file": tables.is_file()}
    step("createdb", ["exec", container, "createdb", "-U", "postgres", into])
    step("docker cp", ["cp", str(dump), f"{container}:{inside}"])
    try:
        if not tables.is_file():   # a complete dump
            step("pg_restore", [*pg_restore, inside])
        else:
            step("pg_restore pre-data", [*pg_restore, "--section=pre-data", inside])
            step("pg_restore data", [*pg_restore, "--section=data", inside])
            with connect(url) as connection:
                report["rows"] = load_tables(connection, tables)
            step("pg_restore post-data", [*pg_restore, "--section=post-data", inside])
    finally:
        runner([docker, "exec", container, "rm", "-f", inside])
    with connect(url) as connection:
        report["embeddings_from_cache"] = fill_embeddings(connection, cache) if cache is not None else 0
        report["active_listings_without_embedding"], report["inactive_listings_without_embedding"] = \
            connection.execute("SELECT count(*) FILTER (WHERE is_active), count(*) FILTER (WHERE NOT is_active) "
                               "FROM raw_listings WHERE embedding IS NULL").fetchone()
        report["fragrances_without_embedding"] = connection.execute(
            "SELECT count(*) FROM fragrances WHERE embedding IS NULL").fetchone()[0]
    return report


def main() -> None:
    from src.daily_run import DB_CONTAINER, _find_docker

    parser = argparse.ArgumentParser(description="Restore a daily backup into a new local database")
    parser.add_argument("dump", type=Path, help="beautymatch_daily_<...>.dump (its .tables.zip is used if present)")
    parser.add_argument("--into", required=True, help="name of the NEW database in the container")
    parser.add_argument("--no-cache", action="store_true", help="leave the embeddings NULL (recompute them later)")
    parser.add_argument("--cache", type=Path, default=CACHE_PATH, help=f"embedding cache (default {CACHE_PATH})")
    args = parser.parse_args()
    docker, _ = _find_docker()
    if docker is None:
        raise SystemExit("docker CLI not found")
    cache = None if args.no_cache else EmbeddingCache(args.cache)
    try:
        report = restore(args.dump, args.into, docker=docker, container=DB_CONTAINER, cache=cache)
    except RestoreFailed as error:
        raise SystemExit(f"restore failed: {error}") from error
    print(json.dumps(report, indent=2))
    missing = report["active_listings_without_embedding"] + report["inactive_listings_without_embedding"]
    if missing or report["fragrances_without_embedding"]:
        print("\nStill missing (with DATABASE_URL pointing to the restored database, see docs/daily_run.md):",
              file=sys.stderr)
        if missing:   # the cache has the vectors the pipeline read: active listings; inactive ones are recomputed
            print("  python -m src.matching.embeddings     # listings without a vector", file=sys.stderr)
        print("  python -m src.matching.pipeline --dry-run   # must show 0 product id changes", file=sys.stderr)
        print("  python -m src.matching.pipeline           # recomputes fragrances.embedding", file=sys.stderr)


if __name__ == "__main__":
    main()
