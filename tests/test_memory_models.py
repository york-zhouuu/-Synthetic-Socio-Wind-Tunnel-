"""Tests for memory models + store + embedding."""

from __future__ import annotations

from datetime import datetime

import pytest

from synthetic_socio_wind_tunnel.memory.embedding import (
    NullEmbedding,
    cosine_similarity,
)
from synthetic_socio_wind_tunnel.memory.models import (
    DailySummary,
    MemoryEvent,
    MemoryQuery,
)
from synthetic_socio_wind_tunnel.memory.store import MemoryStore


def _event(
    event_id: str = "ev_1",
    agent_id: str = "emma",
    tick: int = 0,
    kind: str = "action",
    actor_id: str | None = None,
    location_id: str | None = None,
    content: str = "did something",
    urgency: float = 0.0,
    importance: float = 0.5,
    tags: tuple[str, ...] = (),
    sim_time: datetime | None = None,
) -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        agent_id=agent_id,
        tick=tick,
        simulated_time=sim_time or datetime(2026, 4, 21, 7, 0),
        kind=kind,  # type: ignore
        content=content,
        actor_id=actor_id,
        location_id=location_id,
        urgency=urgency,
        importance=importance,
        tags=tags,
    )


class TestMemoryEvent:

    def test_construct_basic(self):
        e = _event(content="ran into linda", actor_id="linda")
        assert e.actor_id == "linda"
        assert e.content == "ran into linda"
        assert e.urgency == 0.0

    def test_frozen(self):
        e = _event()
        with pytest.raises(Exception):
            e.content = "changed"  # type: ignore

    def test_hashable(self):
        a = _event()
        b = _event()
        assert hash(a) == hash(b)
        assert {a, b} == {a}


class TestNullEmbedding:

    def test_fixed_dim(self):
        emb = NullEmbedding().embed("hello")
        assert isinstance(emb, tuple)
        assert len(emb) == 32

    def test_deterministic(self):
        a = NullEmbedding().embed("hello")
        b = NullEmbedding().embed("hello")
        assert a == b

    def test_different_text_different_embed(self):
        a = NullEmbedding().embed("hello")
        b = NullEmbedding().embed("world")
        assert a != b


class TestCosineSimilarity:

    def test_identical_vectors(self):
        v = (1.0, 0.0, 0.5)
        sim = cosine_similarity(v, v)
        assert sim == pytest.approx(1.0)

    def test_none_returns_zero(self):
        assert cosine_similarity(None, (1.0, 0.0)) == 0.0
        assert cosine_similarity((1.0,), None) == 0.0

    def test_different_lengths_return_zero(self):
        assert cosine_similarity((1.0, 0.0), (1.0, 0.0, 0.0)) == 0.0


class TestMemoryStore:

    def test_empty_store(self):
        s = MemoryStore()
        assert len(s) == 0
        assert s.recent(5) == ()

    def test_append_updates_indexes(self):
        s = MemoryStore()
        e1 = _event(event_id="1", actor_id="linda", location_id="cafe_a",
                    kind="encounter", tags=("social",))
        e2 = _event(event_id="2", actor_id="bob", location_id="cafe_a",
                    kind="encounter")
        s.append(e1)
        s.append(e2)
        assert len(s) == 2
        assert len(s.by_actor("linda")) == 1
        assert len(s.by_actor("bob")) == 1
        assert len(s.by_location("cafe_a")) == 2
        assert len(s.by_kind("encounter")) == 2
        assert len(s.by_tag("social")) == 1

    def test_recent_returns_last_n(self):
        s = MemoryStore()
        for i in range(5):
            s.append(_event(event_id=f"e{i}", content=f"n{i}"))
        recent = s.recent(3)
        assert len(recent) == 3
        assert recent[-1].content == "n4"  # 最新的在最后

    def test_replace_updates_tags_index(self):
        s = MemoryStore()
        orig = _event(event_id="x", tags=("old",))
        s.append(orig)
        assert len(s.by_tag("old")) == 1

        new = _event(event_id="x", tags=("new",))
        ok = s.replace("x", new)
        assert ok
        assert len(s.by_tag("old")) == 0
        assert len(s.by_tag("new")) == 1

    def test_replace_missing_event_returns_false(self):
        s = MemoryStore()
        ok = s.replace("nonexistent", _event(event_id="nonexistent"))
        assert not ok


class TestMemoryQuery:

    def test_default_empty(self):
        q = MemoryQuery()
        assert q.actor_id is None
        assert q.location_id is None
        assert q.tags == ()
        assert q.min_importance == 0.0

    def test_with_fields(self):
        q = MemoryQuery(actor_id="linda", kind="encounter", tags=("social",))
        assert q.actor_id == "linda"
        assert q.kind == "encounter"


class TestDailySummary:

    def test_construct(self):
        s = DailySummary(
            agent_id="emma",
            date="2026-04-21",
            summary_text="Today Emma went to cafe and met Linda.",
        )
        assert s.agent_id == "emma"
        assert s.event_tags == {}
