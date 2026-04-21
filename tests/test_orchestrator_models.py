"""Tests for orchestrator data models (frozen dataclasses)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from synthetic_socio_wind_tunnel.agent.intent import MoveIntent
from synthetic_socio_wind_tunnel.engine.simulation import SimulationResult
from synthetic_socio_wind_tunnel.orchestrator.models import (
    CommitRecord,
    EncounterCandidate,
    SimulationContext,
    SimulationSummary,
    TickContext,
    TickMovementTrace,
    TickResult,
)


class TestTickContext:

    def test_can_construct_without_observer(self):
        ctx = TickContext(tick_index=0, simulated_time=datetime(2026, 4, 20, 7, 0))
        assert ctx.observer_context is None
        assert ctx.tick_index == 0

    def test_frozen(self):
        ctx = TickContext(tick_index=0, simulated_time=datetime.now())
        with pytest.raises(FrozenInstanceError):
            ctx.tick_index = 5  # type: ignore


class TestEncounterCandidate:

    def test_construct(self):
        e = EncounterCandidate(
            tick=3, agent_a="alpha", agent_b="beta",
            shared_locations=("street_1", "street_2"),
        )
        assert e.tick == 3
        assert e.agent_a < e.agent_b
        assert e.shared_locations == ("street_1", "street_2")

    def test_hashable(self):
        e = EncounterCandidate(tick=1, agent_a="a", agent_b="b",
                               shared_locations=("x",))
        assert {e, e} == {e}


class TestTickMovementTrace:

    def test_extend_returns_new(self):
        t = TickMovementTrace(locations=("a", "b"))
        t2 = t.extend("c")
        assert t.locations == ("a", "b")  # original untouched
        assert t2.locations == ("a", "b", "c")

    def test_empty(self):
        t = TickMovementTrace(locations=())
        assert t.locations == ()


class TestTickResult:

    def test_tick_result_contains_commits_and_encounters(self):
        commit = CommitRecord(
            agent_id="alpha",
            intent=MoveIntent(to_location="cafe_a"),
            result=SimulationResult.ok(),
        )
        encounter = EncounterCandidate(
            tick=1, agent_a="alpha", agent_b="beta", shared_locations=("street_1",)
        )
        r = TickResult(
            tick_index=1,
            simulated_time=datetime(2026, 4, 20, 7, 5),
            commits=(commit,),
            encounter_candidates=(encounter,),
        )
        assert r.commits[0].agent_id == "alpha"
        assert r.encounter_candidates[0].agent_a == "alpha"


class TestSimulationSummary:

    def test_summary_fields(self):
        s = SimulationSummary(
            total_ticks=288,
            total_encounters=12,
            total_commits_succeeded=1000,
            total_commits_failed=5,
            seed=42,
            started_at=datetime(2026, 4, 20, 7, 0),
            ended_at=datetime(2026, 4, 20, 7, 30),
        )
        assert s.total_ticks == 288
        assert s.total_commits_succeeded == 1000


class TestSimulationContext:

    def test_context_has_tick_math(self):
        c = SimulationContext(
            num_days=1,
            ticks_per_day=288,
            tick_minutes=5,
            seed=0,
            agent_ids=("alpha", "beta"),
            started_at=datetime.now(),
        )
        assert c.ticks_per_day * c.tick_minutes == 1440
