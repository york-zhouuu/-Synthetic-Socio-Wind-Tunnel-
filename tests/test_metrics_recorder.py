"""Tests for TickMetricsRecorder."""

from __future__ import annotations

from datetime import datetime
from random import Random

from synthetic_socio_wind_tunnel.agent import AgentProfile, AgentRuntime
from synthetic_socio_wind_tunnel.agent.intent import MoveIntent, WaitIntent
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.engine.simulation import SimulationResult
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.metrics import TickMetricsRecorder
from synthetic_socio_wind_tunnel.orchestrator.models import (
    CommitRecord,
    EncounterCandidate,
    TickResult,
)


def _ledger_with(agents: list[tuple[str, str]]) -> Ledger:
    ledger = Ledger()
    ledger.current_time = datetime(2026, 4, 22)
    for agent_id, loc in agents:
        ledger.set_entity(EntityState(
            entity_id=agent_id, location_id=loc, position=Coord(x=0.0, y=0.0),
        ))
    return ledger


def _tick(
    day_index: int, tick_index: int,
    *,
    commits: tuple[CommitRecord, ...] = (),
    encounters: tuple[EncounterCandidate, ...] = (),
) -> TickResult:
    return TickResult(
        tick_index=tick_index,
        simulated_time=datetime(2026, 4, 22, 8, 0, 0),
        commits=commits,
        encounter_candidates=encounters,
        day_index=day_index,
    )


class TestRecorderBasic:
    def test_counts_encounters(self):
        ledger = _ledger_with([("a1", "loc_a")])
        rec = TickMetricsRecorder(ledger=ledger)
        rec.on_tick_end(_tick(0, 0, encounters=(
            EncounterCandidate(tick=0, agent_a="a1", agent_b="a2", shared_locations=("x",)),
        )))
        snap = rec.snapshot()
        assert len(snap) == 1
        assert snap[0].encounter_count_total == 1
        assert snap[0].distinct_encounter_pairs == 1

    def test_counts_commits(self):
        ledger = _ledger_with([("a1", "loc_a")])
        rec = TickMetricsRecorder(ledger=ledger)
        ok_commit = CommitRecord(
            agent_id="a1", intent=WaitIntent(),
            result=SimulationResult.ok(),
        )
        fail_commit = CommitRecord(
            agent_id="a2", intent=WaitIntent(),
            result=SimulationResult.fail("bad"),
        )
        rec.on_tick_end(_tick(0, 0, commits=(ok_commit, fail_commit)))
        snap = rec.snapshot()
        assert snap[0].move_success_count == 1
        assert snap[0].move_fail_count == 1

    def test_location_dwell_accumulates(self):
        ledger = _ledger_with([("a1", "loc_a"), ("a2", "loc_a")])
        rec = TickMetricsRecorder(ledger=ledger)
        for tick in range(5):
            rec.on_tick_end(_tick(0, tick))
        snap = rec.snapshot()
        # 2 agents × 5 ticks = 10 dwell ticks on loc_a
        assert snap[0].location_dwell_ticks["loc_a"] == 10

    def test_end_of_day_location(self):
        ledger = _ledger_with([("a1", "loc_a")])
        rec = TickMetricsRecorder(ledger=ledger)
        rec.on_tick_end(_tick(0, 0))
        # Change location in ledger
        ledger.set_entity(EntityState(
            entity_id="a1", location_id="loc_b", position=Coord(x=0, y=0),
        ))
        rec.on_tick_end(_tick(0, 1))
        snap = rec.snapshot()
        assert snap[0].end_of_day_location_by_agent["a1"] == "loc_b"

    def test_distinct_pairs_canonical(self):
        ledger = _ledger_with([("a", "loc"), ("b", "loc")])
        rec = TickMetricsRecorder(ledger=ledger)
        # 两种顺序的相遇应去重
        rec.on_tick_end(_tick(0, 0, encounters=(
            EncounterCandidate(tick=0, agent_a="a", agent_b="b", shared_locations=("loc",)),
        )))
        rec.on_tick_end(_tick(0, 1, encounters=(
            EncounterCandidate(tick=1, agent_a="b", agent_b="a", shared_locations=("loc",)),
        )))
        snap = rec.snapshot()
        assert snap[0].distinct_encounter_pairs == 1

    def test_multi_day_rollup(self):
        ledger = _ledger_with([("a1", "loc")])
        rec = TickMetricsRecorder(ledger=ledger)
        rec.on_tick_end(_tick(0, 0))
        rec.on_tick_end(_tick(1, 0))
        rec.on_tick_end(_tick(2, 0))
        snap = rec.snapshot()
        assert [d.day_index for d in snap] == [0, 1, 2]

    def test_attention_service_none_ok(self):
        ledger = _ledger_with([("a1", "loc")])
        rec = TickMetricsRecorder(ledger=ledger, attention_service=None)
        rec.on_tick_end(_tick(0, 0))
        # does not crash
        assert rec.snapshot()[0].day_index == 0


class TestRecorderSnapshotRoundtrip:
    """Capability 1.11 — resume preserves run_metrics across cycles."""

    def test_empty_recorder_state(self):
        ledger = _ledger_with([("a1", "loc")])
        rec = TickMetricsRecorder(ledger=ledger)
        state = rec.to_snapshot_state()
        assert state == {"current_day": -1, "buckets": {}}

    def test_roundtrip_preserves_counters(self):
        ledger = _ledger_with([("a", "loc"), ("b", "loc")])
        rec1 = TickMetricsRecorder(ledger=ledger)
        rec1.on_tick_end(_tick(0, 0, encounters=(
            EncounterCandidate(tick=0, agent_a="a", agent_b="b", shared_locations=("loc",)),
        )))
        rec1.on_tick_end(_tick(0, 1, encounters=(
            EncounterCandidate(tick=1, agent_a="a", agent_b="b", shared_locations=("loc",)),
        )))
        rec1.on_tick_end(_tick(1, 0))
        state = rec1.to_snapshot_state()

        rec2 = TickMetricsRecorder(ledger=ledger)
        rec2.from_snapshot_state(state)
        snap1 = rec1.snapshot()
        snap2 = rec2.snapshot()
        assert [d.day_index for d in snap1] == [d.day_index for d in snap2]
        assert snap1[0].encounter_count_total == snap2[0].encounter_count_total
        assert snap1[0].distinct_encounter_pairs == snap2[0].distinct_encounter_pairs

    def test_restore_clears_existing_buckets(self):
        """from_snapshot_state SHALL clear before restoring (idempotent)."""
        ledger = _ledger_with([("a", "loc")])
        rec = TickMetricsRecorder(ledger=ledger)
        rec.on_tick_end(_tick(0, 0))
        rec.on_tick_end(_tick(0, 1))
        state = rec.to_snapshot_state()

        # Mutate, then restore
        rec.on_tick_end(_tick(5, 0))
        assert len(rec.snapshot()) == 2
        rec.from_snapshot_state(state)
        assert len(rec.snapshot()) == 1  # day 5 is gone
        assert rec.snapshot()[0].day_index == 0

    def test_distinct_pairs_set_survives_roundtrip(self):
        ledger = _ledger_with([("a", "l"), ("b", "l"), ("c", "l")])
        rec1 = TickMetricsRecorder(ledger=ledger)
        rec1.on_tick_end(_tick(0, 0, encounters=(
            EncounterCandidate(tick=0, agent_a="a", agent_b="b", shared_locations=("l",)),
            EncounterCandidate(tick=0, agent_a="b", agent_b="c", shared_locations=("l",)),
            EncounterCandidate(tick=0, agent_a="a", agent_b="b", shared_locations=("l",)),  # dup
        )))
        rec2 = TickMetricsRecorder(ledger=ledger)
        rec2.from_snapshot_state(rec1.to_snapshot_state())
        assert rec2.snapshot()[0].distinct_encounter_pairs == 2

    def test_resume_appends_to_existing_buckets(self):
        """harden-worker-resilience scenario: Worker A runs day 0-1,
        Worker B from_snapshot_state continues with day 2-3. Final
        snapshot() SHALL contain 4 day-summaries, not just the 2 from
        Worker B's session (backlog 1.11 — pre-fix this case lost the
        pre-resume days).
        """
        ledger = _ledger_with([("a1", "loc_a")])
        # Worker A
        rec_a = TickMetricsRecorder(ledger=ledger)
        rec_a.on_tick_end(_tick(0, 0))
        rec_a.on_tick_end(_tick(1, 0))
        state_a = rec_a.to_snapshot_state()
        assert len(rec_a.snapshot()) == 2

        # Worker B: fresh recorder + restore
        rec_b = TickMetricsRecorder(ledger=ledger)
        rec_b.from_snapshot_state(state_a)
        # B continues with day 2, 3
        rec_b.on_tick_end(_tick(2, 0))
        rec_b.on_tick_end(_tick(3, 0))
        summaries = rec_b.snapshot()
        # Final result spans all 4 days
        assert [s.day_index for s in summaries] == [0, 1, 2, 3]
