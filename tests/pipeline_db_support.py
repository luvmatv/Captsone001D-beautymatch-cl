"""Shared by the test_pipeline_db*.py files: write_plan against a copy of the real catalog in
beautymatch_test (see conftest.py), inside a transaction that is rolled back so each test starts
from the same data.

The tests are split in three files so that each runs in a few minutes: a full pipeline pass over
the copied catalog takes ~1 minute and some tests make two or three.
"""

import psycopg
import pytest

from src.matching.pipeline import build_plan, decide, load_listings, load_overrides


@pytest.fixture
def connection(catalog_database_url):
    with psycopg.connect(catalog_database_url) as connection:
        connection.execute("SELECT 1")  # open the transaction: write_plan's transaction() becomes a savepoint
        try:
            yield connection
        finally:
            connection.rollback()


def run_pipeline(connection):
    listings = load_listings(connection)
    plan = build_plan(listings, decide(listings, load_overrides()))
    return listings, plan


def snapshot(connection):
    return {
        "listings": dict(connection.execute(
            "SELECT raw_listing_id, product_id FROM raw_listings WHERE product_id IS NOT NULL").fetchall()),
        "products": dict(connection.execute(
            "SELECT product_id, canonical_name FROM products").fetchall()),
        "fragrances": dict(connection.execute(
            "SELECT identity_key, fragrance_id FROM fragrances").fetchall()),
    }
