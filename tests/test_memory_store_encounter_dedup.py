"""Backlog 1.7 A — in-place encounter dedup.

Movement-induced encounters between the same (actor_id, day_index) pair
collapse to a single MemoryEvent whose `encounter_count` is bumped on
every subsequent occurrence. Dialogue-completion encounters (tagged
"dialogue") and non-encounter events are unaffected.

This is the bounded-memory mechanism that keeps per-day encounter event
count at O(pairs) instead of O(pairs × ticks_per_day). At 1000 agents
this is ~1000x reduction in encounter rows.
"""

from __future__ import annotations

from datetime import datetime

from synthetic_socio_wind_tunnel.memory.models import MemoryEvent
from synthetic_socio_wind_tunnel.memory.store import MemoryStore


_BASE = datetime(2026, 5, 22, 8, 0)


def _enc(
    *, owner: str, other: str, day: int, tick: int,
    dialogue: bool = False, location: str | None = "park_1",
) -> MemoryEvent:
    tags = ("encounter", "dialogue") if dialogue else ("encounter", "noticed")
    return MemoryEvent(
        event_id=f"ev_{owner}_{other}_d{day}_t{tick}",
        agent_id=owner,
        tick=tick,
        simulated_time=_BASE,
        kind="encounter",
        content=f"ran into {other}",
        actor_id=other,
        location_id=location,
        day_index=day,
        participants=(other,),
        tags=tags,
    )


class TestRoutineEncounterDedup:
    def test_same_pair_same_day_collapses_to_one_event(self) -> None:
        store = MemoryStore()
        for tick in range(500):
            store.append(_enc(owner="a_001", other="a_002", day=3, tick=tick))
        assert len(store) == 1
        ev = store.all()[0]
        assert ev.encounter_count == 500
        assert ev.actor_id == "a_002"
        assert ev.day_index == 3

    def test_count_starts_at_1_on_first_append(self) -> None:
        store = MemoryStore()
        store.append(_enc(owner="a_001", other="a_002", day=3, tick=10))
        assert store.all()[0].encounter_count == 1

    def test_different_days_create_separate_events(self) -> None:
        store = MemoryStore()
        for day in (3, 4, 5):
            for tick in range(100):
                store.append(_enc(owner="a_001", other="a_002", day=day, tick=tick))
        assert len(store) == 3
        counts = sorted(ev.encounter_count for ev in store.all())
        assert counts == [100, 100, 100]

    def test_different_pairs_same_day_create_separate_events(self) -> None:
        store = MemoryStore()
        for other in ("a_002", "a_003", "a_004"):
            for tick in range(50):
                store.append(_enc(owner="a_001", other=other, day=3, tick=tick))
        assert len(store) == 3
        for ev in store.all():
            assert ev.encounter_count == 50


class TestDialogueEncountersNotDeduped:
    """Dialogue-completion encounters carry intent ("had a conversation")
    and are rare per pair-day. They MUST stay as distinct events so the
    LLM can read them as separate signals."""

    def test_dialogue_encounter_appends_distinct(self) -> None:
        store = MemoryStore()
        for tick in (10, 50, 200):
            store.append(_enc(
                owner="a_001", other="a_002", day=3, tick=tick,
                dialogue=True,
            ))
        assert len(store) == 3
        for ev in store.all():
            assert ev.encounter_count == 1

    def test_routine_and_dialogue_for_same_pair_kept_separate(self) -> None:
        """If a pair has movement-encounters AND a dialogue, dialogue
        is its own event; routine ones dedup among themselves."""
        store = MemoryStore()
        for tick in range(100):
            store.append(_enc(owner="a_001", other="a_002", day=3, tick=tick))
        store.append(_enc(
            owner="a_001", other="a_002", day=3, tick=150, dialogue=True,
        ))
        assert len(store) == 2
        routine = [ev for ev in store.all() if "dialogue" not in ev.tags]
        dialogue = [ev for ev in store.all() if "dialogue" in ev.tags]
        assert len(routine) == 1 and routine[0].encounter_count == 100
        assert len(dialogue) == 1 and dialogue[0].encounter_count == 1


class TestLocationDiversityPreserved:
    """backlog 1.7 A.2: when a dedup'd pair encounters at multiple
    locations on the same day, encounter_locations accumulates the
    full ordered set of unique locations. Empty for the 86% case of
    single-location pair-days; populated for the rest."""

    def test_single_location_stays_empty(self) -> None:
        store = MemoryStore()
        for tick in range(100):
            store.append(_enc(
                owner="a_001", other="a_002", day=3, tick=tick,
                location="park_1",
            ))
        ev = store.all()[0]
        assert ev.encounter_count == 100
        assert ev.encounter_locations == ()  # lazy: stayed empty
        assert ev.location_id == "park_1"

    def test_two_locations_seed_tuple(self) -> None:
        store = MemoryStore()
        store.append(_enc(
            owner="a_001", other="a_002", day=3, tick=10,
            location="park_1",
        ))
        store.append(_enc(
            owner="a_001", other="a_002", day=3, tick=50,
            location="cafe_2",
        ))
        ev = store.all()[0]
        assert ev.encounter_count == 2
        assert ev.encounter_locations == ("park_1", "cafe_2")

    def test_three_unique_locations_accumulate(self) -> None:
        store = MemoryStore()
        for tick, loc in (
            (10, "park_1"), (50, "cafe_2"), (100, "park_1"),
            (200, "gym_3"), (250, "cafe_2"),
        ):
            store.append(_enc(
                owner="a_001", other="a_002", day=3, tick=tick,
                location=loc,
            ))
        ev = store.all()[0]
        assert ev.encounter_count == 5
        # Order preserved, duplicates filtered
        assert ev.encounter_locations == ("park_1", "cafe_2", "gym_3")

    def test_helper_returns_all_locations_for_single(self) -> None:
        from synthetic_socio_wind_tunnel.memory.models import (
            all_encounter_locations,
        )
        store = MemoryStore()
        store.append(_enc(
            owner="a_001", other="a_002", day=3, tick=10, location="park_1",
        ))
        assert all_encounter_locations(store.all()[0]) == ("park_1",)

    def test_helper_returns_all_locations_for_multi(self) -> None:
        from synthetic_socio_wind_tunnel.memory.models import (
            all_encounter_locations,
        )
        store = MemoryStore()
        store.append(_enc(
            owner="a_001", other="a_002", day=3, tick=10, location="park_1",
        ))
        store.append(_enc(
            owner="a_001", other="a_002", day=3, tick=50, location="cafe_2",
        ))
        assert all_encounter_locations(store.all()[0]) == ("park_1", "cafe_2")

    def test_locations_snapshot_round_trip(self) -> None:
        from synthetic_socio_wind_tunnel.memory.service import (
            _event_to_json, _event_from_json,
        )
        store = MemoryStore()
        for tick, loc in ((10, "p1"), (20, "p2"), (30, "p3")):
            store.append(_enc(
                owner="a_001", other="a_002", day=3, tick=tick, location=loc,
            ))
        ev = store.all()[0]
        roundtripped = _event_from_json(_event_to_json(ev))
        assert roundtripped.encounter_locations == ("p1", "p2", "p3")
        assert roundtripped.encounter_count == 3


class TestNonEncounterUnaffected:
    def test_action_events_not_deduped(self) -> None:
        store = MemoryStore()
        for tick in range(10):
            store.append(MemoryEvent(
                event_id=f"ev_action_{tick}", agent_id="a_001", tick=tick,
                simulated_time=_BASE, kind="action",
                content="walked to cafe", day_index=3,
            ))
        assert len(store) == 10
        for ev in store.all():
            assert ev.encounter_count == 1

    def test_reflection_events_not_deduped(self) -> None:
        store = MemoryStore()
        for tick in range(5):
            store.append(MemoryEvent(
                event_id=f"ev_refl_{tick}", agent_id="a_001", tick=tick,
                simulated_time=_BASE, kind="reflection",
                content="insight", day_index=3,
            ))
        assert len(store) == 5


class TestReverseIndicesAfterDedup:
    def test_by_actor_index_returns_single_dedup_event(self) -> None:
        store = MemoryStore()
        for tick in range(100):
            store.append(_enc(owner="a_001", other="a_002", day=3, tick=tick))
        hits = store.by_actor("a_002")
        assert len(hits) == 1
        assert hits[0].encounter_count == 100

    def test_by_kind_index_returns_dedup_events(self) -> None:
        store = MemoryStore()
        for tick in range(100):
            store.append(_enc(owner="a_001", other="a_002", day=3, tick=tick))
        store.append(_enc(owner="a_001", other="a_003", day=3, tick=200))
        hits = store.by_kind("encounter")
        assert len(hits) == 2


class TestEvictAfterDedup:
    def test_evict_clears_dedup_index_for_old_days(self) -> None:
        store = MemoryStore()
        for tick in range(100):
            store.append(_enc(owner="a_001", other="a_002", day=2, tick=tick))
        for tick in range(50):
            store.append(_enc(owner="a_001", other="a_002", day=4, tick=tick))
        assert len(store) == 2
        evicted = store.evict_cold_encounter_events(before_day_index=3)
        assert evicted == 1
        # After evict, only day 4 left
        remaining = store.all()
        assert len(remaining) == 1
        assert remaining[0].day_index == 4 and remaining[0].encounter_count == 50

    def test_append_after_evict_does_not_resurrect_pair(self) -> None:
        """Evicting day 2 (actor a_002) then appending a NEW day-4
        encounter for the same pair SHALL produce a fresh event, not
        keep counting from the deleted one."""
        store = MemoryStore()
        for tick in range(100):
            store.append(_enc(owner="a_001", other="a_002", day=2, tick=tick))
        store.evict_cold_encounter_events(before_day_index=3)
        store.append(_enc(owner="a_001", other="a_002", day=4, tick=10))
        store.append(_enc(owner="a_001", other="a_002", day=4, tick=20))
        events = store.all()
        assert len(events) == 1
        assert events[0].day_index == 4
        assert events[0].encounter_count == 2


class TestSnapshotRoundTripPreservesCount:
    """Without this, resume from snapshot would silently reset all
    encounter_counts to 1, undoing the optimization on every restart."""

    def test_to_json_includes_encounter_count(self) -> None:
        from synthetic_socio_wind_tunnel.memory.service import _event_to_json
        ev = _enc(owner="a_001", other="a_002", day=3, tick=10)
        from dataclasses import replace
        ev = replace(ev, encounter_count=42)
        d = _event_to_json(ev)
        assert d["encounter_count"] == 42

    def test_from_json_restores_encounter_count(self) -> None:
        from synthetic_socio_wind_tunnel.memory.service import (
            _event_to_json, _event_from_json,
        )
        ev = _enc(owner="a_001", other="a_002", day=3, tick=10)
        from dataclasses import replace
        ev = replace(ev, encounter_count=42)
        roundtripped = _event_from_json(_event_to_json(ev))
        assert roundtripped.encounter_count == 42

    def test_snapshot_load_preserves_location_diversity(self) -> None:
        """Loading legacy snapshot with N events for same pair-day at
        DIFFERENT locations: dedup gate fires per-event during
        from_snapshot_state, encounter_locations accumulates ordered
        unique set. This is what makes resume-from-snapshot of current
        dead workers a NON-lossy migration."""
        from synthetic_socio_wind_tunnel.memory.service import (
            MemoryService, _event_to_json,
        )
        from synthetic_socio_wind_tunnel.memory.embedding import NullEmbedding

        legacy_events = []
        for tick, loc in enumerate(
            ["park_1", "cafe_2", "park_1", "gym_3", "cafe_2", "park_1"]
        ):
            ev = _enc(
                owner="a_001", other="a_002", day=6, tick=tick,
                location=loc,
            )
            legacy_events.append(_event_to_json(ev))

        state = {
            "agent_events": {"a_001": legacy_events},
            "event_counter": 6, "consumed_feed_item_ids": {},
            "replan_count_today": {}, "replan_no_op_count_today": {},
            "last_day_index": 6, "last_reflection_time": {},
            "rng_state": None, "noticing_seed": 0,
        }
        svc = MemoryService(
            embedding_provider=NullEmbedding(), atlas=None,
        )
        svc.from_snapshot_state(state)
        events_after = list(svc._stores["a_001"].all())
        assert len(events_after) == 1
        assert events_after[0].encounter_count == 6
        # Unique locations in order seen
        assert events_after[0].encounter_locations == (
            "park_1", "cafe_2", "gym_3",
        )

    def test_snapshot_load_auto_dedups_legacy_duplicates(self) -> None:
        """An old (pre-dedup) snapshot may contain thousands of
        encounter events for the same (actor, day) pair. MemoryService
        from_snapshot_state calls store.append() per event → the dedup
        gate inside append() automatically collapses them. This is the
        "free migration" property: existing snapshots from a 4-worker
        dead run get rehydrated 70-1000x smaller without any explicit
        migration pass."""
        from synthetic_socio_wind_tunnel.memory.service import (
            MemoryService, _event_to_json,
        )
        from synthetic_socio_wind_tunnel.memory.embedding import NullEmbedding

        legacy_events = [
            _event_to_json(_enc(
                owner="a_001", other="a_002", day=6, tick=t,
            ))
            for t in range(1000)
        ]
        snapshot_state = {
            "agent_events": {"a_001": legacy_events},
            "event_counter": 1000, "consumed_feed_item_ids": {},
            "replan_count_today": {}, "replan_no_op_count_today": {},
            "last_day_index": 6, "last_reflection_time": {},
            "rng_state": None, "noticing_seed": 0,
        }
        svc = MemoryService(
            embedding_provider=NullEmbedding(), atlas=None,
        )
        svc.from_snapshot_state(snapshot_state)
        events_after = list(svc._stores["a_001"].all())
        assert len(events_after) == 1
        assert events_after[0].encounter_count == 1000

    def test_from_json_legacy_event_defaults_count_to_1(self) -> None:
        """Old snapshots written before this change have no
        encounter_count field. They MUST load with count=1 (the
        dataclass default), not raise."""
        from synthetic_socio_wind_tunnel.memory.service import _event_from_json
        legacy_data = {
            "event_id": "ev_legacy", "agent_id": "a_001", "tick": 10,
            "simulated_time": _BASE.isoformat(), "kind": "encounter",
            "content": "legacy event", "actor_id": "a_002",
            "day_index": 3,
            # NO encounter_count field
        }
        ev = _event_from_json(legacy_data)
        assert ev.encounter_count == 1
