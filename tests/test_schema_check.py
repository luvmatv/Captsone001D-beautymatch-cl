"""The schema check against beautymatch_test (conftest.py applies every migration of database/)."""

import re
import shutil

import psycopg
import pytest

from src.schema_check import (
    MIGRATIONS_DIRECTORY,
    SchemaNotUpToDate,
    expected_migrations,
    missing_migrations,
    require_current_schema,
)


@pytest.fixture
def connection(database_url):
    with psycopg.connect(database_url) as connection:
        connection.execute("SELECT 1")  # open the transaction: everything below is rolled back
        try:
            yield connection
        finally:
            connection.rollback()


def test_a_database_with_every_migration_passes(connection) -> None:
    assert "005_schema_migrations" in expected_migrations()
    assert missing_migrations(connection) == []
    require_current_schema(connection)


def test_a_migration_file_not_applied_stops_the_caller(connection, tmp_path) -> None:
    for path in MIGRATIONS_DIRECTORY.glob("*.sql"):
        shutil.copy(path, tmp_path / path.name)
    (tmp_path / "006_future_change.sql").write_text("SELECT 1;", encoding="utf-8")
    assert missing_migrations(connection, tmp_path) == ["006_future_change"]
    with pytest.raises(SchemaNotUpToDate, match=r"database/006_future_change\.sql"):
        require_current_schema(connection, tmp_path)


def test_without_its_record_the_database_fails_closed(connection) -> None:
    # beautymatch before migration 005: no schema_migrations table
    connection.execute("DROP TABLE schema_migrations")
    with pytest.raises(SchemaNotUpToDate, match="cannot read schema_migrations"):
        require_current_schema(connection)


def test_an_empty_record_reports_every_migration(connection) -> None:
    connection.execute("DELETE FROM schema_migrations")
    assert missing_migrations(connection) == expected_migrations()


def test_every_migration_from_005_records_itself() -> None:
    for path in sorted(MIGRATIONS_DIRECTORY.glob("[0-9][0-9][0-9]_*.sql")):
        if int(path.stem[:3]) < 5:
            continue  # applied by hand before the record existed; 005 records them
        text = path.read_text(encoding="utf-8")
        assert re.search(rf"INSERT INTO schema_migrations.*'{re.escape(path.stem)}'", text, re.S), path.name
