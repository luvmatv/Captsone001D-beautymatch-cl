"""Less transfer from the database (2026-11-16), against the copied catalog in beautymatch_test:
the embedding cache gives the pipeline the same vectors, and a backup without embeddings
restores the same rows. Everything runs in a transaction that is rolled back."""

import numpy as np
import psycopg
import pytest

from src.backup import export_tables
from src.matching.embedding_cache import EmbeddingCache, digest
from src.matching.pipeline import load_listings
from src.restore_backup import fill_embeddings, load_tables


@pytest.fixture
def connection(catalog_database_url):
    with psycopg.connect(catalog_database_url) as connection:
        try:
            yield connection
        finally:
            connection.rollback()


def test_the_cache_gives_the_same_listings_and_reads_only_what_changed(connection, tmp_path) -> None:
    plain = load_listings(connection)
    if not plain:
        pytest.skip("no embedded listings in the copied catalog")
    cache = EmbeddingCache(tmp_path / "cache.npz")
    cold = load_listings(connection, cache=cache)
    assert cache.last_read == len(plain)
    warm = load_listings(connection, cache=EmbeddingCache(tmp_path / "cache.npz"))   # from the saved file
    for a, b, c in zip(plain, cold, warm, strict=True):
        assert (a.id, a.name, a.store) == (b.id, b.name, b.store) == (c.id, c.name, c.store)
        assert np.array_equal(a.embedding, b.embedding) and np.array_equal(a.embedding, c.embedding)

    # a vector changed in the database (re-embedded, edited by hand): only that one is read again
    changed = plain[0]
    connection.execute("UPDATE raw_listings SET embedding = %s::vector WHERE raw_listing_id = %s",
                       ("[" + ",".join(["0.5"] * len(changed.embedding)) + "]", changed.id))
    again = EmbeddingCache(tmp_path / "cache.npz")
    listings = load_listings(connection, cache=again)
    assert again.last_read == 1
    assert np.allclose(next(x for x in listings if x.id == changed.id).embedding, 0.5)


def test_the_tests_never_write_the_real_cache() -> None:
    from src.matching import embedding_cache
    real = embedding_cache.BACKUP_DIRECTORY / "embedding_cache.npz"
    assert EmbeddingCache().path != real and EmbeddingCache().path == embedding_cache.CACHE_PATH


def test_python_and_postgres_agree_on_the_md5_of_a_vector(connection) -> None:
    row = connection.execute("SELECT embedding::text, md5(embedding::text) FROM raw_listings "
                             "WHERE embedding IS NOT NULL LIMIT 1").fetchone()
    if row is None:
        pytest.skip("no embedded listings in the copied catalog")
    assert digest(row[0]) == row[1]


SNAPSHOT = """
SELECT (SELECT md5(string_agg(t::text, ',' ORDER BY raw_listing_id))
        FROM (SELECT raw_listing_id, store_id, product_id, listing_url, raw_name, raw_brand, is_active,
                     matching_status, parsed_volume_ml, embedding::text AS embedding FROM raw_listings) t),
       (SELECT md5(string_agg(t::text, ',' ORDER BY fragrance_id))
        FROM (SELECT fragrance_id, identity_key, brand, name, gender FROM fragrances) t),
       (SELECT count(*) FROM raw_listings), (SELECT count(*) FROM fragrances)
"""


def test_a_backup_without_embeddings_restores_the_same_rows_and_vectors(connection, tmp_path) -> None:
    before = connection.execute(SNAPSHOT).fetchone()
    if not before[2]:
        pytest.skip("no listings in the copied catalog")
    manifest = export_tables(connection, tmp_path / "tables.zip")
    assert {t: i["rows"] for t, i in manifest["tables"].items()} == {"raw_listings": before[2], "fragrances": before[3]}
    assert all("embedding" not in info["columns"] for info in manifest["tables"].values())
    cache = EmbeddingCache(tmp_path / "cache.npz")
    for id_, text in connection.execute("SELECT raw_listing_id::text, embedding::text FROM raw_listings "
                                        "WHERE embedding IS NOT NULL").fetchall():
        cache.put(id_, text)

    # as a restore does: the two tables empty, then their rows from the zip, then the vectors from the cache
    connection.execute("SET session_replication_role = replica")   # the other tables keep pointing at these rows
    connection.execute("DELETE FROM raw_listings")
    connection.execute("DELETE FROM fragrances")
    assert load_tables(connection, tmp_path / "tables.zip") == {"raw_listings": before[2], "fragrances": before[3]}
    assert fill_embeddings(connection, cache) == len(cache)
    connection.execute("SET session_replication_role = origin")
    after = connection.execute(SNAPSHOT).fetchone()
    assert after == before   # same rows, and the same vectors byte for byte (their text is compared)
