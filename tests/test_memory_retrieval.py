"""Tests for MemoryRetriever 4-way scoring."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from synthetic_socio_wind_tunnel.memory.models import MemoryEvent, MemoryQuery
from synthetic_socio_wind_tunnel.memory.retrieval import MemoryRetriever
from synthetic_socio_wind_tunnel.memory.store import MemoryStore


def _event(
    *,
    event_id: str,
    tick: int = 0,
    sim_time: datetime | None = None,
    kind: str = "action",
    actor_id: str | None = None,
    location_id: str | None = None,
    tags: tuple[str, ...] = (),
    content: str = "",
    importance: float = 0.5,
    embedding: tuple[float, ...] | None = None,
) -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        agent_id="emma",
        tick=tick,
        simulated_time=sim_time or datetime(2026, 4, 21, 7, 0),
        kind=kind,  # type: ignore
        content=content,
        actor_id=actor_id,
        location_id=location_id,
        importance=importance,
        tags=tags,
        embedding=embedding,
    )


class TestStructuralScoring:

    def test_actor_match_wins(self):
        store = MemoryStore()
        store.append(_event(event_id="a", actor_id="linda"))
        store.append(_event(event_id="b", actor_id="bob"))
        r = MemoryRetriever()
        result = r.retrieve(store, MemoryQuery(actor_id="linda"))
        assert result[0].event_id == "a"

    def test_location_filter(self):
        store = MemoryStore()
        store.append(_event(event_id="a", location_id="cafe_a"))
        store.append(_event(event_id="b", location_id="park"))
        r = MemoryRetriever()
        result = r.retrieve(store, MemoryQuery(location_id="cafe_a"))
        assert {e.event_id for e in result} == {"a"}


class TestRecencyScoring:

    def test_more_recent_ranks_higher(self):
        t0 = datetime(2026, 4, 21, 7, 0)
        store = MemoryStore()
        store.append(_event(event_id="old", sim_time=t0, actor_id="x"))
        store.append(_event(event_id="new", sim_time=t0 + timedelta(hours=2),
                             actor_id="x"))
        r = MemoryRetriever()
        result = r.retrieve(
            store,
            MemoryQuery(actor_id="x",
                        reference_time=t0 + timedelta(hours=2)),
        )
        assert result[0].event_id == "new"


class TestKeywordScoring:

    def test_substring_case_insensitive(self):
        store = MemoryStore()
        store.append(_event(event_id="a", content="Met LINDA at the cafe",
                             actor_id="linda"))
        store.append(_event(event_id="b", content="Walked alone"))
        r = MemoryRetriever()
        result = r.retrieve(store, MemoryQuery(keyword="linda"))
        assert {e.event_id for e in result if "linda" in e.content.lower()} == {"a"}


class TestEmbeddingScoring:

    def test_embedding_contributes(self):
        store = MemoryStore()
        # 两条 event，一条有相似 embedding，一条完全不同
        target = (1.0, 0.0, 0.0)
        store.append(_event(
            event_id="close", content="target item", embedding=target,
        ))
        store.append(_event(
            event_id="far", content="unrelated item",
            embedding=(0.0, 1.0, 0.0),
        ))
        r = MemoryRetriever()
        result = r.retrieve(
            store,
            MemoryQuery(embedding_query=target,
                        reference_time=datetime(2026, 4, 21, 7, 0)),
        )
        assert result[0].event_id == "close"

    def test_null_embedding_degraded(self):
        """event / query 缺 embedding → embed 子分 = 0，其它分继续工作。"""
        store = MemoryStore()
        store.append(_event(event_id="a", actor_id="linda"))
        r = MemoryRetriever()
        result = r.retrieve(store, MemoryQuery(actor_id="linda"))
        assert result[0].event_id == "a"  # structural 子分仍命中


class TestMinImportance:

    def test_below_threshold_filtered(self):
        store = MemoryStore()
        store.append(_event(event_id="low", importance=0.2, actor_id="x"))
        store.append(_event(event_id="high", importance=0.8, actor_id="x"))
        r = MemoryRetriever()
        result = r.retrieve(
            store, MemoryQuery(actor_id="x", min_importance=0.5)
        )
        assert [e.event_id for e in result] == ["high"]


class TestFallback:

    def test_empty_query_returns_recent(self):
        store = MemoryStore()
        for i in range(5):
            store.append(_event(event_id=f"e{i}"))
        r = MemoryRetriever()
        result = r.retrieve(store, MemoryQuery(), top_k=3)
        assert len(result) == 3


class TestTopK:

    def test_respects_top_k(self):
        store = MemoryStore()
        for i in range(20):
            store.append(_event(event_id=f"e{i}", actor_id="x"))
        r = MemoryRetriever()
        result = r.retrieve(store, MemoryQuery(actor_id="x"), top_k=5)
        assert len(result) == 5
