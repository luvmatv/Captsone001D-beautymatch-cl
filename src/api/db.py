"""Connection pool and the dependency that lends one connection per request."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from src.api.config import Settings
from src.api.repositories.products import PostgresProductRepository

# Seconds a request waits for a free connection (or for an unreachable
# database) before failing with 503 instead of hanging.
CONNECTION_TIMEOUT = 5


def create_pool(settings: Settings) -> ConnectionPool:
    return ConnectionPool(
        settings.conninfo(),
        min_size=1,
        max_size=settings.pool_max_size,
        kwargs={"row_factory": dict_row},
        check=ConnectionPool.check_connection,  # drop connections broken by a database restart
        timeout=CONNECTION_TIMEOUT,
        open=False,
        name="beautymatch-api",
    )


def get_product_repository(request: Request) -> Iterator[PostgresProductRepository]:
    with request.app.state.pool.connection() as connection:
        yield PostgresProductRepository(connection)
