"""Tests for TickMetricsRecorder ↔ SocialGraphService integration."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.metrics.recorder import TickMetricsRecorder
from synthetic_socio_wind_tunnel.orchestrator.models import EncounterCandidate, TickResult
from synthetic_socio_wind_tunnel.social_graph import SocialGraphService


def _ledger_with_agents(agent_ids: list[str]) -> Ledger:
    led = Ledger()
    led.current_time = datetime(2026, 5, 5)
    for aid in agent_ids:
        led.set_entity(EntityState(
            entity_id=aid, position=Coord(x=0, y=0), location_id="home",
        ))
    return led


def _tick(tick: int, day: int, encounters: list[tuple[str, str]] = ()) -> TickResult:
    return TickResult(
        tick_index=tick,
        day_index=day,
        simulated_time=datetime(2026, 5, 5),
        commits=(),
        encounter_candidates=tuple(
            EncounterCandidate(
                agent_a=a, agent_b=b, shared_locations=("cafe",), tick=tick,
            )
            for a, b in encounters
        ),
    )


class TestSocialGraphInRecorder:

    def test_no_graph_keeps_fields_none(self):
        led = _ledger_with_agents(["emma", "linda"])
        rec = TickMetricsRecorder(ledger=led, social_graph=None)
        rec.on_tick_end(_tick(0, 0, [("emma", "linda")]))
        snap = rec.snapshot()
        assert len(snap) == 1
        d = snap[0]
        assert d.tie_count_total is None
        assert d.tie_count_weak is None
        assert d.tie_count_strong is None
        assert d.new_ties_today is None
        assert d.avg_ties_per_agent is None

    def test_graph_injection_fills_fields(self):
        led = _ledger_with_agents(["emma", "linda"])
        graph = SocialGraphService(K=10)
        rec = TickMetricsRecorder(ledger=led, social_graph=graph)

        # Simulate 2 ticks with the encounter pair
        # (recorder doesn't auto-record into graph — production path is via
        # MemoryService; here test the SNAPSHOT semantics by manually populating)
        for tick in range(2):
            graph.record_encounter("emma", "linda", tick=tick, day_index=0)
            rec.on_tick_end(_tick(tick, 0, [("emma", "linda")]))

        snap = rec.snapshot()
        assert len(snap) == 1
        d = snap[0]
        assert d.tie_count_total == 1  # 1 unique pair
        assert d.tie_count_weak == 1   # strength 0.167 ∈ [0.1, 0.5)
        assert d.tie_count_strong == 0
        assert d.new_ties_today == 1   # first_seen_day == 0
        assert d.avg_ties_per_agent == pytest.approx(1.0)

    def test_strong_tie_after_threshold(self):
        led = _ledger_with_agents(["emma", "linda"])
        graph = SocialGraphService(K=10)
        rec = TickMetricsRecorder(ledger=led, social_graph=graph)

        # 10 encounters → strength 0.500 ≥ 0.5 → strong tie
        for tick in range(10):
            graph.record_encounter("emma", "linda", tick=tick, day_index=0)
            rec.on_tick_end(_tick(tick, 0, [("emma", "linda")]))

        snap = rec.snapshot()
        assert snap[0].tie_count_strong == 1
        assert snap[0].tie_count_weak == 0


class TestRunMetricsFactory:

    def test_weak_tie_formation_count_filled_when_graph_present(self):
        from synthetic_socio_wind_tunnel.metrics.factory import build_run_metrics
        from synthetic_socio_wind_tunnel.orchestrator.multi_day import MultiDayResult

        led = _ledger_with_agents(["emma", "linda", "john"])
        graph = SocialGraphService(K=10)
        # 3 weak ties + 1 strong tie
        for tick in range(3):  graph.record_encounter("emma", "linda", tick)  # weak
        for tick in range(4):  graph.record_encounter("emma", "john", tick + 100)  # weak
        for tick in range(5):  graph.record_encounter("linda", "john", tick + 200)  # weak
        for tick in range(15): graph.record_encounter("emma", "alex", tick + 300)  # strong

        rec = TickMetricsRecorder(ledger=led, social_graph=graph)
        rec.on_tick_end(_tick(0, 0))

        mdr = MagicMock()
        mdr.seed = 42

        rm = build_run_metrics(rec, multi_day_result=mdr)
        assert rm.weak_tie_formation_count == 3  # exclude the 1 strong tie

    def test_weak_tie_formation_count_none_when_no_graph(self):
        from synthetic_socio_wind_tunnel.metrics.factory import build_run_metrics

        led = _ledger_with_agents(["emma"])
        rec = TickMetricsRecorder(ledger=led, social_graph=None)
        rec.on_tick_end(_tick(0, 0))

        mdr = MagicMock()
        mdr.seed = 42

        rm = build_run_metrics(rec, multi_day_result=mdr)
        assert rm.weak_tie_formation_count is None
