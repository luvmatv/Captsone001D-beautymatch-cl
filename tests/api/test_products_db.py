"""The product endpoints against a copy of the real catalog in beautymatch_test
(see conftest.py). The API reads its connection from the PG* variables, which
point at the test database for the whole module.
"""

import unicodedata
from collections import Counter
from datetime import timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from src.api.main import create_app
from src.api.repositories import products as products_repository
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


def test_filters_keep_only_matching_products(client, catalog_database_url) -> None:
    everything, total = all_products(client)
    priced = [i for i in everything if i["lowest_price"] is not None]
    low, high = sorted(i["lowest_price"] for i in priced)[len(priced) // 4], sorted(
        i["lowest_price"] for i in priced)[3 * len(priced) // 4]
    items, n = all_products(client, min_price=low, max_price=high)
    assert n == len(items) == sum(1 for i in priced if low <= i["lowest_price"] <= high) > 0
    items, n = all_products(client, concentration=["edp", "edt"])
    assert n == sum(1 for i in everything if i["concentration"] in ("edp", "edt")) and n > 0
    items, n = all_products(client, min_volume=50, max_volume=100)
    assert n == sum(1 for i in everything if 50 <= i["volume_ml"] <= 100) and n > 0
    by_gender = [all_products(client, gender=g)[1] for g in ("male", "female", "unisex")]
    assert sum(by_gender) == total and all(by_gender)            # every product has exactly one gender
    assert all_products(client, gender=["male", "female"])[1] == by_gender[0] + by_gender[1]
    with psycopg.connect(catalog_database_url) as connection:
        in_store = {row[0] for row in connection.execute(
            """SELECT DISTINCT cp.product_id::text FROM current_prices cp JOIN raw_listings rl USING (raw_listing_id)
               JOIN stores s ON s.store_id = cp.store_id
               WHERE s.name = 'salcobrand' AND cp.is_available AND rl.matching_status IN ('matched', 'new_product')""")}
    items, n = all_products(client, store="salcobrand")
    assert {i["product_id"] for i in items} == in_store & {i["product_id"] for i in everything}
    # combined with q and brand, paginated without repeats
    items, n = all_products(client, q="edp", brand=everything[0]["brand"], max_price=high)
    assert len({i["product_id"] for i in items}) == n


@pytest.mark.parametrize(("sort", "key", "descending"), [
    ("price_asc", "lowest_price", False), ("price_desc", "lowest_price", True),
    ("discount", "best_discount_percent", True), ("price_per_ml", "price_per_ml", False),
])
def test_sorts_order_by_their_value_with_missing_values_last(client, sort, key, descending) -> None:
    items, total = all_products(client, sort=sort)
    assert len({i["product_id"] for i in items}) == total        # stable pages
    values = [i[key] for i in items]
    known = [v for v in values if v is not None]
    assert values[:len(known)] == known                          # nulls at the end
    assert known == sorted(known, reverse=descending) and known


def test_name_sort_is_the_default(client) -> None:
    assert all_products(client, sort="name")[0] == all_products(client)[0]


def test_price_per_ml_and_last_updated(client, matched_product_id) -> None:
    detail = client.get(f"/products/{matched_product_id}").json()
    assert detail["last_updated"] == max(p["scraped_at"] for p in detail["prices"])
    for price in detail["prices"]:
        expected = None if detail["presentation"] == "travel_set" else round(price["price"] / detail["volume_ml"], 1)
        assert price["price_per_ml"] == expected
    items, _ = all_products(client, brand=detail["brand"])
    summary = next(i for i in items if i["product_id"] == matched_product_id)
    assert summary["last_updated"] == detail["last_updated"]
    if summary["lowest_price"] is not None and detail["presentation"] != "travel_set":
        assert summary["price_per_ml"] == round(summary["lowest_price"] / summary["volume_ml"], 1)
    sets = all_products(client, q="set")[0]
    assert all(i["price_per_ml"] is None for i in sets if i["presentation"] == "travel_set")


def test_brands_count_the_products_on_sale(client) -> None:
    body = client.get("/brands").json()
    everything, total = all_products(client)
    assert body["total"] == len(body["items"]) == len({i["brand"] for i in everything})
    assert sum(b["products"] for b in body["items"]) == total
    names = [b["brand"] for b in body["items"]]
    assert len(set(names)) == len(names)
    # alphabetical as the database collates (it ignores spaces: "Alejandro Sanz" before "Al Haramain")
    initials = [plain(n)[0] for n in names]
    assert initials == sorted(initials)
    biggest = max(body["items"], key=lambda b: b["products"])
    assert all_products(client, brand=biggest["brand"])[1] == biggest["products"]


def test_variants_are_the_other_products_of_the_same_fragrance(client, catalog_database_url) -> None:
    with psycopg.connect(catalog_database_url) as connection:
        product_id, fragrance_id = connection.execute(
            """SELECT p.product_id::text, p.fragrance_id FROM products p
               WHERE (SELECT count(*) FROM products o WHERE o.fragrance_id = p.fragrance_id AND EXISTS (
                      SELECT 1 FROM raw_listings rl WHERE rl.product_id = o.product_id AND rl.is_active
                      AND rl.matching_status IN ('matched', 'new_product'))) >= 3
               ORDER BY p.product_id LIMIT 1""").fetchone()
        siblings = {row[0] for row in connection.execute(
            """SELECT o.product_id::text FROM products o WHERE o.fragrance_id = %s AND o.product_id <> %s
               AND EXISTS (SELECT 1 FROM raw_listings rl WHERE rl.product_id = o.product_id AND rl.is_active
                           AND rl.matching_status IN ('matched', 'new_product'))""", (fragrance_id, product_id))}
    body = client.get(f"/products/{product_id}/variants").json()
    assert {i["product_id"] for i in body["items"]} == siblings and product_id not in siblings
    assert len({i["brand"] for i in body["items"]}) == 1
    keys = [(i["presentation"], i["volume_ml"]) for i in body["items"]]
    assert keys == sorted(keys)


def test_brand_filter_is_case_insensitive(client) -> None:
    brand = client.get("/products", params={"limit": 1}).json()["items"][0]["brand"]
    items, total = all_products(client, brand=brand.upper())
    assert total == len(items) > 0
    assert {item["brand"] for item in items} == {brand}


# GET /products as it was before q (main c36dd1d): without q the list must be exactly this.
LIST_BEFORE_SEARCH = """
SELECT p.product_id::text FROM products p JOIN fragrances f ON f.fragrance_id = p.fragrance_id
WHERE EXISTS (SELECT 1 FROM raw_listings rl WHERE rl.product_id = p.product_id AND rl.is_active
              AND rl.matching_status IN ('matched', 'new_product'))
ORDER BY p.canonical_name, p.product_id
"""


def plain(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(ch)
                   ).replace("'", "").replace("´", "")


def test_without_search_the_list_is_the_same_as_before(client, catalog_database_url) -> None:
    with psycopg.connect(catalog_database_url) as connection:
        before = [row[0] for row in connection.execute(LIST_BEFORE_SEARCH)]
    for params in ({}, {"q": ""}, {"q": "   "}):
        items, total = all_products(client, **params)
        assert [item["product_id"] for item in items] == before and total == len(before)


def test_search_ignores_case_and_accents(client) -> None:
    items, _ = all_products(client)
    accented = next(item for item in items if any(ch in item["canonical_name"] for ch in "áéíóúñ"))
    word = next(w for w in accented["canonical_name"].split() if any(ch in w for ch in "áéíóúñ"))
    for q in (plain(word).upper(), word.lower(), word):
        found, total = all_products(client, q=q)
        assert accented["product_id"] in {item["product_id"] for item in found}, q
        assert all(plain(word) in plain(f"{i['canonical_name']} {i['brand']}") for i in found)
    # and an accent in the search finds the name written without it
    unaccented = next((item for item in items if "Jazmin" in item["canonical_name"].split()), None)
    if unaccented:  # the copied catalog has "Jean Les Pins Agua Jazmin EDT 100 ml"
        assert unaccented["product_id"] in {i["product_id"] for i in all_products(client, q="JAZMÍN")[0]}


def test_two_words_must_both_appear_in_any_order(client) -> None:
    items, _ = all_products(client)
    product = next(item for item in items if len([w for w in item["canonical_name"].split() if len(w) > 3]) >= 2)
    first, second = [w for w in product["canonical_name"].split() if len(w) > 3][:2]
    both, total = all_products(client, q=f"{second} {first}")
    assert product["product_id"] in {item["product_id"] for item in both}
    for item in both:
        text = plain(f"{item['canonical_name']} {item['brand']}")
        assert plain(first) in text and plain(second) in text
    assert total <= all_products(client, q=first)[1]


def test_search_without_results(client) -> None:
    assert client.get("/products", params={"q": "zzqqxx"}).json() == {"items": [], "total": 0, "limit": 20, "offset": 0}


def test_like_wildcards_are_searched_as_text(client, catalog_database_url) -> None:
    for q in ("%", "_", "\\", "100%"):
        found, total = all_products(client, q=q)
        assert all(q in f"{item['canonical_name']} {item['brand']}" for item in found), q
    assert all_products(client, q="_")[1] < all_products(client)[1]
    # an injection attempt is just text: no results, and the tables are still there
    assert client.get("/products", params={"q": "x'); DROP TABLE products; --"}).json()["total"] == 0
    with psycopg.connect(catalog_database_url) as connection:
        assert connection.execute("SELECT count(*) FROM products").fetchone()[0] > 0


def test_search_combines_with_brand_and_paginates_stably(client) -> None:
    items, _ = all_products(client)
    brand = Counter(item["brand"] for item in items).most_common(1)[0][0]
    word = Counter(w for item in items if item["brand"] == brand for w in item["canonical_name"].split()
                   if len(w) > 3 and plain(w) not in plain(brand)).most_common(1)[0][0]
    everything, total = all_products(client, q=word, brand=brand)
    assert total == len(everything) > 2 and {item["brand"] for item in everything} == {brand}
    pages = []
    for offset in range(0, total, 2):
        page = client.get("/products", params={"q": word, "brand": brand, "limit": 2, "offset": offset}).json()
        assert page["total"] == total
        pages += page["items"]
    assert pages == everything  # same order page by page and in one go: no repeats, none missing
    assert client.get("/products", params={"q": word, "brand": brand}).json() == \
        client.get("/products", params={"q": word, "brand": brand}).json()


def test_search_puts_the_exact_name_and_then_prefixes_first(client) -> None:
    items, _ = all_products(client)
    product = next(item for item in items if item["brand"] and item["canonical_name"].startswith(item["brand"] + " ")
                   and len(item["canonical_name"].split()) >= 4)
    exact = client.get("/products", params={"q": product["canonical_name"].upper()}).json()["items"]
    assert exact[0]["product_id"] == product["product_id"]
    # the name without its brand: the products whose name starts with it come before the others
    rest = product["canonical_name"][len(product["brand"]) + 1:].split()[0]
    found, _ = all_products(client, q=rest)

    def starts(item):
        name = plain(item["canonical_name"])
        brand = plain(item["brand"])
        return name.startswith(plain(rest)) or (name.startswith(brand + " ") and
                                                name[len(brand) + 1:].startswith(plain(rest)))
    flags = [starts(item) for item in found if plain(item["canonical_name"]) != plain(rest)]
    assert flags == sorted(flags, reverse=True)


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


def test_list_price_checks_follow_the_detail_offers(client, matched_product_id) -> None:
    detail = client.get(f"/products/{matched_product_id}").json()
    checks = client.get(f"/products/{matched_product_id}/list-price-checks").json()
    assert checks["window_days"] == 30
    offer = ["store", "listing_url", "price", "list_price", "is_available", "scraped_at"]
    assert [[c[k] for k in offer] for c in checks["checks"]] == [[p[k] for k in offer] for p in detail["prices"]]
    for check in checks["checks"]:
        discounted = check["list_price"] is not None and check["list_price"] > check["price"]
        assert (check["vs_history"]["status"] == "no_list_price") == (not discounted)
        assert (check["vs_market"]["status"] == "no_list_price") == (not discounted)


def test_list_price_against_the_listing_history(repository, matched_product_id) -> None:
    connection = repository.connection
    listing_id, current_at, price = connection.execute(
        """SELECT cp.raw_listing_id, cp.scraped_at, cp.price::int FROM current_prices cp
           JOIN raw_listings rl ON rl.raw_listing_id = cp.raw_listing_id
           WHERE cp.product_id = %s AND rl.matching_status IN ('matched', 'new_product')
           ORDER BY cp.price, rl.listing_url LIMIT 1""", (matched_product_id,)).fetchone().values()
    # A day later the same price, undiscounted and in stock; a day after that, a discount.
    insert = ("INSERT INTO price_history (raw_listing_id, price, list_price, is_available, scraped_at) "
              "VALUES (%s, %s, %s, true, %s)")
    connection.execute(insert, (listing_id, price, None, current_at + timedelta(days=1)))
    reference = connection.execute(
        """SELECT max(price)::int FROM price_history WHERE raw_listing_id = %s AND is_available
           AND (list_price IS NULL OR list_price <= price) AND scraped_at >= %s""",
        (listing_id, current_at + timedelta(days=2) - timedelta(days=30))).fetchone()["max"]
    latest = connection.execute(insert + " RETURNING price_history_id",
                                (listing_id, price // 2, reference + 1, current_at + timedelta(days=2))).fetchone()

    def check():
        result = repository.get_list_price_checks(matched_product_id, 30)
        return next(c for c in result.checks if c.scraped_at == current_at + timedelta(days=2)).vs_history

    above = check()
    assert (above.status, above.reference_price) == ("above_history", reference)
    assert above.undiscounted_points >= 1
    connection.execute("UPDATE price_history SET list_price = %s WHERE price_history_id = %s",
                       (reference, latest["price_history_id"]))
    assert check().status == "consistent"


def test_the_product_image_is_its_cheapest_available_offer_with_one(repository, matched_product_id) -> None:
    connection = repository.connection
    detail = repository.get_product(matched_product_id)
    offers = [p for p in detail.prices if p.is_available]
    cheapest, other = offers[0], offers[-1]
    connection.execute("UPDATE raw_listings SET image_url = NULL WHERE product_id = %s", (matched_product_id,))
    assert repository.get_product(matched_product_id).image_url is None
    connection.execute("UPDATE raw_listings SET image_url = 'https://img.example/other.jpg' WHERE listing_url = %s",
                       (other.listing_url,))
    assert repository.get_product(matched_product_id).image_url == "https://img.example/other.jpg"
    connection.execute("UPDATE raw_listings SET image_url = 'https://img.example/cheapest.jpg' WHERE listing_url = %s",
                       (cheapest.listing_url,))
    detail = repository.get_product(matched_product_id)
    assert detail.image_url == "https://img.example/cheapest.jpg"
    assert {p.listing_url: p.image_url for p in detail.prices}[other.listing_url] == "https://img.example/other.jpg"
    items, _ = repository.list_products(detail.brand, limit=100, offset=0)
    assert next(i for i in items if str(i.product_id) == matched_product_id).image_url == \
        "https://img.example/cheapest.jpg"
    items, _ = repository.list_products(None, limit=100, offset=0, words=tuple(detail.canonical_name.split()[:2]))
    assert next(i for i in items if str(i.product_id) == matched_product_id).image_url == \
        "https://img.example/cheapest.jpg"


def test_offers_are_the_discounts_the_listing_history_supports(repository) -> None:
    connection = repository.connection
    products_repository._offers_cache.clear()
    listing_id, price, current_at = connection.execute(
        """SELECT cp.raw_listing_id, cp.price::int, cp.scraped_at FROM current_prices cp
           JOIN raw_listings rl USING (raw_listing_id)
           WHERE cp.is_available AND rl.matching_status IN ('matched', 'new_product') AND cp.price > 20000
           ORDER BY cp.raw_listing_id LIMIT 1""").fetchone().values()
    insert = ("INSERT INTO price_history (raw_listing_id, price, list_price, is_available, scraped_at) "
              "VALUES (%s, %s, %s, true, %s) RETURNING price_history_id")
    # the listing sold at `price` without a discount, then at half with `price` as its list price
    connection.execute(insert, (listing_id, price, None, current_at + timedelta(days=1)))
    latest = connection.execute(insert, (listing_id, price // 2, price, current_at + timedelta(days=2))).fetchone()
    offers, total = repository.list_offers(30, (), None, limit=100, offset=0)
    assert total == len(repository.list_offers(30, (), None, limit=10000, offset=0)[0])
    everything = repository.list_offers(30, (), None, limit=10000, offset=0)[0]
    mine = next(o for o in everything if o.price == price // 2 and o.list_price == price)
    assert (mine.discount_amount, mine.vs_history.status) == (price - price // 2, "consistent")
    assert all(o.vs_history.status == "consistent" and o.list_price > o.price for o in everything)
    keys = [(-o.discount_amount, -o.discount_percent) for o in everything]
    assert keys == sorted(keys)
    stores = {o.store for o in everything}
    one = sorted(stores)[0]
    assert {o.store for o in repository.list_offers(30, (one,), None, limit=10000, offset=0)[0]} == {one}
    # a list price above what the listing charged undiscounted is not a verified offer
    connection.execute("UPDATE price_history SET list_price = %s WHERE price_history_id = %s",
                       (price + 1, latest["price_history_id"]))
    products_repository._offers_cache.clear()
    assert not any(o.listing_url == mine.listing_url and o.scraped_at == mine.scraped_at
                   for o in repository.list_offers(30, (), None, limit=10000, offset=0)[0])
    products_repository._offers_cache.clear()


def test_unknown_product_is_404(client) -> None:
    assert client.get(f"/products/{uuid4()}").status_code == 404
    assert client.get(f"/products/{uuid4()}/price-history").status_code == 404
    assert client.get(f"/products/{uuid4()}/list-price-checks").status_code == 404


def test_a_retired_id_follows_its_chain_to_the_product_on_sale(repository, matched_product_id) -> None:
    connection = repository.connection
    first, second, gone, loop_a, loop_b = (uuid4() for _ in range(5))
    insert = ("INSERT INTO retired_products (product_id, replaced_by, reason, canonical_name) "
              "VALUES (%s, %s, %s, 'x')")
    connection.execute(insert, (first, second, "merged"))            # first -> second -> the product on sale
    connection.execute(insert, (second, matched_product_id, "merged"))
    connection.execute(insert, (gone, None, "no_listings"))
    connection.execute(insert, (loop_a, loop_b, "merged"))           # a cycle (should never happen) stops
    connection.execute(insert, (loop_b, loop_a, "merged"))
    assert repository.get_retirement(first) == (True, UUID(matched_product_id))
    assert repository.get_retirement(second) == (True, UUID(matched_product_id))
    assert repository.get_retirement(gone) == (True, None)
    assert repository.get_retirement(loop_a) == (True, None)
    assert repository.get_retirement(uuid4()) == (False, None)
    assert repository.get_retirement(UUID(matched_product_id)) == (False, None)
