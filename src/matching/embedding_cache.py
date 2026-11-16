"""Local copy of raw_listings.embedding, so the pipeline does not read every vector from the database.

Each run used to read all active embeddings as text (~41 MB for ~5,400 listings):
on Neon's free plan, with its 5 GB a month of network transfer, that was a sixth
of the monthly allowance every week (2026-11-16). Now the pipeline reads only
md5(embedding::text) of each listing (32 characters) and fetches the full vector
only for listings that are not in the cache or whose md5 changed (new listings,
re-embedded ones, a vector edited by hand). A cached vector is used only when
its md5 equals the database's, so the cache can never feed a stale vector.

The file (CACHE_PATH, by default ~/bm-backups/embedding_cache.npz, or
BM_EMBEDDING_CACHE) keeps every vector ever read, active or not, keyed by
raw_listing_id. It also serves to restore a backup made without embeddings
(src/restore_backup.py). Deleting it is safe: the next run reads everything again.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

import numpy as np

from src.backup import BACKUP_DIRECTORY

logger = logging.getLogger(__name__)

CACHE_PATH = Path(os.environ.get("BM_EMBEDDING_CACHE", BACKUP_DIRECTORY / "embedding_cache.npz"))


def digest(vector_text: str) -> str:
    """md5 of a vector's text, the same value PostgreSQL's md5(embedding::text) gives."""
    return hashlib.md5(vector_text.encode("utf-8")).hexdigest()


def parse_vector(vector_text: str) -> np.ndarray:
    """pgvector's text ("[0.1,0.2,...]") as the float32 array the pipeline uses."""
    return np.array([float(x) for x in vector_text.strip("[]").split(",")], dtype=np.float32)


class EmbeddingCache:
    """raw_listing_id -> (md5 of the vector's text, vector)."""

    def __init__(self, path: Path = CACHE_PATH) -> None:
        self.path = path
        self._entries: dict[str, tuple[str, np.ndarray]] = {}
        self.changed = False
        self.last_read = 0   # vectors read from the database by the last load_listings
        if path.is_file():
            try:
                with np.load(path, allow_pickle=False) as data:
                    for id_, md5, vector in zip(data["ids"], data["digests"], data["vectors"]):
                        self._entries[str(id_)] = (str(md5), vector)
            except (OSError, ValueError, KeyError) as error:   # a damaged file: start over, it is only a copy
                logger.warning("embedding cache %s unreadable (%s): reading every vector again", path, error)
                self._entries = {}

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, listing_id: str, md5: str) -> np.ndarray | None:
        """The cached vector, only if it is the one the database has now (same md5)."""
        entry = self._entries.get(listing_id)
        return entry[1] if entry is not None and entry[0] == md5 else None

    def put(self, listing_id: str, vector_text: str) -> np.ndarray:
        """Store a vector read from the database; returns it parsed."""
        vector = parse_vector(vector_text)
        self._entries[listing_id] = (digest(vector_text), vector)
        self.changed = True
        return vector

    def items(self):
        """(raw_listing_id, vector) of every cached listing."""
        return ((id_, vector) for id_, (_, vector) in self._entries.items())

    def save(self) -> None:
        """Write the file if something changed (atomically: a crash leaves the previous file)."""
        if not self.changed or not self._entries:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        ids = list(self._entries)
        partial = self.path.with_name(self.path.name + ".partial")
        with partial.open("wb") as out:
            np.savez(out, ids=np.array(ids), digests=np.array([self._entries[i][0] for i in ids]),
                     vectors=np.stack([self._entries[i][1] for i in ids]).astype(np.float32))
        partial.replace(self.path)
        self.changed = False
