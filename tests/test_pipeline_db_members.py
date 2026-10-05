"""write_plan on the copied catalog when listings leave: a pair member, an inactive listing
(see pipeline_db_support.py)."""

from src.matching.pipeline import serialize_identity, write_plan
from src.matching.rules import identity_key
from tests.pipeline_db_support import connection, run_pipeline  # noqa: F401  (connection: fixture)

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
    own_key = {listing.id: serialize_identity(identity_key(listing.brand, listing.name, listing.store))
               for listing in listings}

    # The hard case: remove the member the product's key was taken from, when
    # the member left alone has a different key (a different product key).
    cases = {}
    for product_id, removed, kept, product_key in connection.execute(MATCHED_PAIRS).fetchall():
        if own_key[removed] == product_key != own_key[kept]:
            cases.setdefault(product_id, (removed, kept))
    assert len(cases) >= 10, cases

    existing = {product_id for (product_id,) in connection.execute("SELECT product_id FROM products").fetchall()}
    removed = [removed for removed, _ in cases.values()]
    # Every member that stays: in a product of three stores, more than the one in the pair.
    remaining = connection.execute(
        "SELECT raw_listing_id::text, product_id FROM raw_listings WHERE product_id = ANY(%s) AND is_active "
        "AND embedding IS NOT NULL AND raw_listing_id <> ALL(%s::uuid[])", (list(cases), removed)).fetchall()
    connection.execute("UPDATE raw_listings SET is_active = false WHERE raw_listing_id = ANY(%s::uuid[])", (removed,))
    write_plan(connection, *run_pipeline(connection))

    now = {listing_id: (product_id, status) for listing_id, product_id, status in connection.execute(
        "SELECT raw_listing_id::text, product_id, matching_status::text FROM raw_listings "
        "WHERE raw_listing_id = ANY(%s::uuid[])", ([listing_id for listing_id, _ in remaining],)).fetchall()}
    assert all(product_id is not None for product_id, _ in now.values())
    # A member that stays keeps the product ID, or joins a product that already
    # existed (a merge: only one ID can survive; the old one stays reachable
    # through the inactive listing). It gets a new ID only when the product
    # split, because the removed member was the only link between the ones that
    # stay (a three-store chain): then the old ID lives on in one of them.
    kept_by = {old for listing_id, old in remaining if now[listing_id][0] == old}
    new_ids = [(old, listing_id) for listing_id, old in remaining
               if now[listing_id][0] != old and now[listing_id][0] not in existing and old not in kept_by]
    assert not new_ids, f"{len(new_ids)} listings got a new product ID and their old one did not survive: {new_ids[:5]}"
    # A member left alone stays visible even with an open review pair; only a
    # listing without a volume can be pending, and it keeps its product ID.
    volume = {listing.id: listing.volume_ml for listing in listings}
    pending = [listing_id for listing_id, (_, status) in now.items() if status == "pending"]
    assert all(volume[listing_id] is None for listing_id in pending), pending


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
