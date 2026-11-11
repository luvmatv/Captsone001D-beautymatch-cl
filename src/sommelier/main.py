"""API del sommelier (puerto 8001).

Uso:
    uvicorn src.sommelier.main:app --env-file .env --port 8001

Variables de entorno:
    GEMINI_API_KEY          key de Google AI Studio
    GEMINI_MODEL            modelos en orden de preferencia, separados por comas
    CATALOG_API_URL         API de BeautyMatch (por defecto http://localhost:8000)
    SOMMELIER_CORS_ORIGINS  orígenes permitidos (por defecto http://localhost:5173 y http://localhost:3000)
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.sommelier.agent import Sommelier
from src.sommelier.catalog import Catalog
from src.sommelier.llm import ChatModel, GeminiModel, Message, ModelUnavailable

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3.6-flash,gemini-3.5-flash,gemini-3.5-flash-lite,gemini-3.1-flash-lite"
MAX_MESSAGES = 30
DEFAULT_ORIGINS = "http://localhost:5173,http://localhost:3000"
MAX_MESSAGE_LENGTH = 2000


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: Annotated[str, Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)]


class ChatRequest(BaseModel):
    messages: Annotated[list[ChatMessage], Field(
        min_length=1, max_length=MAX_MESSAGES,
        description="La conversación completa, de la más antigua a la más reciente; la última es de `user`.")]


class ProductCard(BaseModel):
    """Mismos campos que un producto de GET /products, para reutilizar la tarjeta del frontend."""
    product_id: str
    canonical_name: str
    brand: str | None = None
    concentration: str | None = None
    volume_ml: int | None = None
    presentation: str | None = None
    lowest_price: int | None = None
    lowest_price_store: str | None = None
    image_url: str | None = None
    price_per_ml: float | None = None
    best_discount_percent: float | None = None


class ChatResponse(BaseModel):
    reply: str = Field(description="La respuesta del sommelier, en Markdown simple (negritas y listas).")
    products: list[ProductCard] = Field(description="Productos del catálogo que nombra la respuesta, en orden.")
    model: str


def parse_origins(value: str) -> list[str]:
    """Convierte "http://a,http://b" en una lista de orígenes válidos para CORS."""
    origins = [origin.strip().rstrip("/") for origin in value.split(",") if origin.strip()]
    invalid = [origin for origin in origins if origin != "*" and not origin.startswith(("http://", "https://"))]
    if invalid:
        raise RuntimeError(f"SOMMELIER_CORS_ORIGINS debe empezar con http:// o https://: {', '.join(invalid)}")
    return origins


def _model_from_env() -> ChatModel | None:
    """Crea el cliente de Gemini con las variables de entorno, o None si falta la key."""
    try:
        return GeminiModel(os.environ.get("GEMINI_API_KEY", "").strip(),
                           os.environ.get("GEMINI_MODEL", "").strip() or DEFAULT_MODEL)
    except ModelUnavailable as error:
        logger.warning("sommelier sin modelo: %s", error)
        return None


def create_app(model: ChatModel | None = None, catalog: Catalog | None = None,
               cors_origins: list[str] | None = None) -> FastAPI:
    """Crea la aplicación. Los tests pasan un modelo y un catálogo falsos."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.catalog = catalog or Catalog(os.environ.get("CATALOG_API_URL", "http://localhost:8000"))
        app.state.model = model if model is not None else _model_from_env()
        try:
            yield
        finally:
            if catalog is None:
                app.state.catalog.close()

    app = FastAPI(title="BeautyMatch CL – Sommelier", version="0.1.0", lifespan=lifespan,
                  summary="Agente que recomienda perfumes del catálogo de BeautyMatch")
    if cors_origins is None:
        cors_origins = parse_origins(os.environ.get("SOMMELIER_CORS_ORIGINS", DEFAULT_ORIGINS))
    app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type"], allow_credentials=False)

    @app.exception_handler(ModelUnavailable)
    async def model_unavailable(request: Request, error: ModelUnavailable) -> JSONResponse:
        logger.warning("modelo no disponible: %s", error)
        headers = {"Retry-After": str(error.retry_after)} if error.retry_after else None
        return JSONResponse(status_code=503, headers=headers, content={
            "detail": "El sommelier no está disponible en este momento. Intenta de nuevo en unos segundos."})

    @app.get("/healthz", include_in_schema=False)
    def healthz(request: Request) -> dict:
        return {"status": "ok", "model": getattr(request.app.state.model, "name", None),
                "catalog": "ok" if request.app.state.catalog.healthy() else "unreachable"}

    @app.post("/chat", response_model=ChatResponse, summary="Conversar con el sommelier")
    async def chat(body: ChatRequest, request: Request) -> ChatResponse:
        """Recibe el historial completo y devuelve la respuesta y los productos recomendados."""
        if body.messages[-1].role != "user":
            raise HTTPException(422, "El último mensaje debe ser del usuario (role = user).")
        current = request.app.state.model
        if current is None:
            raise ModelUnavailable("falta GEMINI_API_KEY")
        sommelier = Sommelier(current, request.app.state.catalog)
        conversation = [Message(m.role, m.content) for m in body.messages]
        answer = await run_in_threadpool(sommelier.answer, conversation)
        logger.info("chat: %d mensajes, herramientas=%s, productos=%d", len(conversation),
                    [call["tool"] for call in answer.tool_calls], len(answer.products))
        cards = [ProductCard(**{key: product.get(key) for key in ProductCard.model_fields})
                 for product in answer.products]
        return ChatResponse(reply=answer.reply, products=cards, model=current.name)

    return app


app = create_app()
