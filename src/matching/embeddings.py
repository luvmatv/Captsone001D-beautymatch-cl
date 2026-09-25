"""Compute raw_listings.embedding with a local multilingual model.

Usage:
    python -m src.matching.embeddings          # listings without an embedding
    python -m src.matching.embeddings --all    # recompute every listing
"""

from __future__ import annotations

import argparse
import os
import time

import psycopg

from src.loader.raw_listings import DEFAULT_DATABASE_URL
from src.matching.normalization import expand_abbreviations

MODEL_NAME = "intfloat/multilingual-e5-base"
EMBEDDING_DIMENSIONS = 768  # must match VECTOR(768) in database/001
BATCH_SIZE = 32

SELECT_LISTINGS = """
SELECT raw_listing_id, raw_brand, raw_name FROM raw_listings
{where}
ORDER BY raw_listing_id
"""
UPDATE_EMBEDDING = "UPDATE raw_listings SET embedding = %s::vector WHERE raw_listing_id = %s"


def listing_text(brand: str | None, name: str) -> str:
    """Brand + name, lowercased so "ANTONIO BANDERAS" and "Antonio Banderas" agree,
    with store abbreviations expanded ("ARIANA GR.MOD VAI" -> "ariana grande mod vanilla").

    e5 models expect a "query: " prefix; listings are compared with each other
    (symmetric similarity), so every text gets the same prefix.
    """
    name = expand_abbreviations(name)
    brand = expand_abbreviations(brand or "")
    text = name if not brand or brand in name else f"{brand} {name}"
    return f"query: {text}"


def to_pgvector(values) -> str:
    return "[" + ",".join(f"{value:.7f}" for value in values) + "]"


def load_model():
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(MODEL_NAME, device="cpu")
    get_dimensions = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
    dimensions = get_dimensions()
    if dimensions != EMBEDDING_DIMENSIONS:
        raise SystemExit(f"{MODEL_NAME} returns {dimensions} dimensions, schema expects {EMBEDDING_DIMENSIONS}")
    return model


def main() -> None:
    parser = argparse.ArgumentParser(description="Embed raw_listings with a local model")
    parser.add_argument("--all", action="store_true", help="recompute existing embeddings too")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    args = parser.parse_args()

    with psycopg.connect(args.database_url) as connection:
        rows = connection.execute(
            SELECT_LISTINGS.format(where="" if args.all else "WHERE embedding IS NULL")
        ).fetchall()
        if not rows:
            print("Nothing to embed")
            return

        model = load_model()
        started = time.monotonic()
        texts = [listing_text(brand, name) for _, brand, name in rows]
        vectors = model.encode(
            texts, batch_size=BATCH_SIZE, normalize_embeddings=True, show_progress_bar=True
        )
        with connection.transaction(), connection.cursor() as cursor:
            cursor.executemany(
                UPDATE_EMBEDDING,
                [(to_pgvector(vector), row[0]) for row, vector in zip(rows, vectors)],
            )
        print(f"Embedded {len(rows)} listings with {MODEL_NAME} in {time.monotonic() - started:.1f}s")


if __name__ == "__main__":
    main()
