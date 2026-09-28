"""A separate database for the tests: beautymatch_test.

Created once per test session on the same server as DATABASE_URL (default:
the local bm-pg container), with the schema built from database/*.sql, and
dropped at the end. The tests never write to beautymatch.

Tests that need realistic data (pipeline stability, API against matched
products) get a read-only copy of beautymatch's catalog tables; they are
skipped if that copy is empty. Tests with synthetic data (loader, daily run)
only need the schema.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from src.loader.raw_listings import DEFAULT_DATABASE_URL

TEST_DATABASE = "beautymatch_test"
MIGRATIONS = sorted((Path(__file__).parent.parent / "database").glob("[0-9][0-9][0-9]_*.sql"))
# Copied in foreign-key order. scrape_runs is not copied: tests start with no runs.
COPIED_TABLES = ["stores", "fragrances", "products", "raw_listings", "price_history"]


def _copy_catalog(source_url: str, target: psycopg.Connection) -> int:
    """Copy the catalog tables from the source database; returns the products copied (0 if unavailable)."""
    try:
        source = psycopg.connect(source_url, connect_timeout=2)
    except psycopg.OperationalError:
        return 0
    with source:
        try:
            source.execute("SELECT 1 FROM fragrances WHERE identity_key IS NOT NULL LIMIT 1")
        except psycopg.Error:  # schema not migrated: nothing to copy
            return 0
        source.rollback()
        for table in COPIED_TABLES:
            columns = [row[0] for row in target.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %s ORDER BY ordinal_position",
                (table,)).fetchall()]
            column_list = sql.SQL(", ").join(map(sql.Identifier, columns))
            with source.cursor().copy(sql.SQL("COPY {} ({}) TO STDOUT").format(sql.Identifier(table), column_list)) as out, \
                    target.cursor().copy(sql.SQL("COPY {} ({}) FROM STDIN").format(sql.Identifier(table), column_list)) as into:
                for data in out:
                    into.write(data)
        for table, column in (("stores", "store_id"), ("price_history", "price_history_id")):
            target.execute(sql.SQL("SELECT setval(pg_get_serial_sequence({t}, {c}), coalesce(max({ci}), 1)) FROM {ti}").format(
                t=sql.Literal(table), c=sql.Literal(column), ci=sql.Identifier(column), ti=sql.Identifier(table)))
    return target.execute("SELECT count(*) FROM products").fetchone()[0]


@pytest.fixture(scope="session")
def database_url() -> str:
    source_url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    if conninfo_to_dict(source_url).get("dbname") == TEST_DATABASE:
        raise RuntimeError(f"DATABASE_URL must not point at {TEST_DATABASE}: it is dropped after the tests")
    admin_url = make_conninfo(source_url, dbname="postgres")
    test_url = make_conninfo(source_url, dbname=TEST_DATABASE)
    try:
        admin = psycopg.connect(admin_url, autocommit=True, connect_timeout=2)
    except psycopg.OperationalError as error:
        pytest.skip(f"database server not available: {error}")
    drop = sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(TEST_DATABASE))
    with admin:
        admin.execute(drop)  # leftover of an interrupted session
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DATABASE)))
    try:
        with psycopg.connect(test_url, autocommit=True) as connection:
            for migration in MIGRATIONS:
                connection.execute(migration.read_text(encoding="utf-8"))
            _copy_catalog(source_url, connection)
        yield test_url
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(drop)


@pytest.fixture(scope="session")
def catalog_database_url(database_url: str) -> str:
    """database_url, for tests that need the copied catalog (skipped when it is empty)."""
    with psycopg.connect(database_url) as connection:
        if not connection.execute("SELECT count(*) FROM products").fetchone()[0]:
            pytest.skip("no catalog copied into the test database (beautymatch is empty or unreachable)")
    return database_url
