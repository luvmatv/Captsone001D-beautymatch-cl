"""write_plan on the copied catalog: stores outside the matching, a product split in two
(see pipeline_db_support.py)."""

import numpy as np

from src.matching.pipeline import Listing, build_plan, load_listings, serialize_identity, write_plan
from src.matching.rules import identity_key
from tests.pipeline_db_support import connection, run_pipeline  # noqa: F401  (connection: fixture)

# UTF-8 lead bytes read as Latin-1 ("Ã", "Â", "â") followed by a continuation byte or a space
MOJIBAKE = "[ÂÃâ][\u0080-¿ ]"


def test_the_real_catalog_names_every_fragrance(connection) -> None:
    # write_plan refuses a plan with an unnamed fragrance; with the copied catalog
    # (2026-10-05: 51 generic names, e.g. "Perfume Shakira 50 ml") it must not refuse.
    # Mojibake in a store name ("DANCE DIAMONDS\xc2\xa0\xc2", Preunic) must not reach the
    # catalog, and repairing it must not move the listing to another product.
    broken = dict(connection.execute(
        f"SELECT raw_listing_id, product_id FROM raw_listings WHERE is_active AND raw_name ~ '{MOJIBAKE}'").fetchall())
    listings, plan = run_pipeline(connection)
    assert all(fragrance["name"].strip() for fragrance in plan.fragrances.values())
    write_plan(connection, listings, plan)
    assert connection.execute("SELECT count(*) FROM fragrances WHERE btrim(name) = ''").fetchone()[0] == 0
    assert connection.execute(
        f"""SELECT count(*) FROM products p JOIN fragrances f USING (fragrance_id)
            WHERE (p.canonical_name ~ '{MOJIBAKE}' OR f.name ~ '{MOJIBAKE}')
            AND EXISTS (SELECT 1 FROM raw_listings rl WHERE rl.product_id = p.product_id AND rl.is_active)"""
    ).fetchone()[0] == 0
    assert dict(connection.execute("SELECT raw_listing_id, product_id FROM raw_listings WHERE raw_listing_id = ANY(%s)",
                                   (list(broken),)).fetchall()) == broken


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


VECTOR = np.ones(768, dtype=np.float32) / np.sqrt(768)


def _product(connection, key, brand, name) -> str:
    fragrance_id = connection.execute(
        "INSERT INTO fragrances (identity_key, brand, name) VALUES (%s, %s, %s) RETURNING fragrance_id",
        (key, brand, name)).fetchone()[0]
    return connection.execute(
        "INSERT INTO products (fragrance_id, concentration, volume_ml, presentation, canonical_name) "
        "VALUES (%s, 'edp', 80, 'full_bottle', %s) RETURNING product_id", (fragrance_id, f"{brand} {name}")
    ).fetchone()[0]


def _listing(connection, store_id, n, brand, name, product_id, readings, active=True) -> str:
    listing_id = connection.execute(
        "INSERT INTO raw_listings (store_id, listing_url, raw_name, raw_brand, parsed_volume_ml, parsed_concentration, "
        "product_id, matching_status, is_active) VALUES (%s, %s, %s, %s, 80, 'edp', %s, 'new_product', %s) "
        "RETURNING raw_listing_id::text",
        (store_id, f"https://keys.example/{n}", name, brand, product_id, active)).fetchone()[0]
    for day in range(readings):
        connection.execute("INSERT INTO price_history (raw_listing_id, price, scraped_at) "
                           "VALUES (%s, 49990, now() - make_interval(days => %s))", (listing_id, day))
    return listing_id


def _store(connection, name) -> int:
    return connection.execute("INSERT INTO stores (name, base_url) VALUES (%s, 'https://keys.example') "
                              "RETURNING store_id", (name,)).fetchone()[0]


def _product_of(connection, listing_ids) -> dict:
    return dict(connection.execute("SELECT raw_listing_id::text, product_id FROM raw_listings "
                                   "WHERE raw_listing_id = ANY(%s::uuid[])", (listing_ids,)).fetchall())


def test_two_products_swap_keys_without_breaking_the_unique_key(connection) -> None:
    # Each product's row key is now the other's (as when a rule change moves a
    # word between two names): the products keep their listings and IDs and the
    # rows swap keys. The unique key is not deferrable: write_plan parks them first.
    brand, names = "Swapbrand Test", ("Alpha Eau de Parfum 80 ml", "Beta Eau de Parfum 80 ml")
    store_id = _store(connection, "swapstore")
    alpha_key, beta_key = (serialize_identity(identity_key(brand, name, "swapstore")) for name in names)
    alpha_product = _product(connection, beta_key, brand, "Beta")   # holds the key Beta has now
    beta_product = _product(connection, alpha_key, brand, "Alpha")
    ids = [_listing(connection, store_id, 0, brand, names[0], alpha_product, 2),
           _listing(connection, store_id, 1, brand, names[1], beta_product, 2)]
    listings = [Listing(listing_id, "swapstore", brand, name, 80, "edp", f"https://keys.example/{n}", VECTOR)
                for n, (listing_id, name) in enumerate(zip(ids, names))]

    stats = write_plan(connection, listings, build_plan(listings, []))

    assert _product_of(connection, ids) == {ids[0]: alpha_product, ids[1]: beta_product}
    keys = dict(connection.execute("SELECT p.product_id, f.identity_key FROM products p JOIN fragrances f "
                                   "USING (fragrance_id) WHERE p.product_id IN (%s, %s)",
                                   (alpha_product, beta_product)).fetchall())
    assert keys == {alpha_product: alpha_key, beta_product: beta_key}
    assert (stats["rekeyed"], stats["swaps"], stats["new"]) == (2, 0, 0)
    assert connection.execute("SELECT count(*) FROM products WHERE volume_ml >= 1000000000").fetchone()[0] == 0


def test_a_displaced_row_hands_its_inactive_listings_to_the_product_with_its_key(connection) -> None:
    # Two stores' "Gamma" are one product now (identical key). Store 1's listing
    # was product P, which has that key and an inactive listing; store 2's was Q
    # (another key, more price history). Q keeps the ID; P's inactive listing
    # follows the key to Q and P, left without listings, is deleted.
    brand, name = "Fusebrand Test", "Gamma Eau de Parfum 80 ml"
    first, second = _store(connection, "fusestore1"), _store(connection, "fusestore2")
    key = serialize_identity(identity_key(brand, name, "fusestore1"))
    p = _product(connection, key, brand, "Gamma")
    q = _product(connection, f"{key}old", brand, "Gamma Old")
    active_p = _listing(connection, first, 0, brand, name, p, 1)
    inactive_p = _listing(connection, first, 1, brand, name, p, 4, active=False)
    active_q = _listing(connection, second, 2, brand, name, q, 6)
    listings = [Listing(active_p, "fusestore1", brand, name, 80, "edp", "https://keys.example/0", VECTOR),
                Listing(active_q, "fusestore2", brand, name, 80, "edp", "https://keys.example/2", VECTOR)]

    stats = write_plan(connection, listings, build_plan(listings, []))

    assert _product_of(connection, [active_p, inactive_p, active_q]) == {active_p: q, inactive_p: q, active_q: q}
    assert connection.execute("SELECT count(*) FROM products WHERE product_id = %s", (p,)).fetchone()[0] == 0
    assert (stats["fusions"], stats["displaced"], stats["swaps"], stats["retired"]) == (1, 1, 0, 1)
    # P's ID is recorded as merged into Q, so the API can redirect a saved link (database/007)
    assert connection.execute("SELECT replaced_by, reason, canonical_name FROM retired_products WHERE product_id = %s",
                              (p,)).fetchone() == (q, "merged", "Fusebrand Test Gamma")
