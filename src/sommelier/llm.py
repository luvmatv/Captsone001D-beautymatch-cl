"""Conexión con el modelo de lenguaje (Gemini).

El agente usa las interfaces ChatModel y ChatSession, así se puede cambiar de
proveedor o usar un modelo falso en los tests.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from src.sommelier.catalog import Tool

logger = logging.getLogger(__name__)

# Tiempo que se deja de usar un modelo sin cuota (429) o que rechaza la key (403/404)
QUOTA_PAUSE_SECONDS = 3600
REFUSED_PAUSE_SECONDS = 6 * 3600


@dataclass(frozen=True)
class Message:
    role: str  # "user" o "assistant"
    content: str


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any]
    id: str | None = None


@dataclass(frozen=True)
class ModelReply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)


class ModelUnavailable(RuntimeError):
    """El modelo no puede responder (sin key, sin cuota o caído). La API responde 503."""

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ChatSession(Protocol):
    def start(self) -> ModelReply: ...

    def send_tool_results(self, results: list[tuple[ToolCall, dict]]) -> ModelReply: ...


class ChatModel(Protocol):
    name: str

    def session(self, system: str, history: Sequence[Message], tools: Sequence[Tool]) -> ChatSession: ...


class GeminiModel:
    """Cliente de Gemini con una lista de modelos en orden de preferencia.

    La cuota gratuita es por modelo y por día: si uno se queda sin cuota se usa
    el siguiente de la lista.
    """

    def __init__(self, api_key: str, models: str | Sequence[str], temperature: float = 0.6,
                 clock: Callable[[], float] = time.monotonic) -> None:
        from google import genai
        from google.genai import types

        if not api_key:
            raise ModelUnavailable("falta GEMINI_API_KEY")
        names = models.split(",") if isinstance(models, str) else list(models)
        self.models = [name.strip() for name in names if name.strip()]
        if not self.models:
            raise ModelUnavailable("GEMINI_MODEL no tiene modelos")
        self._paused_until: dict[str, float] = {}
        self._clock = clock
        # Timeout de 60 s y un solo reintento para no dejar al usuario esperando
        self._client = genai.Client(api_key=api_key, http_options=types.HttpOptions(
            timeout=60_000, retry_options=types.HttpRetryOptions(attempts=2, initial_delay=1.0, max_delay=4.0)))
        self._temperature = temperature

    def available(self) -> list[str]:
        """Modelos que no están en pausa."""
        now = self._clock()
        return [name for name in self.models if self._paused_until.get(name, 0) <= now]

    def pause(self, name: str, seconds: float) -> None:
        self._paused_until[name] = self._clock() + seconds

    @property
    def name(self) -> str:
        """Modelo que se usará en la próxima consulta."""
        return (self.available() or self.models)[0]

    def session(self, system: str, history: Sequence[Message], tools: Sequence[Tool]) -> GeminiSession:
        return GeminiSession(self, system, history, tools)


class GeminiSession:
    """Una conversación con Gemini: guarda los mensajes tal como los devuelve el modelo."""

    def __init__(self, model: GeminiModel, system: str, history: Sequence[Message], tools: Sequence[Tool]) -> None:
        from google.genai import types

        self._types, self._model = types, model
        self.model_used: str | None = None
        self._config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=model._temperature,
            tools=[types.Tool(function_declarations=[
                types.FunctionDeclaration(name=t.name, description=t.description,
                                          parameters_json_schema=t.parameters)
                for t in tools])],
            # Las herramientas las ejecuta el agente, no el SDK
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        self._contents = [types.Content(role="model" if m.role == "assistant" else "user",
                                        parts=[types.Part.from_text(text=m.content)]) for m in history]

    def _call(self):
        """Llama al primer modelo disponible y pausa los que no tienen cuota o rechazan la key."""
        from google.genai import errors

        model, last = self._model, None
        for name in model.available():
            try:
                response = model._client.models.generate_content(model=name, contents=self._contents,
                                                                 config=self._config)
            except errors.APIError as error:
                last = error
                if error.code == 429:
                    logger.warning("Gemini %s sin cuota (429), se prueba el siguiente modelo", name)
                    model.pause(name, QUOTA_PAUSE_SECONDS)
                elif error.code in (403, 404):
                    logger.warning("Gemini %s rechazado (%s %s), se prueba el siguiente modelo",
                                   name, error.code, error.message)
                    model.pause(name, REFUSED_PAUSE_SECONDS)
                elif error.code in (500, 502, 503, 504):
                    logger.warning("Gemini %s no disponible (%s), se prueba el siguiente modelo", name, error.code)
                else:
                    raise ModelUnavailable(f"Gemini rechazó la consulta: {error.code} {error.message}") from error
                continue
            self.model_used = name
            return response
        if last is None:
            raise ModelUnavailable("todos los modelos de GEMINI_MODEL están sin cuota", retry_after=300)
        raise ModelUnavailable(f"ningún modelo de Gemini respondió (último: {last.code} {last.message})",
                               retry_after=30 if last.code == 429 else 10) from last

    def _generate(self) -> ModelReply:
        response = self._call()
        candidate = (response.candidates or [None])[0]
        if candidate is not None and candidate.content is not None:
            # Se guarda sin modificar: Gemini necesita recibir de vuelta sus firmas de razonamiento
            self._contents.append(candidate.content)
        calls = [ToolCall(name=call.name, args=dict(call.args or {}), id=call.id)
                 for call in (response.function_calls or [])]
        text = "" if calls else (response.text or "")
        return ModelReply(text=text.strip(), tool_calls=calls)

    def start(self) -> ModelReply:
        return self._generate()

    def send_tool_results(self, results: list[tuple[ToolCall, dict]]) -> ModelReply:
        """Envía al modelo el resultado de cada herramienta que pidió."""
        types = self._types
        parts = [types.Part(function_response=types.FunctionResponse(id=call.id, name=call.name, response=result))
                 for call, result in results]
        self._contents.append(types.Content(role="user", parts=parts))
        return self._generate()
