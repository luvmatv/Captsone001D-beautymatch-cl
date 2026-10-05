"""write_plan on the copied catalog: stable IDs across runs, pending listings (see pipeline_db_support.py)."""

from src.matching.pipeline import write_plan
from tests.pipeline_db_support import connection, run_pipeline, snapshot  # noqa: F401  (connection: fixture)


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
    # Names did update for every product of the plan: the products of the
    # listings the plan resolves. Products kept only by inactive or pending
    # (no volume) listings are not in the plan and keep their name.
    resolved = {listings[i].id for i, (state, _, _) in plan.status.items() if state != "pending"}
    planned = {product_id for listing_id, product_id in renamed["listings"].items() if str(listing_id) in resolved}
    assert planned and all("(renamed)" in renamed["products"][product_id] for product_id in planned)


def test_pending_listing_keeps_its_product_id(connection) -> None:
    listings, plan = run_pipeline(connection)
    write_plan(connection, listings, plan)
    listing_id, product_id = connection.execute(
        "SELECT raw_listing_id::text, product_id FROM raw_listings WHERE matching_status = 'matched' "
        "ORDER BY raw_listing_id LIMIT 1").fetchone()
    index = next(i for i, listing in enumerate(listings) if listing.id == listing_id)
    plan.status[index] = ("pending", None, 0.9)  # as if it now had an open review candidate
    write_plan(connection, listings, plan)
    assert connection.execute("SELECT product_id, matching_status::text FROM raw_listings WHERE raw_listing_id = %s",
                              (listing_id,)).fetchone() == (product_id, "pending")
