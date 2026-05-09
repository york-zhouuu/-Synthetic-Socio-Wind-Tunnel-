"""
EmbeddingsCache — sha256-keyed dedup of embedding lookups.

Wraps an EmbeddingProvider; first request for a given text computes + caches;
subsequent requests for the same text return the cached vector. Designed for
the ai-town agent stack port where every dialogue / reflection LLM call may
embed identity_text + recent memories repeatedly.

Sync API to stay compatible with the existing `EmbeddingProvider` protocol
(which is sync). For batch optimisation use `fetch_batch()`.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.memory.embedding import EmbeddingProvider


def _hash(text: str) -> str:
    """SHA-256 hex digest of `text` (utf-8). Stable, collision-safe enough for cache key."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class EmbeddingsCache:
    """In-memory sha256(text) → embedding cache.

    Wraps an EmbeddingProvider. Tracks hit/miss stats for dev metric.
    Single-process; not thread-safe (callers expected to drive serially within
    one process — matches MemoryService's per-tick model).
    """

    __slots__ = ("_provider", "_cache", "_hits", "_misses")

    def __init__(self, provider: "EmbeddingProvider") -> None:
        self._provider = provider
        self._cache: dict[str, tuple[float, ...]] = {}
        self._hits: int = 0
        self._misses: int = 0

    def fetch(self, text: str) -> tuple[float, ...]:
        """Return embedding for `text`, using cache if present."""
        key = _hash(text)
        cached = self._cache.get(key)
        if cached is not None:
            self._hits += 1
            return cached
        emb = self._provider.embed(text)
        # Defensive: ensure tuple (provider may return list)
        emb_t = tuple(emb)
        self._cache[key] = emb_t
        self._misses += 1
        return emb_t

    def fetch_batch(self, texts: list[str]) -> list[tuple[float, ...]]:
        """Batched fetch — looks up each text individually (no provider batch API yet).

        Order-preserving; duplicates within `texts` count as cache hits after the
        first miss.
        """
        out: list[tuple[float, ...]] = []
        for t in texts:
            out.append(self.fetch(t))
        return out

    def hit_rate(self) -> float:
        """Cache hit rate; 0.0 if no calls yet."""
        total = self._hits + self._misses
        if total == 0:
            return 0.0
        return self._hits / total

    def size(self) -> int:
        return len(self._cache)

    def clear(self) -> None:
        self._cache.clear()
        self._hits = 0
        self._misses = 0


__all__ = ["EmbeddingsCache"]
