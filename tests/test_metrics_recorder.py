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
