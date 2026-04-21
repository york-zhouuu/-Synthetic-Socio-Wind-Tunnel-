"""Tests for MemoryService basic behavior."""

from __future__ import annotations

from datetime import datetime

import pytest

from synthetic_socio_wind_tunnel.memory import (
    MemoryEvent,
    MemoryQuery,
    MemoryService,
    NullEmbedding,
)


def _event(agent_id: str = "emma", event_id: str = "ev_1") -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        agent_id=agent_id,
        tick=0,
        simulated_time=datetime(2026, 4, 21, 7, 0),
        kind="action",
        content="test content",
    )


class TestRecordAndRetrieve:

    def test_record_then_retrieve(self):
        s = MemoryService()
        s.record("emma", _event())
        result = s.retrieve("emma", MemoryQuery(kind="action"))
        assert len(result) == 1

    def test_unknown_agent_returns_empty(self):
        s = MemoryService()
        assert s.retrieve("nobody", MemoryQuery()) == []

    def test_recent(self):
        s = MemoryService()
        for i in range(3):
            ev = MemoryEvent(
                event_id=f"e{i}", agent_id="emma", tick=i,
                simulated_time=datetime(2026, 4, 21, 7, 0),
                kind="action", content=f"c{i}",
            )
            s.record("emma", ev)
        recent = s.recent("emma", last_ticks=1)
        # last_ticks=1 means tick >= 2 (max_tick - last_ticks + 1 = 2)
        assert len(recent) == 1
        assert recent[0].content == "c2"

    def test_all_for(self):
        s = MemoryService()
        s.record("emma", _event(event_id="a"))
        s.record("emma", _event(event_id="b"))
        events = s.all_for("emma")
        assert len(events) == 2


class TestAgentIsolation:

    def test_agent_stores_isolated(self):
        s = MemoryService()
        s.record("emma", _event(agent_id="emma", event_id="a"))
        assert s.all_for("linda") == []
        assert len(s.all_for("emma")) == 1


class TestEmbeddingIntegration:

    def test_null_embedding_leaves_field_none(self):
        s = MemoryService()  # default NullEmbedding
        ev = _event()
        s.record("emma", ev)
        all_events = s.all_for("emma")
        # NullEmbedding is considered "no provider"; embedding stays None
        assert all_events[0].embedding is None

    def test_real_provider_fills_embedding(self):
        class FakeProvider:
            def embed(self, text):
                return (float(len(text)),) * 8

        s = MemoryService(embedding_provider=FakeProvider())
        s.record("emma", _event())
        all_events = s.all_for("emma")
        assert all_events[0].embedding is not None
        assert len(all_events[0].embedding) == 8
