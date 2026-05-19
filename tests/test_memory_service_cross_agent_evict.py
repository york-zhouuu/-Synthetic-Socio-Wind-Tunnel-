"""Layer 1 — MemoryService cross-agent evict tests.

Spec: openspec/specs/memory-event-eviction/spec.md
Requirement: "MemoryService 必须暴露 cross-agent eviction"
"""

from __future__ import annotations

from datetime import datetime

from synthetic_socio_wind_tunnel.memory.models import MemoryEvent
from synthetic_socio_wind_tunnel.memory.service import MemoryService


_BASE = datetime(2026, 4, 22, 8, 0)


def _add(
    service: MemoryService, agent_id: str, kind: str, tick: int,
    *, day_index: int = 0,
) -> None:
    """Append an event into agent's store with explicit day_index.

    2026-05-20 fix-encounter-eviction-tick-semantic: eviction now uses
    day_index, so tests pass it explicitly.
    """
    if agent_id not in service._stores:
        from synthetic_socio_wind_tunnel.memory.store import MemoryStore
        service._stores[agent_id] = MemoryStore()
    service._stores[agent_id].append(MemoryEvent(
        event_id=f"ev_{agent_id}_{kind}_d{day_index}_t{tick}",
        agent_id=agent_id,
        tick=tick,
        day_index=day_index,
        simulated_time=_BASE,
        kind=kind,  # type: ignore[arg-type]
        content="x",
    ))


def test_cross_agent_evict_accumulates_count() -> None:
    """spec scenario: 跨 agent evict 累计 (day < cutoff)."""
    service = MemoryService()
    for aid in ("a_001", "a_002", "a_003"):
        _add(service, aid, "encounter", 10, day_index=0)
        _add(service, aid, "encounter", 50, day_index=3)
    # 3 agents × 1 evicted each (day=0 < 2) = 3
    n = service.evict_cold_encounter_events_across_agents(before_day_index=2)
    assert n == 3
    for aid in ("a_001", "a_002", "a_003"):
        remaining = service._stores[aid].all()
        assert len(remaining) == 1
        assert remaining[0].day_index == 3


def test_cross_agent_evict_idempotent() -> None:
    """spec scenario: 二次调用 idempotent."""
    service = MemoryService()
    _add(service, "a_001", "encounter", 10, day_index=0)
    _add(service, "a_001", "encounter", 50, day_index=3)
    first = service.evict_cold_encounter_events_across_agents(before_day_index=2)
    second = service.evict_cold_encounter_events_across_agents(before_day_index=2)
    assert first == 1
    assert second == 0


def test_cross_agent_evict_empty_service() -> None:
    """No agents → returns 0, no crash."""
    service = MemoryService()
    n = service.evict_cold_encounter_events_across_agents(before_day_index=99)
    assert n == 0


def test_cross_agent_evict_non_encounter_untouched() -> None:
    """Other kinds preserved across all agents."""
    service = MemoryService()
    _add(service, "a_001", "action", 10, day_index=0)
    _add(service, "a_001", "encounter", 10, day_index=0)
    _add(service, "a_002", "reflection", 10, day_index=0)
    n = service.evict_cold_encounter_events_across_agents(before_day_index=2)
    assert n == 1
    # a_001 should still have its action; a_002 still has reflection
    assert len(service._stores["a_001"]) == 1
    assert service._stores["a_001"].all()[0].kind == "action"
    assert len(service._stores["a_002"]) == 1
    assert service._stores["a_002"].all()[0].kind == "reflection"
