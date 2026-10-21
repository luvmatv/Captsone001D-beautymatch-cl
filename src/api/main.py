"""BeautyMatch CL API.

Usage:
    uvicorn src.api.main:app --env-file .env

Connection settings come from PGHOST, PGPORT, PGUSER, PGPASSWORD and
PGDATABASE; browser origins allowed by CORS from API_CORS_ORIGINS (see
.env.example). Interactive docs at /docs; guide in docs/api.md.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from src.api.config import Settings, cors_origins_from_env
from src.api.db import create_pool
from src.api.routers import products
from src.api.semantic import QueryEmbedder

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


# Shown at the top of /docs (Markdown).
DESCRIPTION = """
Precios de perfumes comparados entre tiendas chilenas (hoy: **Preunic**, **Maicao**, **Salcobrand** y **Beauty Perfumes**).

**Conceptos**

- **Producto**: una versión vendible y comparable de un perfume: misma fragancia,
  concentración, volumen y presentación. Ej.: *Lattafa Asad EDP 100 ml*.
  Su `product_id` (UUID) es estable entre actualizaciones del catálogo: se puede
  guardar en URLs del frontend.
- **Publicación**: la página de un producto en una tienda (`listing_url`). Un
  producto puede tener varias, incluso dos en la misma tienda.
- **Precios**: pesos chilenos (CLP) enteros. `price` es el precio actual (con
  descuento, si lo hay); `list_price` es el precio "normal" tachado, o `null`
  si no hay descuento.

**Errores**: todos responden `{"detail": "..."}`. `404` producto inexistente,
`422` parámetro inválido (el `detail` es una lista con el problema de cada
parámetro), `503` base de datos no disponible (o, en `/search/semantic`, el modelo
de embeddings no descargado).

**Campos `null`**: los campos opcionales siempre vienen, con `null` cuando no hay
dato (por ejemplo `image_url` en Maicao, que no entrega imágenes).

**CORS**: solo `GET`, sin cookies. Los orígenes permitidos se configuran con
`API_CORS_ORIGINS` (ver `.env.example`).

**IDs retirados**: si dos productos resultan ser el mismo, uno se retira. Su ID
responde `308` con `Location` (y `replaced_by`) hacia el ID vigente, con la
misma ruta y parámetros; `fetch` lo sigue solo. Un ID retirado sin reemplazo
responde `410`.
"""

TAGS = [{"name": "products", "description": "Catálogo de productos, precios actuales e historial."},
        {"name": "brands", "description": "Marcas del catálogo, para los menús de filtros."},
        {"name": "offers", "description": "Descuentos cuyo precio de lista coincide con el historial."},
        {"name": "search", "description": "Búsqueda por significado, pensada para el chatbot."}]


ROUTERS = (products.router, products.brands_router, products.offers_router, products.search_router)


def keep_null_examples(app: FastAPI) -> None:
    """FastAPI drops None from the whole OpenAPI document, examples included, so /docs
    would hide fields like "image_url": null. Put the response examples back as written."""
    generate = app.openapi

    def openapi() -> dict:
        if app.openapi_schema is None:
            schema = generate()  # also caches it in app.openapi_schema
            for route in (route for router in ROUTERS for route in router.routes if isinstance(route, APIRoute)):
                for status, response in route.responses.items():
                    example = response.get("content", {}).get("application/json", {}).get("example")
                    if example is not None:
                        operation = schema["paths"][route.path]["get"]
                        operation["responses"][str(status)]["content"]["application/json"]["example"] = example
        return app.openapi_schema

    app.openapi = openapi


def create_app(*, use_database: bool = True, cors_origins: list[str] | None = None) -> FastAPI:
    """use_database=False skips the pool, for tests that override the repository.

    cors_origins defaults to API_CORS_ORIGINS.
    """
    app = FastAPI(
        title="BeautyMatch CL API",
        summary="Comparador de precios de perfumes entre tiendas chilenas",
        description=DESCRIPTION,
        version="0.1.0",
        openapi_tags=TAGS,
        lifespan=database_lifespan if use_database else None,
    )
    # Read-only API without cookies or auth: only GET, no credentials.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins_from_env() if cors_origins is None else cors_origins,
        allow_methods=["GET"],
        allow_credentials=False,
    )
    for router in ROUTERS:
        app.include_router(router)
    keep_null_examples(app)
    # GET /search/semantic: the embedding model, loaded on the first semantic search only
    app.state.embedder = QueryEmbedder()
    app.add_exception_handler(psycopg.OperationalError, database_unavailable)
    # retired product IDs (database/007): 308 to the product they live on as, 410 without one
    app.add_exception_handler(products.ProductMoved, products.moved_response)
    app.add_exception_handler(products.ProductGone, products.gone_response)
    return app


app = create_app()
