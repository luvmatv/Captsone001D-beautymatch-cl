"""write_plan against the real database (bm-pg), inside a transaction that is rolled back.

Skipped when the database does not answer or migration 003 is not applied.
"""

import os

import psycopg
import pytest

from src.loader.raw_listings import DEFAULT_DATABASE_URL
from src.matching.pipeline import build_plan, decide, load_listings, load_overrides, write_plan


@pytest.fixture
def connection():
    try:
        connection = psycopg.connect(os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL), connect_timeout=2)
    except psycopg.OperationalError as error:
        pytest.skip(f"database not available: {error}")
    with connection:
        has_key = connection.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name = 'fragrances' AND column_name = 'identity_key'"
        ).fetchone()
        if not has_key:
            pytest.skip("migration 003_stable_product_ids.sql not applied")
        try:
            yield connection  # write_plan's transaction() becomes a savepoint inside this one
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


def test_ids_are_stable_across_runs_even_if_display_names_change(connection) -> None:
    listings, plan = run_pipeline(connection)
    write_plan(connection, listings, plan)
    first = snapshot(connection)
    assert first["products"]

    write_plan(connection, listings, plan)  # same plan again
    assert snapshot(connection) == first

    for fragrance in plan.fragrances.values():
        fragrance["name"] = f"{fragrance['name']} (renamed)"
    write_plan(connection, listings, plan)
    renamed = snapshot(connection)
    assert renamed["listings"] == first["listings"]      # every listing keeps its product ID
    assert renamed["fragrances"] == first["fragrances"]  # every fragrance keeps its ID
    assert renamed["products"].keys() == first["products"].keys()
    assert all("(renamed)" in name for name in renamed["products"].values())  # names did update


def test_inactive_listing_keeps_its_product_and_history(connection) -> None:
    listings, plan = run_pipeline(connection)
    write_plan(connection, listings, plan)
    listing_id, product_id = connection.execute(
        "SELECT raw_listing_id, product_id FROM raw_listings WHERE matching_status = 'matched' "
        "ORDER BY raw_listing_id LIMIT 1").fetchone()

    connection.execute("UPDATE raw_listings SET is_active = false WHERE raw_listing_id = %s", (listing_id,))
    write_plan(connection, *run_pipeline(connection))

    assert connection.execute(
        "SELECT product_id FROM raw_listings WHERE raw_listing_id = %s", (listing_id,)).fetchone()[0] == product_id
    assert connection.execute("SELECT 1 FROM products WHERE product_id = %s", (product_id,)).fetchone()
