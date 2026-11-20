"""Tests del sommelier con un modelo falso y una API falsa (no llaman a Gemini ni a la base)."""

from __future__ import annotations

import time

import httpx
import pytest
from fastapi.testclient import TestClient

from src.sommelier.agent import FALLBACK_REPLY, Sommelier, mentioned_products
from src.sommelier.catalog import Catalog, clp
from src.sommelier.llm import Message, ModelReply, ModelUnavailable, ToolCall
from src.sommelier.main import BUSY_DETAIL, UNAVAILABLE_DETAIL, create_app, parse_origins

ASAD = {"product_id": "p-asad", "canonical_name": "Lattafa Asad EDP 100 ml", "brand": "Lattafa",
        "concentration": "edp", "volume_ml": 100, "presentation": "full_bottle", "lowest_price": 25999,
        "lowest_price_store": "dperfumes", "image_url": "https://img/asad.jpg", "price_per_ml": 259.99,
        "best_discount_percent": None, "last_updated": "2026-11-10T17:04:44Z", "similarity": 0.8731}
ASAD_SET = {**ASAD, "product_id": "p-asad-set", "canonical_name": "Lattafa Asad EDP 100 ml (set)",
            "presentation": "set", "lowest_price": 31990, "lowest_price_store": "maicao"}
DETAIL = {"product_id": "p-asad", "canonical_name": "Lattafa Asad EDP 100 ml", "brand": "Lattafa",
          "concentration": "edp", "volume_ml": 100, "presentation": "full_bottle", "image_url": None,
          "last_updated": None, "currency": "CLP", "prices": [
              {"store": "salcobrand", "price": 29990, "list_price": None, "is_available": False,
               "listing_url": "https://sb/asad", "scraped_at": "2026-11-10T17:00:00Z", "image_url": None,
               "price_per_ml": 299.9},
              {"store": "dperfumes", "price": 25999, "list_price": 32000, "is_available": True,
               "listing_url": "https://dp/asad", "scraped_at": "2026-11-10T17:00:00Z", "image_url": None,
               "price_per_ml": 259.99}]}
# Beauty Perfumes no se lee desde el 29 oct: su precio es más bajo, pero desactualizado
STALE_DETAIL = {**DETAIL, "product_id": "p-stale", "prices": [
    {**DETAIL["prices"][1], "is_stale": False},
    {"store": "beautyperfumes", "price": 24900, "list_price": 39990, "is_available": True,
     "listing_url": "https://bp/asad", "scraped_at": "2026-10-29T15:20:00Z", "image_url": None,
     "price_per_ml": 249.0, "is_stale": True}]}


def fake_api(requests: list[httpx.Request]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path == "/search/semantic":
            return httpx.Response(200, json={"query": request.url.params["q"], "items": [ASAD, ASAD_SET]})
        if path == "/products":
            return httpx.Response(200, json={"items": [ASAD], "total": 1, "limit": 8, "offset": 0})
        if path == "/products/p-asad":
            return httpx.Response(200, json=DETAIL)
        if path == "/products/p-stale":
            return httpx.Response(200, json=STALE_DETAIL)
        if path == "/offers":
            return httpx.Response(200, json={"items": [], "total": 0, "limit": 8, "offset": 0,
                                             "window_days": 30, "currency": "CLP"})
        if path == "/healthz":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(404, json={"detail": "Product not found"})

    return httpx.Client(base_url="http://catalog", transport=httpx.MockTransport(handler))


class ScriptedModel:
    """Modelo falso: devuelve las respuestas dadas en orden y guarda lo que recibe."""

    name = "fake-model"

    def __init__(self, *replies: ModelReply) -> None:
        self.replies, self.sent, self.system, self.history = list(replies), [], None, None

    def session(self, system, history, tools, budget=None):
        self.system, self.history, self.tools, self.budget = system, list(history), list(tools), budget
        model = self

        class Session:
            def start(self):
                return model.replies.pop(0)

            def send_tool_results(self, results):
                model.sent.append(results)
                return model.replies.pop(0)

        return Session()


@pytest.fixture
def catalog_requests() -> list[httpx.Request]:
    return []


@pytest.fixture
def catalog(catalog_requests) -> Catalog:
    return Catalog("http://catalog", client=fake_api(catalog_requests))


def test_clp_formats_chilean_pesos():
    assert clp(25999) == "$25.999"
    assert clp(1690000) == "$1.690.000"
    assert clp(None) is None


def test_semantic_tool_maps_filters_and_trims_fields(catalog, catalog_requests):
    result = catalog.search_by_description({"consulta": "vainilla árabe", "precio_max": 30000,
                                            "genero": ["male"], "limite": 99})
    params = catalog_requests[-1].url.params
    assert params["q"] == "vainilla árabe" and params["max_price"] == "30000" and params["gender"] == "male"
    assert params["limit"] == "15"  # máximo 15
    first = result["resultados"][0]
    assert first["precio_mas_bajo"] == "$25.999" and first["tienda_mas_barata"] == "dperfumes"
    assert "image_url" not in first and first["similitud"] == 0.873
    assert first["_card"]["image_url"] == "https://img/asad.jpg" and first["_card"]["lowest_price"] == 25999


def test_product_detail_lists_available_cheapest_first(catalog):
    result = catalog.product_detail({"product_id": "p-asad"})
    assert [p["tienda"] for p in result["precios"]] == ["dperfumes", "Salcobrand"]
    assert result["precios"][0]["precio_normal"] == "$32.000"


def test_catalog_errors_go_back_to_the_model(catalog):
    assert catalog.product_detail({"product_id": "nope"}) == {"error": "producto no encontrado"}
    down = Catalog("http://catalog", client=httpx.Client(transport=httpx.MockTransport(
        lambda request: (_ for _ in ()).throw(httpx.ConnectError("refused")))))
    assert "no responde" in down.search_products({"texto": "asad"})["error"]


def test_empty_offers_explain_why(catalog):
    assert "historial" in catalog.offers({})["nota"]


def test_agent_runs_tools_and_returns_mentioned_products(catalog):
    model = ScriptedModel(
        ModelReply("", [ToolCall("buscar_por_descripcion", {"consulta": "vainilla"}, id="1")]),
        ModelReply("Te recomiendo **Lattafa Asad EDP 100 ml** a $25.999 en dperfumes."),
    )
    answer = Sommelier(model, catalog).answer([Message("user", "algo con vainilla")])
    assert answer.reply.startswith("Te recomiendo")
    # el set también se encontró, pero solo se devuelve el producto que nombra la respuesta
    assert [p["product_id"] for p in answer.products] == ["p-asad"]
    assert answer.tool_calls[0]["tool"] == "buscar_por_descripcion" and answer.tool_calls[0]["error"] is None
    (call, result), = model.sent[0]
    assert call.id == "1" and result["resultados"][0]["nombre"] == "Lattafa Asad EDP 100 ml"
    assert "_card" not in result["resultados"][0]  # los datos del frontend no llegan al modelo
    assert answer.products[0]["canonical_name"] == "Lattafa Asad EDP 100 ml"
    assert "SOLO productos" in model.system


def test_unknown_tool_and_broken_tool_do_not_end_the_chat(catalog):
    catalog.search_products = lambda args: 1 / 0
    model = ScriptedModel(
        ModelReply("", [ToolCall("borrar_todo", {}), ToolCall("buscar_productos", {"texto": "x"})]),
        ModelReply("No encontré nada."),
    )
    answer = Sommelier(model, catalog).answer([Message("user", "hola")])
    errors = [result["error"] for _, result in model.sent[0]]
    assert "desconocida" in errors[0] and "falló" in errors[1]
    assert answer.reply == "No encontré nada." and answer.products == []


def test_agent_stops_after_max_rounds(catalog):
    looping = ModelReply("", [ToolCall("buscar_productos", {"texto": "x"})])
    answer = Sommelier(ScriptedModel(*[looping] * 3), catalog, max_rounds=2).answer([Message("user", "hola")])
    assert answer.reply == FALLBACK_REPLY and len(answer.tool_calls) == 2


def test_mentioned_products_prefers_the_longer_name():
    seen = {"a": {"product_id": "a", "nombre": "Lattafa Asad EDP 100 ml"},
            "b": {"product_id": "b", "nombre": "Lattafa Asad EDP 100 ml (set)"},
            "c": {"product_id": "c", "nombre": "Plaisance Hot Vainilla EDP 100 ml"}}
    reply = "1. **Plaisance  Hot Vainilla EDP 100 ml**\n2. **lattafa asad edp 100 ml (set)**"
    assert [p["product_id"] for p in mentioned_products(reply, seen)] == ["c", "b"]


def test_chat_endpoint(catalog):
    model = ScriptedModel(
        ModelReply("", [ToolCall("ver_producto", {"product_id": "p-asad"})]),
        ModelReply("**Lattafa Asad EDP 100 ml**: $25.999 en dperfumes."),
    )
    with TestClient(create_app(model=model, catalog=catalog, cors_origins=["http://localhost:5173"])) as client:
        response = client.post("/chat", json={"messages": [
            {"role": "user", "content": "hola"}, {"role": "assistant", "content": "¿Qué buscas?"},
            {"role": "user", "content": "el asad"}]}, headers={"Origin": "http://localhost:5173"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["products"] == [{
            "product_id": "p-asad", "canonical_name": "Lattafa Asad EDP 100 ml", "brand": "Lattafa",
            "concentration": "edp", "volume_ml": 100, "presentation": "full_bottle", "lowest_price": 25999,
            "lowest_price_store": "dperfumes", "image_url": None, "price_per_ml": 259.99,
            "best_discount_percent": None}]
        assert body["model"] == "fake-model"
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
        assert [m.role for m in model.history] == ["user", "assistant", "user"]
        assert client.get("/healthz").json() == {"status": "ok", "model": "fake-model", "catalog": "ok"}


def test_chat_validation_and_unavailable_model(catalog):
    with TestClient(create_app(model=ScriptedModel(), catalog=catalog, cors_origins=[])) as client:
        assert client.post("/chat", json={"messages": []}).status_code == 422
        last_from_assistant = {"messages": [{"role": "assistant", "content": "hola"}]}
        assert client.post("/chat", json=last_from_assistant).status_code == 422

    class Busy(ScriptedModel):
        def session(self, *args, **kwargs):
            raise ModelUnavailable("quota", retry_after=30)

    with TestClient(create_app(model=Busy(), catalog=catalog, cors_origins=[])) as client:
        response = client.post("/chat", json={"messages": [{"role": "user", "content": "hola"}]})
        assert response.status_code == 503 and response.headers["retry-after"] == "30"
        assert response.json()["detail"] == UNAVAILABLE_DETAIL


def test_parse_origins():
    assert parse_origins("http://localhost:5173/, https://x.cl") == ["http://localhost:5173", "https://x.cl"]
    with pytest.raises(RuntimeError):
        parse_origins("localhost:5173")


class FakeModels:
    """Reemplaza genai.Client().models. Cada modelo responde un texto o un código de error."""

    def __init__(self, script: dict) -> None:
        self.script, self.calls, self.configs = script, [], []

    def generate_content(self, *, model, contents, config):
        from google.genai import errors, types

        self.calls.append(model)
        self.configs.append(config)
        outcome = self.script[model]
        if outcome == "timeout":
            raise httpx.ReadTimeout("slow")
        if isinstance(outcome, int):
            raise errors.APIError(outcome, {"error": {"code": outcome, "message": "nope", "status": "X"}})
        return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(
            role="model", parts=[types.Part.from_text(text=outcome)]))])


def gemini(script: dict, clock):
    from src.sommelier.llm import GeminiModel

    model = GeminiModel("key", ",".join(script), clock=clock)
    fake = FakeModels(script)
    model._client = type("Client", (), {"models": fake})()
    return model, fake


def test_gemini_falls_back_when_a_model_is_out_of_quota():
    now = [0.0]
    model, fake = gemini({"m1": 429, "m2": 404, "m3": "hola"}, clock=lambda: now[0])
    session = model.session("sys", [Message("user", "hola")], [])
    assert session.start().text == "hola" and session.model_used == "m3"
    assert fake.calls == ["m1", "m2", "m3"] and model.name == "m3"
    fake.calls.clear()
    model.session("sys", [Message("user", "hola")], []).start()
    assert fake.calls == ["m3"]  # los modelos en pausa se saltan
    now[0] += 3601
    assert model.available() == ["m1", "m3"]  # 429 queda en pausa una hora, 404 más tiempo


def test_gemini_all_models_out_of_quota_is_unavailable():
    model, _ = gemini({"m1": 429, "m2": 429}, clock=lambda: 0.0)
    with pytest.raises(ModelUnavailable) as error:
        model.session("sys", [Message("user", "hola")], []).start()
    assert error.value.retry_after == 30 and not error.value.busy
    model, _ = gemini({"m1": 429, "m2": 503}, clock=lambda: 0.0)
    with pytest.raises(ModelUnavailable) as error:  # 503: el modelo está saturado
        model.session("sys", [Message("user", "hola")], []).start()
    assert error.value.retry_after == 30 and error.value.busy
    with pytest.raises(ModelUnavailable):  # 400: no se prueba otro modelo
        gemini({"m1": 400, "m2": "hola"}, clock=lambda: 0.0)[0].session("s", [Message("user", "x")], []).start()


def test_product_detail_never_takes_a_stale_price_as_the_cheapest(catalog):
    result = catalog.product_detail({"product_id": "p-stale"})
    assert result["precio_mas_bajo"] == "$25.999" and result["tienda_mas_barata"] == "dperfumes"
    assert result["_card"]["lowest_price"] == 25999 and result["_card"]["lowest_price_store"] == "dperfumes"
    fresh, stale = result["precios"]
    assert fresh["tienda"] == "dperfumes" and "nota" not in fresh
    assert stale["tienda"] == "Beauty Perfumes" and stale["precio"] == "$24.900"
    assert stale["nota"] == ("precio del 29 oct 2026, sin lectura reciente: no es de hoy "
                             "y no cuenta como el más barato")


def test_product_detail_with_only_stale_prices_has_no_cheapest(catalog):
    only_stale = {**STALE_DETAIL, "prices": [STALE_DETAIL["prices"][1]]}
    catalog._client = httpx.Client(base_url="http://catalog", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=only_stale)))
    result = catalog.product_detail({"product_id": "p-stale"})
    assert result["precio_mas_bajo"] is None and result["_card"]["lowest_price"] is None
    assert "sin lectura reciente" in result["precios"][0]["nota"]


def test_prompt_forbids_stale_prices_as_the_cheapest():
    from src.sommelier.agent import SYSTEM_PROMPT
    assert "sin lectura" in SYSTEM_PROMPT and "nunca lo presentes como el más barato" in SYSTEM_PROMPT


def test_gemini_moves_on_when_a_model_times_out():
    model, fake = gemini({"m1": "timeout", "m2": "hola"}, clock=lambda: 0.0)
    session = model.session("sys", [Message("user", "hola")], [])
    assert session.start().text == "hola" and fake.calls == ["m1", "m2"]
    options = fake.configs[0].http_options
    assert options.timeout == 20_000 and options.retry_options.attempts == 1  # sin reintento
    assert model.available() == ["m1", "m2"]  # tardar no deja al modelo en pausa
    model, _ = gemini({"m1": "timeout", "m2": "timeout"}, clock=lambda: 0.0)
    with pytest.raises(ModelUnavailable) as error:
        model.session("sys", [Message("user", "hola")], []).start()
    assert error.value.busy and error.value.retry_after == 30


def test_gemini_call_timeout_shrinks_to_the_budget_left():
    now = [0.0]
    model, fake = gemini({"m1": "hola"}, clock=lambda: now[0])
    session = model.session("sys", [Message("user", "hola")], [], budget=40)
    now[0] = 25.0  # quedan 15 s
    session.start()
    assert fake.configs[0].http_options.timeout == 15_000
    now[0] = 31.0  # quedan 9 s: Gemini no acepta esperas de menos de 10 s
    with pytest.raises(ModelUnavailable) as error:
        session.start()
    assert error.value.busy and len(fake.calls) == 1


def test_agent_passes_its_budget_and_stops_tools_when_time_is_up(catalog):
    model = ScriptedModel(ModelReply("", [ToolCall("buscar_productos", {"texto": "x"})]))
    with pytest.raises(ModelUnavailable) as error:
        Sommelier(model, catalog, budget=-1).answer([Message("user", "hola")])
    assert error.value.busy and model.budget == -1 and model.sent == []


def test_chat_answers_busy_when_the_model_is_too_slow(catalog):
    class Slow(ScriptedModel):
        def session(self, *args, **kwargs):
            class Session:
                def start(self):
                    time.sleep(2)
                    return ModelReply("tarde")
            return Session()

    with TestClient(create_app(model=Slow(), catalog=catalog, cors_origins=[], answer_timeout=0.2)) as client:
        started = time.monotonic()
        response = client.post("/chat", json={"messages": [{"role": "user", "content": "hola"}]})
        assert time.monotonic() - started < 1.5
    assert response.status_code == 503 and response.json() == {"detail": BUSY_DETAIL}
    assert response.headers["retry-after"] == "30"


def test_chat_answers_busy_when_no_model_responds_in_time(catalog):
    class Busy(ScriptedModel):
        def session(self, *args, **kwargs):
            raise ModelUnavailable("ningún modelo respondió a tiempo", retry_after=30, busy=True)

    with TestClient(create_app(model=Busy(), catalog=catalog, cors_origins=[])) as client:
        response = client.post("/chat", json={"messages": [{"role": "user", "content": "hola"}]})
    assert response.status_code == 503 and response.json()["detail"] == BUSY_DETAIL


def test_timeouts_of_httpx_and_its_fork_httpx2_are_both_caught():
    from src.sommelier.llm import timeout_errors
    assert httpx.TimeoutException in timeout_errors()
    try:
        import httpx2
    except ImportError:
        return
    assert httpx2.TimeoutException in timeout_errors()  # google-genai 3.0.0 (la imagen) usa httpx2
