"""Is the database's schema the one this working tree's code expects?

Every migration in database/NNN_*.sql must be recorded in the table
schema_migrations (database/005). The daily run, the loader and the
pipeline call require_current_schema before writing, so code that needs a
new migration never runs against a database that does not have it.

Fails closed: a missing table, an unreadable one, or any migration file not
recorded stops the caller with SchemaNotUpToDate and a message saying what
to apply.
"""

from __future__ import annotations

from pathlib import Path

import psycopg

MIGRATIONS_DIRECTORY = Path(__file__).resolve().parent.parent / "database"


class SchemaNotUpToDate(RuntimeError):
    """The database lacks migrations this code expects (or its record of them cannot be read)."""


def expected_migrations(directory: Path = MIGRATIONS_DIRECTORY) -> list[str]:
    """The migrations of the working tree, in order: file names without ".sql"."""
    return sorted(path.stem for path in directory.glob("[0-9][0-9][0-9]_*.sql"))


def missing_migrations(connection: psycopg.Connection, directory: Path = MIGRATIONS_DIRECTORY) -> list[str]:
    """The working tree's migrations not recorded in schema_migrations; raises if the record cannot be read."""
    try:
        applied = {name for (name,) in connection.execute("SELECT name FROM schema_migrations").fetchall()}
    except psycopg.Error as error:
        if not connection.autocommit:
            connection.rollback()
        first_line = str(error).strip().splitlines()[0] if str(error).strip() else type(error).__name__
        raise SchemaNotUpToDate(
            f"cannot read schema_migrations ({first_line}): the database predates database/005_schema_migrations.sql "
            "or is not this project's. Back it up and apply the missing migrations (see README) before running."
        ) from error
    return [name for name in expected_migrations(directory) if name not in applied]


def require_current_schema(connection: psycopg.Connection, directory: Path = MIGRATIONS_DIRECTORY) -> None:
    missing = missing_migrations(connection, directory)
    if missing:
        raise SchemaNotUpToDate(
            f"the database is missing migrations: {', '.join(f'database/{name}.sql' for name in missing)}. "
            "Back it up and apply them, in order (see README), before running.")
