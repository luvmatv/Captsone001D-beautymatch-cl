"""BeautyMatch CL API.

Usage:
    uvicorn src.api.main:app --env-file .env

Connection settings come from PGHOST, PGPORT, PGUSER, PGPASSWORD and
PGDATABASE (see .env.example). Interactive docs at /docs.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.api.config import Settings
from src.api.db import create_pool
from src.api.routers import products

logger = logging.getLogger(__name__)


@asynccontextmanager
async def database_lifespan(app: FastAPI) -> AsyncIterator[None]:
    # One pool for the whole process. open() does not wait for the database:
    # the API starts even if it is down and answers 503 until it comes back.
    pool = create_pool(Settings.from_env())
    pool.open()
    app.state.pool = pool
    try:
        yield
    finally:
        pool.close()


async def database_unavailable(request: Request, error: Exception) -> JSONResponse:
    # Also covers psycopg_pool.PoolTimeout (a subclass): no free connection in time.
    logger.error("Database unavailable on %s %s: %s", request.method, request.url.path, error)
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


def create_app(*, use_database: bool = True) -> FastAPI:
    """use_database=False skips the pool, for tests that override the repository."""
    app = FastAPI(
        title="BeautyMatch CL API",
        summary="Perfume prices compared across Chilean stores",
        lifespan=database_lifespan if use_database else None,
    )
    app.include_router(products.router)
    app.add_exception_handler(psycopg.OperationalError, database_unavailable)
    return app


app = create_app()
