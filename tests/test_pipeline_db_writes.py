"""write_plan on the copied catalog: stores outside the matching, a product split in two
(see pipeline_db_support.py)."""

import numpy as np

from src.matching.pipeline import Listing, build_plan, load_listings, serialize_identity, write_plan
from src.matching.rules import identity_key
from tests.pipeline_db_support import connection, run_pipeline  # noqa: F401  (connection: fixture)


def test_the_real_catalog_names_every_fragrance(connection) -> None:
    # write_plan refuses a plan with an unnamed fragrance; with the copied catalog
    # (2026-10-05: 51 generic names, e.g. "Perfume Shakira 50 ml") it must not refuse.
    listings, plan = run_pipeline(connection)
    assert all(fragrance["name"].strip() for fragrance in plan.fragrances.values())
    write_plan(connection, listings, plan)
    assert connection.execute("SELECT count(*) FROM fragrances WHERE btrim(name) = ''").fetchone()[0] == 0


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


def test_a_split_product_keeps_its_id_with_the_listing_with_more_history(connection) -> None:
    # A store's "Scandal" and "So Scandal!" were one product P: the identity used
    # to drop "so", and "Scandal"'s key is still P's. "So Scandal!" has more
    # price history, so it keeps P; "Scandal" gets a new product.
    # (the names of the real dperfumes listings, under a made-up brand: the copied catalog has the real ones)
    brand, names = "Splitbrand Test", ("Scandal Eau de Parfum 80 ml", "So Scandal! Eau de Parfum 80 ml")
    store_id = connection.execute("INSERT INTO stores (name, base_url) VALUES ('splitstore', 'https://split.example') "
                                  "RETURNING store_id").fetchone()[0]
    old_key = serialize_identity(identity_key(brand, names[0], "splitstore"))
    fragrance_id = connection.execute(
        "INSERT INTO fragrances (identity_key, brand, name) VALUES (%s, %s, 'Scandal') RETURNING fragrance_id",
        (old_key, brand)).fetchone()[0]
    product_id = connection.execute(
        "INSERT INTO products (fragrance_id, concentration, volume_ml, presentation, canonical_name) "
        "VALUES (%s, 'edp', 80, 'full_bottle', 'Splitbrand Test Scandal EDP 80 ml') RETURNING product_id",
        (fragrance_id,)).fetchone()[0]
    ids = []
    for n, (name, readings) in enumerate(zip(names, (1, 3))):
        listing_id = connection.execute(
            "INSERT INTO raw_listings (store_id, listing_url, raw_name, raw_brand, parsed_volume_ml, parsed_concentration, "
            "product_id, matching_status) VALUES (%s, %s, %s, %s, 80, 'edp', %s, 'new_product') RETURNING raw_listing_id::text",
            (store_id, f"https://split.example/{n}", name, brand, product_id)).fetchone()[0]
        for day in range(readings):
            connection.execute("INSERT INTO price_history (raw_listing_id, price, scraped_at) "
                               "VALUES (%s, 49990, now() - make_interval(days => %s))", (listing_id, day))
        ids.append(listing_id)
    vector = np.ones(768, dtype=np.float32) / np.sqrt(768)
    listings = [Listing(listing_id, "splitstore", brand, name, 80, "edp", f"https://split.example/{n}", vector)
                for n, (listing_id, name) in enumerate(zip(ids, names))]

    write_plan(connection, listings, build_plan(listings, []))

    now = dict(connection.execute("SELECT raw_listing_id::text, product_id FROM raw_listings WHERE raw_listing_id = "
                                  "ANY(%s::uuid[])", (ids,)).fetchall())
    assert now[ids[1]] == product_id                    # "So Scandal!", 3 readings: keeps P
    assert now[ids[0]] not in (None, product_id)        # "Scandal", 1 reading: a new product
    assert connection.execute("SELECT f.identity_key FROM products p JOIN fragrances f USING (fragrance_id) "
                              "WHERE p.product_id = %s", (product_id,)).fetchone()[0] != old_key
