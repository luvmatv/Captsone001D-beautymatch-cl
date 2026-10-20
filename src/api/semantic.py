"""The query side of GET /search/semantic: the same model and text form as the listings' embeddings.

The model (~1 GB in memory) is loaded on the first semantic search, not when
the API starts, and offline: it must have been downloaded once
(python -m src.matching.embeddings --download-model). Without it the
endpoint answers 503 and the rest of the API works as always.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from fastapi import Request

from src.matching.embeddings import ModelNotDownloaded, listing_text, load_model

Embedder = Callable[[str], list[float]]


class SemanticSearchUnavailable(RuntimeError):
    """The embedding model cannot be loaded: answered 503 (see main.py)."""


class QueryEmbedder:
    """Turns a search into a normalized vector comparable with fragrances.embedding."""

    def __init__(self, loader: Callable[[], object] = lambda: load_model(offline=True)) -> None:
        self._loader, self._model, self._lock = loader, None, threading.Lock()

    def __call__(self, text: str) -> list[float]:
        if self._model is None:
            with self._lock:  # one load even if several requests arrive together
                if self._model is None:
                    try:
                        self._model = self._loader()
                    except (ModelNotDownloaded, SystemExit, OSError) as error:
                        raise SemanticSearchUnavailable(str(error)) from error
        # listing_text: lower case, store abbreviations expanded, the e5 "query: " prefix
        vector = self._model.encode([listing_text(None, text)], normalize_embeddings=True)[0]
        return [float(value) for value in vector]


def get_embedder(request: Request) -> Embedder:
    return request.app.state.embedder
