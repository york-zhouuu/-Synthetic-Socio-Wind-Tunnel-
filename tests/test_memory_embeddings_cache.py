"""Tests for EmbeddingsCache (agent-stack-aitown-port Phase A)."""

from __future__ import annotations

import pytest

from synthetic_socio_wind_tunnel.memory.embedding import NullEmbedding
from synthetic_socio_wind_tunnel.memory.embeddings_cache import EmbeddingsCache


class _CountingProvider:
    """Test double that counts embed() calls."""

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, text: str) -> tuple[float, ...]:
        self.calls += 1
        # Return a unique vector per text via hash; deterministic
        h = hash(text) & 0xFFFFFFFF
        return (float(h % 1000), float((h >> 10) % 1000))


class TestEmbeddingsCacheHitMiss:

    def test_first_fetch_misses(self):
        provider = _CountingProvider()
        cache = EmbeddingsCache(provider=provider)
        cache.fetch("hello")
        assert provider.calls == 1
        assert cache.hit_rate() == 0.0  # 1 miss, 0 hits → 0/1

    def test_second_fetch_same_text_hits(self):
        provider = _CountingProvider()
        cache = EmbeddingsCache(provider=provider)
        v1 = cache.fetch("hello")
        v2 = cache.fetch("hello")
        assert provider.calls == 1, "second fetch should hit cache, not provider"
        assert v1 == v2

    def test_different_texts_independent(self):
        provider = _CountingProvider()
        cache = EmbeddingsCache(provider=provider)
        cache.fetch("foo")
        cache.fetch("bar")
        cache.fetch("foo")
        assert provider.calls == 2  # 2 unique texts

    def test_hit_rate_after_mixed_calls(self):
        provider = _CountingProvider()
        cache = EmbeddingsCache(provider=provider)
        cache.fetch("a")
        cache.fetch("b")
        cache.fetch("a")
        cache.fetch("a")
        cache.fetch("b")
        # 3 hits (a×2, b×1), 2 misses (a, b)
        assert cache.hit_rate() == pytest.approx(3 / 5, abs=1e-3)


class TestBatch:

    def test_batch_preserves_order(self):
        cache = EmbeddingsCache(provider=NullEmbedding())
        out = cache.fetch_batch(["x", "y", "z"])
        assert len(out) == 3
        assert out[0] == cache.fetch("x")
        assert out[1] == cache.fetch("y")

    def test_batch_with_duplicates(self):
        provider = _CountingProvider()
        cache = EmbeddingsCache(provider=provider)
        cache.fetch_batch(["a", "b", "a", "c", "b"])
        # 3 unique → 3 provider calls
        assert provider.calls == 3
        assert cache.size() == 3


class TestSizeAndClear:

    def test_size_grows(self):
        cache = EmbeddingsCache(provider=NullEmbedding())
        assert cache.size() == 0
        cache.fetch("a")
        assert cache.size() == 1
        cache.fetch("b")
        cache.fetch("a")
        assert cache.size() == 2  # "a" duplicate doesn't grow size

    def test_clear_resets_all(self):
        cache = EmbeddingsCache(provider=NullEmbedding())
        cache.fetch("a")
        cache.fetch("b")
        cache.fetch("a")  # 1 hit
        cache.clear()
        assert cache.size() == 0
        assert cache.hit_rate() == 0.0


class TestHashStability:

    def test_same_text_same_key(self):
        """Verify identical strings produce identical cache hits across instances."""
        provider1 = _CountingProvider()
        provider2 = _CountingProvider()
        c1 = EmbeddingsCache(provider=provider1)
        c2 = EmbeddingsCache(provider=provider2)
        v1 = c1.fetch("本街市集")
        v2 = c2.fetch("本街市集")
        # Same text → same hash → both fetched once from their providers
        assert provider1.calls == 1
        assert provider2.calls == 1

    def test_unicode_handling(self):
        cache = EmbeddingsCache(provider=NullEmbedding())
        # Unicode + emoji
        v1 = cache.fetch("emma 跟 linda 在 cafe 聊天 ☕")
        v2 = cache.fetch("emma 跟 linda 在 cafe 聊天 ☕")
        assert v1 == v2
        assert cache.hit_rate() == 0.5  # 1 miss + 1 hit
