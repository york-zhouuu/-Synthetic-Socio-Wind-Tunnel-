"""Backlog 1.7 A+ — action event eviction.

Once encounter events are deduped, action events become the largest
remaining per-day event kind (~290K/agent-day). This evict path lets
the operator opt-in via `ACTION_EVICT_ENABLED=true` to also drop old
action events at day_end / pre-snapshot prune.

Default OFF — preserves existing behavior. Tests directly invoke the
function so they don't depend on env state at orchestrator level.
"""

from __future__ import annotations

from datetime import datetime

from synthetic_socio_wind_tunnel.memory.models import MemoryEvent
from synthetic_socio_wind_tunnel.memory.store import MemoryStore


_BASE = datetime(2026, 5, 22, 8, 0)


def _action(*, owner: str, day: int, tick: int) -> MemoryEvent:
    return MemoryEvent(
        event_id=f"ev_act_{owner}_d{day}_t{tick}",
        agent_id=owner,
        tick=tick,
        simulated_time=_BASE,
        kind="action",
        content="walked to cafe",
        day_index=day,
    )


def _encounter(*, owner: str, other: str, day: int, tick: int) -> MemoryEvent:
    return MemoryEvent(
        event_id=f"ev_enc_{owner}_{other}_d{day}_t{tick}",
        agent_id=owner,
        tick=tick,
        simulated_time=_BASE,
        kind="encounter",
        content=f"ran into {other}",
        actor_id=other,
        day_index=day,
        tags=("encounter", "noticed"),
    )


class TestActionEviction:
    def test_evict_cold_action_events_drops_old(self) -> None:
        store = MemoryStore()
        for day in (0, 1, 2, 3, 4):
            for tick in (10, 20, 30):
                store.append(_action(owner="a_001", day=day, tick=tick))
        assert len(store) == 15
        # Keep day >= 3
        evicted = store.evict_cold_action_events(before_day_index=3)
        assert evicted == 9  # day 0, 1, 2 → 3 days × 3 events
        remaining_days = sorted({ev.day_index for ev in store.all()})
        assert remaining_days == [3, 4]

    def test_action_evict_leaves_encounter_alone(self) -> None:
        """Encounter eviction and action eviction are independent kinds."""
        store = MemoryStore()
        store.append(_action(owner="a_001", day=1, tick=10))
        store.append(_encounter(owner="a_001", other="a_002", day=1, tick=10))
        store.append(_encounter(owner="a_001", other="a_002", day=2, tick=10))
        store.evict_cold_action_events(before_day_index=2)
        kinds_left = sorted(ev.kind for ev in store.all())
        assert kinds_left == ["encounter", "encounter"]

    def test_encounter_evict_leaves_action_alone(self) -> None:
        store = MemoryStore()
        store.append(_action(owner="a_001", day=0, tick=10))
        store.append(_encounter(owner="a_001", other="a_002", day=0, tick=10))
        store.evict_cold_encounter_events(before_day_index=5)
        kinds_left = sorted(ev.kind for ev in store.all())
        assert kinds_left == ["action"]  # action survived

    def test_action_evict_idempotent(self) -> None:
        store = MemoryStore()
        for day in range(5):
            store.append(_action(owner="a_001", day=day, tick=10))
        first = store.evict_cold_action_events(before_day_index=3)
        second = store.evict_cold_action_events(before_day_index=3)
        assert first == 3
        assert second == 0

    def test_action_evict_rebuilds_by_kind_index(self) -> None:
        store = MemoryStore()
        for day in (0, 1, 2, 3):
            store.append(_action(owner="a_001", day=day, tick=10))
        store.evict_cold_action_events(before_day_index=2)
        hits = store.by_kind("action")
        assert len(hits) == 2
        assert sorted(ev.day_index for ev in hits) == [2, 3]


class TestActionEvictAcrossAgents:
    def test_across_agents_wrapper_sums_correctly(self) -> None:
        from synthetic_socio_wind_tunnel.memory.service import MemoryService
        from synthetic_socio_wind_tunnel.memory.embedding import NullEmbedding

        svc = MemoryService(embedding_provider=NullEmbedding(), atlas=None)
        for agent in ("a_001", "a_002", "a_003"):
            for day in range(4):
                svc.record(agent, _action(owner=agent, day=day, tick=10))

        total = svc.evict_cold_action_events_across_agents(before_day_index=2)
        # Each agent had day 0, 1 = 2 events → 3 agents × 2 = 6
        assert total == 6
