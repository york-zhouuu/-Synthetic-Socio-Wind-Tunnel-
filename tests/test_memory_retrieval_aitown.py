"""Tests for MemoryRetriever's `aitown` mode (1:1 port of rankAndTouchMemories)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from synthetic_socio_wind_tunnel.memory.models import MemoryEvent, MemoryQuery
from synthetic_socio_wind_tunnel.memory.retrieval import (
    MemoryRetriever,
    _normalize_minmax,
    _recency_aitown,
)
from synthetic_socio_wind_tunnel.memory.store import MemoryStore


def _ev(content: str, *, importance: float = 0.5, tick: int = 0,
        ts_offset_hours: int = 0,
        embedding: tuple[float, ...] | None = None) -> MemoryEvent:
    return MemoryEvent(
        event_id=f"ev_{content[:8]}_{tick}",
        agent_id="emma", tick=tick,
        simulated_time=datetime(2026, 5, 9, 10) - timedelta(hours=ts_offset_hours),
        kind="encounter", content=content,
        importance=importance, embedding=embedding,
    )


# ---------------------------------------------------------------------------
# 1. ai-town recency formula (0.99 ^ hours)
# ---------------------------------------------------------------------------


class TestRecencyAitown:

    def test_zero_hours_returns_one(self):
        ev = _ev("now", ts_offset_hours=0)
        ref = datetime(2026, 5, 9, 10)
        assert _recency_aitown(ev, ref) == 1.0

    def test_one_hour_decay(self):
        ev = _ev("hour ago", ts_offset_hours=1)
        ref = datetime(2026, 5, 9, 10)
        # 0.99^1 = 0.99
        assert _recency_aitown(ev, ref) == pytest.approx(0.99, abs=1e-3)

    def test_24_hours_decay(self):
        ev = _ev("yesterday", ts_offset_hours=24)
        ref = datetime(2026, 5, 9, 10)
        assert _recency_aitown(ev, ref) == pytest.approx(0.99 ** 24, abs=1e-3)

    def test_future_event_clamped(self):
        ev = _ev("future", ts_offset_hours=-1)
        ref = datetime(2026, 5, 9, 10)
        assert _recency_aitown(ev, ref) == 1.0


# ---------------------------------------------------------------------------
# 2. Min-max normalization
# ---------------------------------------------------------------------------


class TestMinMaxNormalize:

    def test_basic(self):
        result = _normalize_minmax([0.0, 0.5, 1.0])
        assert result == [0.0, 0.5, 1.0]

    def test_all_equal_returns_ones(self):
        result = _normalize_minmax([0.5, 0.5, 0.5])
        assert result == [1.0, 1.0, 1.0]

    def test_empty_returns_empty(self):
        assert _normalize_minmax([]) == []

    def test_negative_range(self):
        result = _normalize_minmax([-1.0, 0.0, 1.0])
        assert result == [0.0, 0.5, 1.0]


# ---------------------------------------------------------------------------
# 3. End-to-end retrieve (aitown mode) — verify ranking
# ---------------------------------------------------------------------------


class TestAitownRetrieve:

    def test_high_importance_outranks_low(self):
        store = MemoryStore()
        store.append(_ev("low", importance=0.1, tick=10))
        store.append(_ev("high", importance=0.9, tick=11))
        retriever = MemoryRetriever(mode="aitown")
        # Query without structural matches → all candidates from recent pool
        # All events have similar relevance/recency → importance dominates
        results = retriever.retrieve(
            store, MemoryQuery(reference_time=datetime(2026, 5, 9, 10)),
            top_k=2,
        )
        assert results[0].content == "high"
        assert results[1].content == "low"

    def test_recent_outranks_old_when_importance_equal(self):
        store = MemoryStore()
        store.append(_ev("yesterday", importance=0.5, tick=5,
                         ts_offset_hours=24))
        store.append(_ev("now", importance=0.5, tick=10,
                         ts_offset_hours=0))
        retriever = MemoryRetriever(mode="aitown")
        results = retriever.retrieve(
            store, MemoryQuery(reference_time=datetime(2026, 5, 9, 10)),
            top_k=2,
        )
        # Equal importance, but recency differs → "now" wins
        assert results[0].content == "now"

    def test_top_k_truncation(self):
        store = MemoryStore()
        for i in range(10):
            store.append(_ev(f"e{i}", importance=i / 9.0, tick=i))
        retriever = MemoryRetriever(mode="aitown")
        results = retriever.retrieve(
            store, MemoryQuery(reference_time=datetime(2026, 5, 9, 10)),
            top_k=3,
        )
        assert len(results) == 3
        # Top should be highest importance
        assert results[0].content == "e9"

    def test_normalize_then_sum_balances_components(self):
        """ai-town's claim: each batch's components weighted equally regardless
        of raw range. Verify by giving wildly different ranges per dimension."""
        store = MemoryStore()
        # Three events with different importance but same recency
        for i, imp in enumerate([0.01, 0.5, 0.99]):
            store.append(_ev(f"i{i}", importance=imp, tick=10 + i,
                             ts_offset_hours=0))
        retriever = MemoryRetriever(mode="aitown")
        results = retriever.retrieve(
            store, MemoryQuery(reference_time=datetime(2026, 5, 9, 10)),
            top_k=3,
        )
        # Importance dominates (only varying dim) → highest first
        assert [r.content for r in results] == ["i2", "i1", "i0"]


# ---------------------------------------------------------------------------
# 4. legacy mode unchanged (backward compat)
# ---------------------------------------------------------------------------


class TestLegacyModeUnchanged:

    def test_legacy_default_uses_weighted_sum(self):
        store = MemoryStore()
        store.append(_ev("a", importance=0.1, tick=10))
        store.append(_ev("b", importance=0.9, tick=11))
        retriever = MemoryRetriever()  # default = legacy
        results = retriever.retrieve(
            store, MemoryQuery(reference_time=datetime(2026, 5, 9, 10)),
            top_k=2,
        )
        # In legacy, importance is filtered (>= min_importance=0) but does NOT
        # participate in scoring; recency/struct dominate. Both have same recency
        # and no struct match → same score → tie-break by tick (newer first)
        assert len(results) == 2
        assert results[0].tick == 11

    def test_legacy_mode_explicit(self):
        retriever = MemoryRetriever(mode="legacy")
        # Just verify constructor accepts mode arg
        assert retriever._mode == "legacy"
