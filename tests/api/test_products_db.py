"""The product endpoints against the real database (bm-pg).

Skipped when the database does not answer. Uses the PG* variables if set,
otherwise the local development database the loader also defaults to.
"""

import os
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict

from src.api.main import create_app
from src.loader.raw_listings import DEFAULT_DATABASE_URL

DEFAULTS = conninfo_to_dict(DEFAULT_DATABASE_URL)
ENV_DEFAULTS = {
    "PGHOST": DEFAULTS["host"], "PGPORT": DEFAULTS["port"], "PGUSER": DEFAULTS["user"],
    "PGPASSWORD": DEFAULTS["password"], "PGDATABASE": DEFAULTS["dbname"],
}

# A product whose active listings are in two different stores.
MATCHED_PRODUCT = """
SELECT product_id FROM current_prices WHERE product_id IS NOT NULL
GROUP BY product_id HAVING count(DISTINCT store_id) >= 2
ORDER BY product_id LIMIT 1
"""


@pytest.fixture(scope="module")
def client():
    with pytest.MonkeyPatch.context() as patch:
        for name, value in ENV_DEFAULTS.items():
            if not os.environ.get(name):
                patch.setenv(name, value)
        try:
            with psycopg.connect(connect_timeout=2) as connection:  # libpq reads the PG* variables
                connection.execute("SELECT 1 FROM products LIMIT 1")
        except psycopg.Error as error:
            pytest.skip(f"database not available: {error}")
        with TestClient(create_app()) as client:
            yield client


@pytest.fixture(scope="module")
def matched_product_id(client):
    with psycopg.connect(connect_timeout=2) as connection:
        row = connection.execute(MATCHED_PRODUCT).fetchone()
    if row is None:
        pytest.skip("no product listed in two stores")
    return str(row[0])


def all_products(client, **params):
    items, offset = [], 0
    while True:
        page = client.get("/products", params={**params, "limit": 100, "offset": offset}).json()
        items += page["items"]
        offset += 100
        if offset >= page["total"]:
            return items, page["total"]


def test_list_is_paginated_and_complete(client) -> None:
    items, total = all_products(client)
    assert len(items) == total > 0
    assert len({item["product_id"] for item in items}) == total  # stable order: no repeats across pages
    first = client.get("/products", params={"limit": 2, "offset": 1}).json()["items"]
    assert [item["product_id"] for item in first] == [item["product_id"] for item in items[1:3]]


def test_brand_filter_is_case_insensitive(client) -> None:
    brand = client.get("/products", params={"limit": 1}).json()["items"][0]["brand"]
    items, total = all_products(client, brand=brand.upper())
    assert total == len(items) > 0
    assert {item["brand"] for item in items} == {brand}


def test_detail_prices_agree_with_the_list(client, matched_product_id) -> None:
    detail = client.get(f"/products/{matched_product_id}").json()
    assert len({price["store"] for price in detail["prices"]}) >= 2
    assert [p["price"] for p in detail["prices"]] == sorted(p["price"] for p in detail["prices"])

    brand_items, _ = all_products(client, brand=detail["brand"])
    summary = next(item for item in brand_items if item["product_id"] == matched_product_id)
    available = [p for p in detail["prices"] if p["is_available"]]
    cheapest = min(available, key=lambda p: (p["price"], p["store"]), default=None)
    assert summary["lowest_price"] == (cheapest and cheapest["price"])
    assert summary["lowest_price_store"] == (cheapest and cheapest["store"])


def test_price_history_has_a_series_per_listing(client, matched_product_id) -> None:
    detail = client.get(f"/products/{matched_product_id}").json()
    history = client.get(f"/products/{matched_product_id}/price-history").json()
    assert {s["listing_url"] for s in history["series"]} >= {p["listing_url"] for p in detail["prices"]}
    for series in history["series"]:
        times = [point["scraped_at"] for point in series["points"]]
        assert times == sorted(times) and times


def test_unknown_product_is_404(client) -> None:
    assert client.get(f"/products/{uuid4()}").status_code == 404
    assert client.get(f"/products/{uuid4()}/price-history").status_code == 404
