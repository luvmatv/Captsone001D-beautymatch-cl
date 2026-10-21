"""The query side of GET /search/semantic: the same model and text form as the listings' embeddings.

The model (~1 GB in memory, 20-30 s to load) is loaded in the background when
the API starts (main.py), so the first search does not wait for it; until it
is ready the endpoint answers 503 with Retry-After. It is loaded offline: it
must have been downloaded once (python -m src.matching.embeddings
--download-model). Without it the endpoint answers 503 and the rest of the
API works as always. If the background load was not started or failed, the
next search tries again.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from fastapi import Request

from src.matching.embeddings import ModelNotDownloaded, listing_text, load_model

logger = logging.getLogger(__name__)

Embedder = Callable[[str], list[float]]
LOAD_ERRORS = (ModelNotDownloaded, SystemExit, OSError)


class SemanticSearchUnavailable(RuntimeError):
    """The embedding model cannot be loaded: answered 503 (see main.py)."""


class ModelLoading(SemanticSearchUnavailable):
    """The model is being loaded right now: 503 with Retry-After."""


class QueryEmbedder:
    """Turns a search into a normalized vector comparable with fragrances.embedding."""

    def __init__(self, loader: Callable[[], object] = lambda: load_model(offline=True)) -> None:
        self._loader, self._model, self._lock = loader, None, threading.Lock()

    def start_loading(self) -> threading.Thread:
        """Load the model in a background thread; searches answer ModelLoading meanwhile."""
        thread = threading.Thread(target=self._load_in_background, name="semantic-model", daemon=True)
        thread.start()
        return thread

    def _load_in_background(self) -> None:
        started = time.monotonic()
        try:
            self._load()
        except Exception as error:  # the API keeps running; the next search tries again
            logger.warning("Semantic search unavailable: the embedding model did not load: %s", error)
        else:
            logger.info("Embedding model loaded for semantic search in %.1f s", time.monotonic() - started)

    def _load(self) -> None:
        with self._lock:
            if self._model is None:
                self._model = self._loader()

    def __call__(self, text: str) -> list[float]:
        if self._model is None:
            if self._lock.locked():  # another load is running: answer now instead of waiting 20-30 s
                raise ModelLoading("the embedding model is loading; try again in a few seconds")
            try:
                self._load()
            except LOAD_ERRORS as error:
                raise SemanticSearchUnavailable(str(error)) from error
        # listing_text: lower case, store abbreviations expanded, the e5 "query: " prefix
        vector = self._model.encode([listing_text(None, text)], normalize_embeddings=True)[0]
        return [float(value) for value in vector]


def get_embedder(request: Request) -> Embedder:
    return request.app.state.embedder
