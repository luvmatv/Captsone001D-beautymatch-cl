"""HTTP behavior of the product endpoints, with an in-memory repository (no database)."""

from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from src.api.config import Settings
from src.api.db import get_product_repository
from src.api.main import create_app
from src.api.schemas import PriceHistory, PricePoint, PriceSeries, ProductDetail, ProductSummary, StorePrice

SEEN = datetime(2026, 9, 25, 12, tzinfo=UTC)
FUCSIA, ICON, MIST = uuid4(), uuid4(), uuid4()

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


class FakeProductRepository:
    def __init__(self) -> None:
        self.calls = []

    def list_products(self, brand, limit, offset):
        self.calls.append(("list", brand, limit, offset))
        items = [p for p in SUMMARIES if brand is None or p.brand.lower() == brand.lower()]
        return items[offset:offset + limit], len(items)

    def get_product(self, product_id):
        return DETAIL if product_id == FUCSIA else None

    def get_price_history(self, product_id):
        return HISTORY if product_id == FUCSIA else None


class BrokenRepository(FakeProductRepository):
    def get_product(self, product_id):
        raise psycopg.OperationalError("connection refused")


@pytest.fixture
def repository():
    return FakeProductRepository()


@pytest.fixture
def client(repository):
    app = create_app(use_database=False)
    app.dependency_overrides[get_product_repository] = lambda: repository
    with TestClient(app) as client:
        yield client


def test_list_products_returns_a_page(client) -> None:
    response = client.get("/products")
    assert response.status_code == 200
    body = response.json()
    assert (body["total"], body["limit"], body["offset"]) == (3, 20, 0)
    assert body["items"][0] == {
        "product_id": str(FUCSIA), "canonical_name": "Shakira Fucsia Elixir EDP 50 ml", "brand": "Shakira",
        "concentration": "edp", "volume_ml": 50, "lowest_price": 12990, "lowest_price_store": "maicao",
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


@pytest.mark.parametrize("path", ["/products/{}", "/products/{}/price-history"])
def test_unknown_product_is_404(client, path) -> None:
    response = client.get(path.format(uuid4()))
    assert response.status_code == 404
    assert response.json() == {"detail": "Product not found"}


@pytest.mark.parametrize("path", ["/products/abc", "/products/123/price-history"])
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


def test_openapi_documents_the_404() -> None:
    schema = create_app(use_database=False).openapi()
    assert "404" in schema["paths"]["/products/{product_id}"]["get"]["responses"]
