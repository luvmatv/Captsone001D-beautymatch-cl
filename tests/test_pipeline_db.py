"""write_plan against a copy of the real catalog in beautymatch_test (see conftest.py),
inside a transaction that is rolled back so each test starts from the same data.
"""


import psycopg
import pytest

from src.matching.pipeline import build_plan, decide, load_listings, load_overrides, serialize_identity, write_plan
from src.matching.rules import identity_key


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


# Every (member, member of another store) pair of each matched product, among
# the listings the pipeline loads (active, embedded): an inactive listing keeps
# its product but is not part of the run.
MATCHED_PAIRS = """
SELECT a.product_id, a.raw_listing_id::text, b.raw_listing_id::text, f.identity_key
FROM raw_listings a
JOIN raw_listings b ON b.product_id = a.product_id AND b.store_id <> a.store_id
JOIN products p ON p.product_id = a.product_id
JOIN fragrances f ON f.fragrance_id = p.fragrance_id
WHERE a.matching_status = 'matched'
  AND a.is_active AND b.is_active AND a.embedding IS NOT NULL AND b.embedding IS NOT NULL
ORDER BY a.product_id, a.raw_listing_id, b.raw_listing_id
"""


def test_product_keeps_its_id_when_a_pair_member_disappears(connection) -> None:
    listings, plan = run_pipeline(connection)
    write_plan(connection, listings, plan)
    own_key = {listing.id: serialize_identity(identity_key(listing.brand, listing.name)) for listing in listings}

    # The hard case: remove the member the product's key was taken from, when
    # the member left alone has a different key (a different product key).
    cases = {}
    for product_id, removed, kept, product_key in connection.execute(MATCHED_PAIRS).fetchall():
        if own_key[removed] == product_key != own_key[kept]:
            cases.setdefault(product_id, (removed, kept))
    assert len(cases) >= 10, cases

    existing = {product_id for (product_id,) in connection.execute("SELECT product_id FROM products").fetchall()}
    connection.execute("UPDATE raw_listings SET is_active = false WHERE raw_listing_id = ANY(%s::uuid[])",
                       ([removed for removed, _ in cases.values()],))
    write_plan(connection, *run_pipeline(connection))

    now = {listing_id: (product_id, status) for listing_id, product_id, status in connection.execute(
        "SELECT raw_listing_id::text, product_id, matching_status::text FROM raw_listings "
        "WHERE raw_listing_id = ANY(%s::uuid[])", ([kept for _, kept in cases.values()],)).fetchall()}
    # The member left alone keeps its product ID, or joins a product that already
    # existed (a merge: two products became one, and only one ID can survive; the
    # old one stays reachable through the inactive listing). It never gets a new ID.
    new_ids = [product_id for product_id, (_, kept) in cases.items()
               if now[kept][0] != product_id and now[kept][0] not in existing]
    assert not new_ids, f"{len(new_ids)} of {len(cases)} kept listings got a new product ID"
    # A member left alone stays visible even with an open review pair; only a
    # listing without a volume can be pending, and it keeps its product ID.
    volume = {listing.id: listing.volume_ml for listing in listings}
    pending = [kept for _, kept in cases.values() if now[kept][1] == "pending"]
    assert all(volume[kept] is None for kept in pending), pending


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


def test_stores_outside_the_matching_are_never_touched(connection) -> None:
    # A listing of another store that copies a real Preunic listing (same name,
    # brand, volume and embedding): the perfect candidate, if it were loaded.
    connection.execute("INSERT INTO stores (name, base_url) VALUES ('otherstore', 'https://other.example')")
    connection.execute("""
        INSERT INTO raw_listings (store_id, listing_url, raw_name, raw_brand, parsed_volume_ml,
                                  parsed_concentration, embedding)
        SELECT (SELECT store_id FROM stores WHERE name = 'otherstore'), 'https://other.example/copy',
               rl.raw_name, rl.raw_brand, rl.parsed_volume_ml, rl.parsed_concentration, rl.embedding
        FROM raw_listings rl WHERE rl.matching_status = 'matched' ORDER BY rl.raw_listing_id LIMIT 1""")

    listings, plan = run_pipeline(connection)
    assert "otherstore" not in {listing.store for listing in listings}
    write_plan(connection, listings, plan)
    assert connection.execute(
        "SELECT matching_status::text, product_id FROM raw_listings WHERE listing_url = 'https://other.example/copy'"
    ).fetchone() == ("pending", None)
    # it is loaded only when asked for explicitly
    assert "otherstore" in {listing.store for listing in load_listings(connection, ("preunic", "maicao", "otherstore"))}


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
