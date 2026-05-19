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


def _make_event(
    kind: str, tick: int, *, day_index: int = 0,
    eid: str | None = None,
) -> MemoryEvent:
    """Build an event. 2026-05-20 fix-encounter-eviction-tick-semantic:
    eviction now uses day_index, so tests pass day_index explicitly."""
    return MemoryEvent(
        event_id=eid or f"ev_{kind}_d{day_index}_t{tick}",
        agent_id="a_001",
        tick=tick,
        day_index=day_index,
        simulated_time=_BASE,
        kind=kind,  # type: ignore[arg-type]
        content=f"{kind} at day {day_index} tick {tick}",
    )


class TestEvictOnlyEncounter:
    def test_evict_keeps_non_encounter_kinds(self) -> None:
        """spec scenario: evict 只删 encounter events with day_index < cutoff."""
        store = MemoryStore()
        store.append(_make_event("encounter", 10, day_index=0))   # SHOULD evict
        store.append(_make_event("action", 10, day_index=0))      # keep (not encounter)
        store.append(_make_event("encounter", 50, day_index=2))   # keep
        store.append(_make_event("reflection", 50, day_index=2))  # keep
        store.append(_make_event("encounter", 100, day_index=3))  # keep

        evicted = store.evict_cold_encounter_events(before_day_index=2)
        assert evicted == 1
        kinds_left = [e.kind for e in store.all()]
        assert kinds_left == ["action", "encounter", "reflection", "encounter"]

    def test_returns_count_correctly(self) -> None:
        store = MemoryStore()
        for d in range(10):
            store.append(_make_event("encounter", d * 10, day_index=d))
        # day 0-4 evicted (5 events)
        evicted = store.evict_cold_encounter_events(before_day_index=5)
        assert evicted == 5
        assert len(store) == 5


class TestEvictAllLegal:
    def test_evict_all_encounter_store_remains_appendable(self) -> None:
        """spec scenario: 全 evict 后 store 合法 + 可继续 append."""
        store = MemoryStore()
        store.append(_make_event("encounter", 10, day_index=0))
        store.append(_make_event("encounter", 20, day_index=1))
        store.evict_cold_encounter_events(before_day_index=99)
        # store now empty
        assert len(store) == 0
        # but still appendable
        store.append(_make_event("encounter", 1000, day_index=100))
        store.append(_make_event("action", 1001, day_index=100))
        assert len(store) == 2


class TestEvictEmptyNoOp:
    def test_evict_on_empty_store(self) -> None:
        """spec scenario: 空 store evict no-op."""
        store = MemoryStore()
        evicted = store.evict_cold_encounter_events(before_day_index=2)
        assert evicted == 0
        assert len(store) == 0


class TestIndexConsistencyAfterEvict:
    """Reverse indices SHALL be rebuilt after evict so by_kind / by_actor /
    by_location / by_tag don't point at stale or off-by-one indices."""

    def test_by_kind_index_consistent_after_evict(self) -> None:
        store = MemoryStore()
        store.append(_make_event("encounter", 10, day_index=0))
        store.append(_make_event("action", 20, day_index=0))
        store.append(_make_event("encounter", 30, day_index=2))
        store.evict_cold_encounter_events(before_day_index=1)

        # by_kind should reflect post-evict state
        encounter_left = store.by_kind("encounter")
        assert len(encounter_left) == 1
        assert encounter_left[0].day_index == 2

        action_left = store.by_kind("action")
        assert len(action_left) == 1
        assert action_left[0].day_index == 0

    def test_by_actor_index_consistent_after_evict(self) -> None:
        store = MemoryStore()
        store.append(MemoryEvent(
            event_id="e1", agent_id="self", tick=10, day_index=0,
            simulated_time=_BASE,
            kind="encounter", content="x", actor_id="other_a",
        ))
        store.append(MemoryEvent(
            event_id="e2", agent_id="self", tick=20, day_index=2,
            simulated_time=_BASE,
            kind="encounter", content="x", actor_id="other_a",
        ))
        store.append(MemoryEvent(
            event_id="e3", agent_id="self", tick=30, day_index=0,
            simulated_time=_BASE,
            kind="action", content="x", actor_id="other_a",
        ))
        store.evict_cold_encounter_events(before_day_index=1)
        # First encounter (day 0) evicted; other_a should still find e2 + e3
        hits = store.by_actor("other_a")
        assert {e.event_id for e in hits} == {"e2", "e3"}
