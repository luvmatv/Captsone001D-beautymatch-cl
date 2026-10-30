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
# With DATABASE_URL (Neon): no connection kept open while nobody asks, so Neon
# can suspend its compute (its free plan has 100 compute hours a month: an
# always-open connection would keep it awake all month).
REMOTE_MAX_IDLE_SECONDS = 240


def create_pool(settings: Settings) -> ConnectionPool:
    kwargs: dict = {"row_factory": dict_row}
    if settings.pooled:
        # PgBouncer in transaction mode does not keep a session's prepared statements
        kwargs["prepare_threshold"] = None
    remote = settings.url is not None
    return ConnectionPool(
        settings.conninfo(),
        min_size=0 if remote else 1,
        max_size=settings.pool_max_size,
        max_idle=REMOTE_MAX_IDLE_SECONDS if remote else 600,
        kwargs=kwargs,
        check=ConnectionPool.check_connection,  # drop connections broken by a database restart
        timeout=CONNECTION_TIMEOUT,
        open=False,
        name="beautymatch-api",
    )


def get_product_repository(request: Request) -> Iterator[PostgresProductRepository]:
    with request.app.state.pool.connection() as connection:
        yield PostgresProductRepository(connection)
