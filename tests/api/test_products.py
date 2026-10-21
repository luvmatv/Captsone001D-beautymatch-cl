"""HTTP behavior of the product endpoints, with an in-memory repository (no database)."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from src.api.config import Settings, cors_origins_from_env
from src.api.db import get_product_repository
from src.api.main import create_app
from src.api.repositories.products import ProductFilters, Sort
from src.api.routers import products
from src.api.schemas import (
    BrandCount,
    HistoryCheck,
    ListPriceCheck,
    ListPriceChecks,
    MarketCheck,
    PriceHistory,
    PricePoint,
    PriceSeries,
    ProductDetail,
    ProductSummary,
    StorePrice,
)
from src.api.semantic import QueryEmbedder, SemanticSearchUnavailable, get_embedder
from src.matching.embeddings import ModelNotDownloaded, listing_text

SEEN =datetime(2026, 9, 25, 12, tzinfo=UTC)
FUCSIA, ICON, MIST = uuid4(), uuid4(), uuid4()
MERGED, RETIRED = uuid4(), uuid4()   # retired product IDs: one merged into FUCSIA, one without a replacement

SUMMARIES = [
    ProductSummary(product_id=FUCSIA, canonical_name="Shakira Fucsia Elixir EDP 50 ml", brand="Shakira",
                   concentration="edp", volume_ml=50, lowest_price=12990, lowest_price_store="maicao"),
    ProductSummary(product_id=ICON, canonical_name="Antonio Banderas The Icon EDT 50 ml", brand="Antonio Banderas",
                   concentration="edt", volume_ml=50, lowest_price=None, lowest_price_store=None),
    ProductSummary(product_id=MIST, canonical_name="Shakira Dance Body Mist 236 ml", brand="Shakira",
                   concentration=None, volume_ml=236, lowest_price=5990, lowest_price_store="preunic"),
]
DETAIL = ProductDetail(
    product_id=FUCSIA, canonical_name="Shakira Fucsia Elixir EDP 50 ml", brand="Shakira", concentration="edp",
    volume_ml=50, presentation="full_bottle",
    prices=[
        StorePrice(store="maicao", price=12990, list_price=15990, is_available=True,
                   listing_url="https://maicao/fucsia", scraped_at=SEEN),
        StorePrice(store="preunic", price=13990, list_price=None, is_available=True,
                   listing_url="https://preunic/fucsia", scraped_at=SEEN),
    ],
)
HISTORY = PriceHistory(
    product_id=FUCSIA, canonical_name="Shakira Fucsia Elixir EDP 50 ml",
    series=[PriceSeries(store="maicao", listing_url="https://maicao/fucsia", points=[
        PricePoint(scraped_at=SEEN, price=12990, list_price=15990, is_available=True),
    ])],
)


def list_price_checks(window_days):
    return ListPriceChecks(
        product_id=FUCSIA, canonical_name="Shakira Fucsia Elixir EDP 50 ml", window_days=window_days,
        checks=[ListPriceCheck(
            store="maicao", listing_url="https://maicao/fucsia", price=12990, list_price=15990, is_available=True,
            scraped_at=SEEN,
            vs_history=HistoryCheck(status="insufficient_data", reference_price=None, reference_scraped_at=None,
                                    observed_from=SEEN, points_in_window=1, undiscounted_points=0),
            vs_market=MarketCheck(status="within_market", reference_price=13990, reference_stores=["preunic"],
                                  percent_above=14.3),
        )],
    )


class FakeProductRepository:
    def __init__(self) -> None:
        self.calls = []

    def list_products(self, brand, limit, offset, words=(), filters=None, sort=None):
        # only what a test sets: the calls without filters or sort look as they always did
        extra = ((words,) if words else ()) + ((filters,) if filters not in (None, ProductFilters()) else ()) \
            + ((sort,) if sort is not None else ())
        self.calls.append(("list", brand, limit, offset) + extra)
        items = [p for p in SUMMARIES if (brand is None or p.brand.lower() == brand.lower())
                 and all(w.lower() in f"{p.canonical_name} {p.brand}".lower() for w in words)]
        return items[offset:offset + limit], len(items)

    def list_brands(self):
        return [BrandCount(brand="Antonio Banderas", products=1), BrandCount(brand="Shakira", products=2)]

    def get_variants(self, product_id):
        return [SUMMARIES[2]] if product_id == FUCSIA else None

    def list_offers(self, window_days, stores, brand, limit, offset):
        self.calls.append(("offers", window_days, stores, brand, limit, offset))
        return [], 0

    def get_product(self, product_id):
        return DETAIL if product_id == FUCSIA else None

    def get_retirement(self, product_id):
        return {MERGED: (True, FUCSIA), RETIRED: (True, None)}.get(product_id, (False, None))

    def get_price_history(self, product_id):
        return HISTORY if product_id == FUCSIA else None

    def get_list_price_checks(self, product_id, window_days):
        self.calls.append(("checks", window_days))
        return list_price_checks(window_days) if product_id == FUCSIA else None

    def semantic_search(self, vector, limit, filters=None):
        self.calls.append(("semantic", tuple(vector), limit) + ((filters,) if filters != ProductFilters() else ()))
        return [(SUMMARIES[0], 0.9123), (SUMMARIES[2], 0.85)][:limit]


class FakeEmbedder:
    def __init__(self, fail=False):
        self.fail, self.texts = fail, []

    def __call__(self, text):
        if self.fail:
            raise SemanticSearchUnavailable("embedding model intfloat/multilingual-e5-base is not downloaded")
        self.texts.append(text)
        return [0.5, 0.5]


class BrokenRepository(FakeProductRepository):
    def get_product(self, product_id):
        raise psycopg.OperationalError("connection refused")


@pytest.fixture
def repository():
    return FakeProductRepository()


@pytest.fixture
def embedder():
    return FakeEmbedder()


@pytest.fixture
def client(repository, embedder):
    app = create_app(use_database=False)
    app.dependency_overrides[get_product_repository] = lambda: repository
    app.dependency_overrides[get_embedder] = lambda: embedder
    with TestClient(app) as client:
        yield client


def test_list_products_returns_a_page(client) -> None:
    response = client.get("/products")
    assert response.status_code == 200
    body = response.json()
    assert (body["total"], body["limit"], body["offset"]) == (3, 20, 0)
    assert body["items"][0] == {
        "product_id": str(FUCSIA), "canonical_name": "Shakira Fucsia Elixir EDP 50 ml", "brand": "Shakira",
        "concentration": "edp", "volume_ml": 50, "presentation": None, "lowest_price": 12990,
        "lowest_price_store": "maicao", "image_url": None, "price_per_ml": None, "best_discount_percent": None,
        "last_updated": None,
    }
    assert body["items"][1]["lowest_price"] is None  # no store has it available


def test_list_products_passes_pagination_and_brand(client, repository) -> None:
    body = client.get("/products", params={"brand": "  shakira ", "limit": 1, "offset": 1}).json()
    assert repository.calls == [("list", "shakira", 1, 1)]  # brand trimmed before querying
    assert [item["product_id"] for item in body["items"]] == [str(MIST)]
    assert body["total"] == 2


def test_blank_brand_means_no_filter(client, repository) -> None:
    client.get("/products", params={"brand": " "})
    assert repository.calls == [("list", None, 20, 0)]


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"limit": "x"}])
def test_invalid_pagination_is_422(client, params) -> None:
    assert client.get("/products", params=params).status_code == 422


def test_search_passes_its_words_with_brand_and_pagination(client, repository) -> None:
    body = client.get("/products", params={"q": "  dance   SHAKIRA ", "brand": "shakira", "limit": 5, "offset": 0}).json()
    assert repository.calls == [("list", "shakira", 5, 0, ("dance", "SHAKIRA"))]
    assert [item["product_id"] for item in body["items"]] == [str(MIST)] and body["total"] == 1


@pytest.mark.parametrize("q", ["", "   "])
def test_blank_search_means_no_search(client, repository, q) -> None:
    assert client.get("/products", params={"q": q}).json()["total"] == 3
    assert repository.calls == [("list", None, 20, 0)]  # exactly the call without q


@pytest.mark.parametrize(("q", "error"), [
    ("x" * 101, "string_too_long"),
    ("asad\x00", "string_pattern_mismatch"),
    ("tab\there", "string_pattern_mismatch"),
    (" ".join(["w"] * 11), "too_many_words"),
])
def test_invalid_search_is_422_in_the_api_error_format(client, repository, q, error) -> None:
    response = client.get("/products", params={"q": q})
    assert response.status_code == 422
    (problem,) = response.json()["detail"]
    assert (problem["type"], problem["loc"]) == (error, ["query", "q"]) and problem["msg"]
    assert repository.calls == []  # nothing reached the database


def test_search_accepts_like_wildcards_and_quotes_as_text(client, repository) -> None:
    for q in ("100%", "a_b", "o'neil", "\\", "'; DROP TABLE products; --"):
        assert client.get("/products", params={"q": q}).status_code == 200
    assert [call[4] for call in repository.calls] == [
        ("100%",), ("a_b",), ("o'neil",), ("\\",), ("';", "DROP", "TABLE", "products;", "--")]


def test_search_limits_are_accepted(client) -> None:
    assert client.get("/products", params={"q": "x" * 100}).status_code == 200
    assert client.get("/products", params={"q": " ".join(["w"] * 10)}).status_code == 200


def test_filters_and_sort_reach_the_repository(client, repository) -> None:
    params = [("min_price", 10000), ("max_price", 30000), ("concentration", "edp"), ("concentration", "edt"),
              ("min_volume", 50), ("max_volume", 100), ("gender", "female"), ("store", "salcobrand"),
              ("store", "preunic"), ("store", "preunic"), ("sort", "price_asc")]
    assert client.get("/products", params=params).status_code == 200
    assert repository.calls == [("list", None, 20, 0, ProductFilters(
        min_price=10000, max_price=30000, concentrations=("edp", "edt"), min_volume=50, max_volume=100,
        genders=("female",), stores=("preunic", "salcobrand")), Sort.PRICE_ASC)]


@pytest.mark.parametrize(("params", "error"), [
    ({"min_price": 30000, "max_price": 10000}, "range"),
    ({"min_volume": 200, "max_volume": 100}, "range"),
    ({"store": "dperfumes"}, "enum"),          # scraped but not in the matching: never has a product here
    ({"store": "falabella"}, "enum"),
    ({"concentration": "eau"}, "enum"),
    ({"gender": "kids"}, "enum"),
    ({"sort": "popularity"}, "enum"),
    ({"min_price": -1}, "greater_than_equal"),
    ({"min_volume": 0}, "greater_than_equal"),
])
def test_invalid_filters_are_422(client, repository, params, error) -> None:
    response = client.get("/products", params=params)
    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == error
    assert repository.calls == []


def test_brands(client) -> None:
    assert client.get("/brands").json() == {
        "items": [{"brand": "Antonio Banderas", "products": 1}, {"brand": "Shakira", "products": 2}], "total": 2}


def test_variants(client) -> None:
    body = client.get(f"/products/{FUCSIA}/variants").json()
    assert body["product_id"] == str(FUCSIA) and body["canonical_name"] == "Shakira Fucsia Elixir EDP 50 ml"
    assert [item["product_id"] for item in body["items"]] == [str(MIST)]
    assert client.get(f"/products/{uuid4()}/variants").status_code == 404


def test_offers_pass_their_parameters(client, repository) -> None:
    body = client.get("/offers", params=[("store", "preunic"), ("store", "maicao"), ("brand", " Lattafa "),
                                         ("window_days", 60), ("limit", 5), ("offset", 10)]).json()
    assert body == {"items": [], "total": 0, "limit": 5, "offset": 10, "window_days": 60, "currency": "CLP"}
    assert repository.calls == [("offers", 60, ("maicao", "preunic"), "Lattafa", 5, 10)]


@pytest.mark.parametrize("params", [{"store": "dperfumes"}, {"window_days": 0}, {"limit": 101}])
def test_invalid_offer_parameters_are_422(client, repository, params) -> None:
    assert client.get("/offers", params=params).status_code == 422
    assert repository.calls == []


def test_product_detail(client) -> None:
    response = client.get(f"/products/{FUCSIA}")
    assert response.status_code == 200
    body = response.json()
    assert body["presentation"] == "full_bottle"
    assert body["currency"] == "CLP"
    assert [(p["store"], p["price"], p["list_price"]) for p in body["prices"]] == [
        ("maicao", 12990, 15990), ("preunic", 13990, None),
    ]
    assert body["prices"][0]["scraped_at"] == "2026-09-25T12:00:00Z"


def test_price_history(client) -> None:
    response = client.get(f"/products/{FUCSIA}/price-history")
    assert response.status_code == 200
    series = response.json()["series"]
    assert series[0]["listing_url"] == "https://maicao/fucsia"
    assert series[0]["points"][0]["price"] == 12990


def test_list_price_checks(client, repository) -> None:
    response = client.get(f"/products/{FUCSIA}/list-price-checks")
    assert response.status_code == 200
    body = response.json()
    assert repository.calls == [("checks", 30)]  # default window
    assert (body["window_days"], body["currency"]) == (30, "CLP")
    check = body["checks"][0]
    assert (check["store"], check["price"], check["list_price"]) == ("maicao", 12990, 15990)
    assert check["vs_history"] == {"status": "insufficient_data", "reference_price": None, "reference_scraped_at": None,
                                   "observed_from": "2026-09-25T12:00:00Z", "points_in_window": 1,
                                   "undiscounted_points": 0}
    assert check["vs_market"] == {"status": "within_market", "reference_price": 13990,
                                  "reference_stores": ["preunic"], "percent_above": 14.3}


def test_list_price_checks_window(client, repository) -> None:
    assert client.get(f"/products/{FUCSIA}/list-price-checks", params={"window_days": 90}).json()["window_days"] == 90
    assert repository.calls == [("checks", 90)]


@pytest.mark.parametrize("window_days", [0, 366, "x"])
def test_list_price_checks_invalid_window_is_422(client, window_days) -> None:
    assert client.get(f"/products/{FUCSIA}/list-price-checks", params={"window_days": window_days}).status_code == 422


@pytest.mark.parametrize("path", ["/products/{}", "/products/{}/price-history", "/products/{}/list-price-checks"])
def test_unknown_product_is_404(client, path) -> None:
    response = client.get(path.format(uuid4()))
    assert response.status_code == 404
    assert response.json() == {"detail": "Product not found"}


@pytest.mark.parametrize(("path", "params"), [
    ("", {}), ("/price-history", {}), ("/list-price-checks", {"window_days": 60}), ("/variants", {}),
])
def test_a_merged_product_id_redirects_to_the_one_it_lives_on_as(client, path, params) -> None:
    response = client.get(f"/products/{MERGED}{path}", params=params, follow_redirects=False)
    assert response.status_code == 308
    query = "?window_days=60" if params else ""
    assert response.headers["location"] == f"/products/{FUCSIA}{path}{query}"
    assert response.json() == {"detail": "Product merged into another", "replaced_by": str(FUCSIA)}
    assert client.get(f"/products/{MERGED}{path}", params=params).status_code == 200   # followed


def test_a_retired_product_id_without_a_replacement_is_410(client) -> None:
    response = client.get(f"/products/{RETIRED}")
    assert response.status_code == 410
    assert response.json() == {"detail": "Product retired", "replaced_by": None}


def test_semantic_search_embeds_the_trimmed_query_and_returns_products_with_similarity(
        client, repository, embedder) -> None:
    response = client.get("/search/semantic", params={"q": "  perfume dulce  ", "limit": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "perfume dulce"
    assert embedder.texts == ["perfume dulce"]
    assert [item["product_id"] for item in body["items"]] == [str(SUMMARIES[0].product_id),
                                                              str(SUMMARIES[2].product_id)]
    assert [item["similarity"] for item in body["items"]] == [0.9123, 0.85]
    assert body["items"][0]["canonical_name"] == SUMMARIES[0].canonical_name
    assert repository.calls == [("semantic", (0.5, 0.5), 2)]


def test_semantic_search_defaults_to_10_and_passes_the_product_filters(client, repository) -> None:
    response = client.get("/search/semantic", params={"q": "vainilla", "max_price": 30000, "gender": "female",
                                                      "store": ["preunic", "maicao"]})
    assert response.status_code == 200
    assert repository.calls == [("semantic", (0.5, 0.5), 10, ProductFilters(
        max_price=30000, genders=("female",), stores=("maicao", "preunic")))]


@pytest.mark.parametrize("params", [{}, {"q": ""}, {"q": "   "}, {"q": "x" * 201}, {"q": "a", "limit": 0},
                                    {"q": "a", "limit": 51}, {"q": "a", "store": "falabella"},
                                    {"q": "a", "min_price": 5, "max_price": 1}])
def test_semantic_search_rejects_invalid_parameters(client, repository, embedder, params) -> None:
    assert client.get("/search/semantic", params=params).status_code == 422
    assert repository.calls == [] and embedder.texts == []


def test_semantic_search_is_503_without_the_model(repository) -> None:
    app = create_app(use_database=False)
    app.dependency_overrides[get_product_repository] = lambda: repository
    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder(fail=True)
    with TestClient(app) as client:
        response = client.get("/search/semantic", params={"q": "vainilla"})
        assert response.status_code == 503
        assert response.json()["detail"].startswith("Semantic search unavailable: embedding model")
        assert repository.calls == []
        assert client.get("/products").status_code == 200  # the rest of the API is unaffected


class FakeModel:
    def __init__(self):
        self.encoded = []

    def encode(self, texts, normalize_embeddings):
        self.encoded.append((texts, normalize_embeddings))
        return [[0.6, 0.8]]


def test_query_embedder_loads_the_model_once_and_encodes_like_the_listings() -> None:
    model, loads = FakeModel(), []
    embedder = QueryEmbedder(loader=lambda: loads.append(1) or model)
    assert embedder("Perfume Árabe") == [0.6, 0.8]
    assert embedder("vainilla") == [0.6, 0.8]
    assert loads == [1]
    assert model.encoded == [([listing_text(None, "Perfume Árabe")], True), (["query: vainilla"], True)]


@pytest.mark.parametrize("error", [ModelNotDownloaded("not downloaded"), OSError("disk"), SystemExit("no model")])
def test_query_embedder_reports_a_missing_model_as_unavailable(error) -> None:
    def loader():
        raise error

    embedder = QueryEmbedder(loader=loader)
    with pytest.raises(SemanticSearchUnavailable):
        embedder("vainilla")


def test_the_app_does_not_load_the_model_at_startup() -> None:
    app = create_app(use_database=False)
    assert isinstance(app.state.embedder, QueryEmbedder)
    assert app.state.embedder._model is None


@pytest.mark.parametrize("path", ["/products/abc", "/products/123/price-history", "/products/abc/list-price-checks"])
def test_malformed_product_id_is_422(client, path) -> None:
    assert client.get(path).status_code == 422


def test_database_down_is_503() -> None:
    app = create_app(use_database=False)
    app.dependency_overrides[get_product_repository] = BrokenRepository
    with TestClient(app) as client:
        response = client.get(f"/products/{FUCSIA}")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}


def test_settings_from_env() -> None:
    env = {"PGHOST": "db", "PGUSER": "api", "PGPASSWORD": "secret", "PGDATABASE": "beautymatch"}
    settings = Settings.from_env(env)
    assert (settings.port, settings.pool_max_size) == (5432, 10)
    assert "secret" not in repr(settings)
    assert "host=db" in settings.conninfo() and "dbname=beautymatch" in settings.conninfo()


def test_settings_require_the_connection_variables() -> None:
    with pytest.raises(RuntimeError, match="PGPASSWORD, PGDATABASE"):
        Settings.from_env({"PGHOST": "db", "PGUSER": "api"})


def test_every_endpoint_has_a_spanish_description_and_a_valid_example() -> None:
    routes = [route for router in (products.router, products.brands_router, products.offers_router,
                                   products.search_router)
              for route in router.routes if isinstance(route, APIRoute)]
    assert len(routes) == 8
    schema = create_app(use_database=False, cors_origins=[]).openapi()
    assert {route.path for route in routes} == schema["paths"].keys()
    for route in routes:
        operation = schema["paths"][route.path]["get"]
        assert operation["summary"] and operation["description"], route.path
        responses = operation["responses"]
        # the example is a real response: it must still fit the response model, nulls included
        example = responses["200"]["content"]["application/json"]["example"]
        assert example == route.responses[200]["content"]["application/json"]["example"], route.path
        route.response_model.model_validate(example)
        if operation.get("parameters"):
            assert responses["422"]["description"].startswith("Parámetro inválido"), route.path
        assert not any(response["description"] in {"Validation Error", "Successful Response"}
                       for response in responses.values()), route.path


def test_openapi_documents_errors_and_fields() -> None:
    schema = create_app(use_database=False, cors_origins=[]).openapi()
    for path in ("/products/{product_id}", "/products/{product_id}/price-history",
                 "/products/{product_id}/list-price-checks"):
        assert {"200", "404", "422", "503"} <= schema["paths"][path]["get"]["responses"].keys()
    (q,) = [p for p in schema["paths"]["/products"]["get"]["parameters"] if p["name"] == "q"]
    assert not q["required"] and q["description"]
    assert q["schema"]["anyOf"][0]["maxLength"] == 100
    for name, model in schema["components"]["schemas"].items():
        if name in {"HTTPValidationError", "ValidationError"}:
            continue
        undocumented = [field for field, spec in model.get("properties", {}).items() if not spec.get("description")]
        assert not undocumented, (name, undocumented)


def test_list_price_texts_do_not_claim_intent() -> None:
    # The checks say what the readings show; they cannot tell a deliberate fake from anything else.
    text = json.dumps(create_app(use_database=False, cors_origins=[]).openapi(), ensure_ascii=False).lower()
    assert "list-price-checks" in text
    assert not any(word in text for word in ("fictic", "falso", "fake", "engañ"))


VITE = "http://localhost:5173"


@pytest.fixture
def cors_client(repository):
    app = create_app(use_database=False, cors_origins=[VITE])
    app.dependency_overrides[get_product_repository] = lambda: repository
    with TestClient(app) as client:
        yield client


def test_cors_allows_the_configured_origin(cors_client) -> None:
    response = cors_client.get("/products", headers={"Origin": VITE})
    assert response.headers["access-control-allow-origin"] == VITE
    preflight = cors_client.options("/products", headers={"Origin": VITE, "Access-Control-Request-Method": "GET"})
    assert preflight.status_code == 200
    assert "GET" in preflight.headers["access-control-allow-methods"]


def test_cors_ignores_other_origins(cors_client) -> None:
    response = cors_client.get("/products", headers={"Origin": "http://evil.example"})
    assert response.status_code == 200  # CORS is enforced by the browser: it just gets no allow header
    assert "access-control-allow-origin" not in response.headers
    preflight = cors_client.options("/products", headers={"Origin": "http://evil.example",
                                                          "Access-Control-Request-Method": "GET"})
    assert preflight.status_code == 400


def test_cors_allows_only_reads(cors_client) -> None:
    preflight = cors_client.options("/products", headers={"Origin": VITE, "Access-Control-Request-Method": "DELETE"})
    assert preflight.status_code == 400


@pytest.mark.parametrize(("value", "expected"), [
    (None, []),
    ("", []),
    ("http://localhost:5173", ["http://localhost:5173"]),
    (" http://localhost:5173/ , https://beautymatch.cl ", ["http://localhost:5173", "https://beautymatch.cl"]),
])
def test_cors_origins_from_env(value, expected) -> None:
    env = {} if value is None else {"API_CORS_ORIGINS": value}
    assert cors_origins_from_env(env) == expected


def test_cors_origin_without_scheme_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="localhost:5173"):
        cors_origins_from_env({"API_CORS_ORIGINS": "localhost:5173"})
