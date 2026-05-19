"""Layer 1 — MemoryStore.evict_cold_encounter_events unit tests.

Spec: openspec/specs/memory-event-eviction/spec.md
Requirement: "MemoryStore 必须支持 cold prune encounter events"

TDD red phase: method doesn't exist yet → AttributeError expected.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from synthetic_socio_wind_tunnel.memory.models import MemoryEvent
from synthetic_socio_wind_tunnel.memory.store import MemoryStore


_BASE = datetime(2026, 4, 22, 8, 0)


def _make_event(kind: str, tick: int, eid: str | None = None) -> MemoryEvent:
    return MemoryEvent(
        event_id=eid or f"ev_{kind}_{tick}",
        agent_id="a_001",
        tick=tick,
        simulated_time=_BASE,
        kind=kind,  # type: ignore[arg-type]
        content=f"{kind} at tick {tick}",
    )


class TestEvictOnlyEncounter:
    def test_evict_keeps_non_encounter_kinds(self) -> None:
        """spec scenario: evict 只删 encounter events."""
        store = MemoryStore()
        store.append(_make_event("encounter", 10))   # SHOULD evict
        store.append(_make_event("action", 10))      # keep
        store.append(_make_event("encounter", 200))  # keep (tick >= cutoff)
        store.append(_make_event("reflection", 200)) # keep
        store.append(_make_event("encounter", 300))  # keep

        evicted = store.evict_cold_encounter_events(before_tick=150)
        assert evicted == 1
        kinds_left = [e.kind for e in store.all()]
        assert kinds_left == ["action", "encounter", "reflection", "encounter"]

    def test_returns_count_correctly(self) -> None:
        store = MemoryStore()
        for i in range(10):
            store.append(_make_event("encounter", i * 10))
        # All ticks 0..90 — evict all with tick < 50 (5 events: tick 0,10,20,30,40)
        evicted = store.evict_cold_encounter_events(before_tick=50)
        assert evicted == 5
        assert len(store) == 5


class TestEvictAllLegal:
    def test_evict_all_encounter_store_remains_appendable(self) -> None:
        """spec scenario: 全 evict 后 store 合法 + 可继续 append."""
        store = MemoryStore()
        store.append(_make_event("encounter", 10))
        store.append(_make_event("encounter", 20))
        store.evict_cold_encounter_events(before_tick=999)
        # store now empty (both were encounter < 999)
        assert len(store) == 0
        # but still appendable
        store.append(_make_event("encounter", 1000))
        store.append(_make_event("action", 1001))
        assert len(store) == 2


class TestEvictEmptyNoOp:
    def test_evict_on_empty_store(self) -> None:
        """spec scenario: 空 store evict no-op."""
        store = MemoryStore()
        evicted = store.evict_cold_encounter_events(before_tick=100)
        assert evicted == 0
        assert len(store) == 0


class TestIndexConsistencyAfterEvict:
    """Reverse indices SHALL be rebuilt after evict so by_kind / by_actor /
    by_location / by_tag don't point at stale or off-by-one indices."""

    def test_by_kind_index_consistent_after_evict(self) -> None:
        store = MemoryStore()
        store.append(_make_event("encounter", 10))
        store.append(_make_event("action", 20))
        store.append(_make_event("encounter", 30))
        store.evict_cold_encounter_events(before_tick=25)

        # by_kind should reflect post-evict state
        encounter_left = store.by_kind("encounter")
        assert len(encounter_left) == 1
        assert encounter_left[0].tick == 30

        action_left = store.by_kind("action")
        assert len(action_left) == 1
        assert action_left[0].tick == 20

    def test_by_actor_index_consistent_after_evict(self) -> None:
        store = MemoryStore()
        store.append(MemoryEvent(
            event_id="e1", agent_id="self", tick=10, simulated_time=_BASE,
            kind="encounter", content="x", actor_id="other_a",
        ))
        store.append(MemoryEvent(
            event_id="e2", agent_id="self", tick=20, simulated_time=_BASE,
            kind="encounter", content="x", actor_id="other_a",
        ))
        store.append(MemoryEvent(
            event_id="e3", agent_id="self", tick=30, simulated_time=_BASE,
            kind="action", content="x", actor_id="other_a",
        ))
        store.evict_cold_encounter_events(before_tick=15)
        # First encounter evicted; other_a should still find e2 + e3
        hits = store.by_actor("other_a")
        assert {e.event_id for e in hits} == {"e2", "e3"}
