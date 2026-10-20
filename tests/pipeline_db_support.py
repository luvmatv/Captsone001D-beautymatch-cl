"""Shared by the test_pipeline_db*.py files: write_plan against a copy of the real catalog in
beautymatch_test (see conftest.py), inside a transaction that is rolled back so each test starts
from the same data.

The tests are split in three files so that each runs in a few minutes: a full pipeline pass over
the copied catalog takes ~1 minute and some tests make two or three.
"""

from collections import defaultdict

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


def id_changes(before: dict, after: dict) -> dict:
    """The product_id audit of 2026-10-15 between two snapshots' listing -> product maps.

    swaps: an ID still in use that holds none of its earlier listings;
    fusions: an ID that now holds the listings of 2+ earlier IDs;
    splits: an earlier ID whose listings are now in 2+ IDs.
    """
    members_before, members_after = defaultdict(set), defaultdict(set)
    for listing, product in before.items():
        members_before[product].add(listing)
    for listing, product in after.items():
        members_after[product].add(listing)
    return {
        "swaps": sum(1 for product, listings in members_before.items()
                     if members_after.get(product) and not listings & members_after[product]),
        "fusions": sum(1 for listings in members_after.values()
                       if len({before[listing] for listing in listings if listing in before}) > 1),
        "splits": sum(1 for listings in members_before.values()
                      if len({after[listing] for listing in listings if listing in after}) > 1),
    }


def snapshot(connection):
    return {
        "listings": dict(connection.execute(
            "SELECT raw_listing_id, product_id FROM raw_listings WHERE product_id IS NOT NULL").fetchall()),
        "products": dict(connection.execute(
            "SELECT product_id, canonical_name FROM products").fetchall()),
        "fragrances": dict(connection.execute(
            "SELECT identity_key, fragrance_id FROM fragrances").fetchall()),
    }
