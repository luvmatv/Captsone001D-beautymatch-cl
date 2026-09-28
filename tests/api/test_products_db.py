"""The product endpoints against a copy of the real catalog in beautymatch_test
(see conftest.py). The API reads its connection from the PG* variables, which
point at the test database for the whole module.
"""

from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from src.api.main import create_app
from src.api.repositories.products import PostgresProductRepository

PG_VARIABLES = {"PGHOST": "host", "PGPORT": "port", "PGUSER": "user", "PGPASSWORD": "password", "PGDATABASE": "dbname"}

# A product whose active resolved listings are in two different stores
# (pending listings keep a product_id but are not offers of it).
MATCHED_PRODUCT = """
SELECT cp.product_id FROM current_prices cp
JOIN raw_listings rl ON rl.raw_listing_id = cp.raw_listing_id
WHERE cp.product_id IS NOT NULL AND rl.matching_status IN ('matched', 'new_product')
GROUP BY cp.product_id HAVING count(DISTINCT cp.store_id) >= 2
ORDER BY cp.product_id LIMIT 1
"""


@pytest.fixture(scope="module")
def client(catalog_database_url):
    params = conninfo_to_dict(catalog_database_url)
    with pytest.MonkeyPatch.context() as patch:
        for variable, key in PG_VARIABLES.items():  # always override: never the development database
            if params.get(key):
                patch.setenv(variable, str(params[key]))
            else:
                patch.delenv(variable, raising=False)
        with TestClient(create_app(cors_origins=[])) as client:
            yield client


@pytest.fixture(scope="module")
def matched_product_id(client, catalog_database_url):
    with psycopg.connect(catalog_database_url) as connection:
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


@pytest.fixture
def repository(client, catalog_database_url):
    """The SQL repository on its own connection, in a transaction rolled back at the end."""
    with psycopg.connect(catalog_database_url, row_factory=dict_row) as connection:
        try:
            yield PostgresProductRepository(connection)
        finally:
            connection.rollback()


def test_pending_listings_are_not_offers_of_their_last_product(repository, matched_product_id) -> None:
    connection = repository.connection
    detail = repository.get_product(matched_product_id)
    brand = detail.brand
    pending_url = detail.prices[0].listing_url  # the cheapest offer
    connection.execute("UPDATE raw_listings SET matching_status = 'pending' WHERE listing_url = %s", (pending_url,))

    detail = repository.get_product(matched_product_id)
    assert detail is not None and detail.prices
    assert pending_url not in {price.listing_url for price in detail.prices}
    history = repository.get_price_history(matched_product_id)
    assert pending_url not in {series.listing_url for series in history.series}  # the whole series is hidden
    items, _ = repository.list_products(brand, limit=100, offset=0)
    summary = next(item for item in items if str(item.product_id) == matched_product_id)
    cheapest = min((p for p in detail.prices if p.is_available), key=lambda p: (p.price, p.store), default=None)
    assert summary.lowest_price == (cheapest and cheapest.price)

    # every listing pending: out of the list, but detail and history still answer, empty
    connection.execute("UPDATE raw_listings SET matching_status = 'pending' WHERE product_id = %s", (matched_product_id,))
    items, _ = repository.list_products(brand, limit=100, offset=0)
    assert matched_product_id not in {str(item.product_id) for item in items}
    assert repository.get_product(matched_product_id).prices == []
    assert repository.get_price_history(matched_product_id).series == []

    # resolved again: the complete series is back
    connection.execute("UPDATE raw_listings SET matching_status = 'matched' WHERE product_id = %s", (matched_product_id,))
    assert pending_url in {s.listing_url for s in repository.get_price_history(matched_product_id).series}


def test_unknown_product_is_404(client) -> None:
    assert client.get(f"/products/{uuid4()}").status_code == 404
    assert client.get(f"/products/{uuid4()}/price-history").status_code == 404
