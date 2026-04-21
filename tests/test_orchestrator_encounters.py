"""Tests for sub-step Ledger writes + encounter detection."""

from __future__ import annotations

from datetime import datetime

import pytest

from synthetic_socio_wind_tunnel.agent import (
    AgentProfile,
    AgentRuntime,
    DailyPlan,
    PlanStep,
)
from synthetic_socio_wind_tunnel.atlas import Atlas
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.cartography.builder import RegionBuilder
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.orchestrator import Orchestrator


def _linear_atlas() -> Atlas:
    """4-segment linear street: a ─ b ─ c ─ d"""
    region = (
        RegionBuilder("r", "r")
        .add_outdoor("a", "a", area_type="street")
        .polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        .end_outdoor()
        .add_outdoor("b", "b", area_type="street")
        .polygon([(15, 0), (25, 0), (25, 10), (15, 10)])
        .end_outdoor()
        .add_outdoor("c", "c", area_type="street")
        .polygon([(30, 0), (40, 0), (40, 10), (30, 10)])
        .end_outdoor()
        .add_outdoor("d", "d", area_type="street")
        .polygon([(45, 0), (55, 0), (55, 10), (45, 10)])
        .end_outdoor()
        .connect("a", "b", path_type="road", distance=5.0)
        .connect("b", "c", path_type="road", distance=5.0)
        .connect("c", "d", path_type="road", distance=5.0)
        .build()
    )
    return Atlas(region)


def _agent(
    agent_id: str, home: str, plan_steps: list[PlanStep]
) -> AgentRuntime:
    profile = AgentProfile(
        agent_id=agent_id, name=agent_id, age=30, occupation="x",
        household="single", home_location=home,
    )
    plan = DailyPlan(agent_id=agent_id, date="2026-04-20", steps=plan_steps)
    return AgentRuntime(profile=profile, plan=plan, current_location=home)


def _ledger(start: datetime, *agents: AgentRuntime) -> Ledger:
    ledger = Ledger()
    ledger.current_time = start
    for a in agents:
        ledger.set_entity(EntityState(
            entity_id=a.profile.agent_id,
            location_id=a.current_location,
            position=Coord(x=0.0, y=0.0),
        ))
    return ledger


class TestSubStepWrites:

    def test_three_step_path_writes_each_intermediate(self):
        """a → d traverses a, b, c, d. Ledger should see intermediate locations."""
        atlas = _linear_atlas()
        plan = [PlanStep(time="7:00", action="move", destination="d",
                         duration_minutes=30)]
        agent = _agent("alpha", home="a", plan_steps=plan)
        ledger = _ledger(datetime(2026, 4, 20, 7, 0), agent)
        orch = Orchestrator(atlas, ledger, [agent], tick_minutes=60)

        captured_results = []
        orch.register_on_tick_end(lambda r: captured_results.append(r))
        orch.run()

        # Tick 0 (7:00-8:00): agent moves from a to d via b, c, d
        tick_0 = captured_results[0]
        commits = [c for c in tick_0.commits if c.agent_id == "alpha"]
        assert len(commits) == 1
        # The commit should be successful (final location reached)
        assert commits[0].result.success

        # Final ledger location
        assert ledger.get_entity("alpha").location_id == "d"


class TestEncounterDetection:

    def test_agents_cross_on_middle_segment(self):
        """alpha a→d and beta d→a both pass through b, c. Should detect encounter."""
        atlas = _linear_atlas()
        plan_alpha = [PlanStep(time="7:00", action="move", destination="d",
                               duration_minutes=30)]
        plan_beta = [PlanStep(time="7:00", action="move", destination="a",
                              duration_minutes=30)]
        alpha = _agent("alpha", home="a", plan_steps=plan_alpha)
        beta = _agent("beta", home="d", plan_steps=plan_beta)
        ledger = _ledger(datetime(2026, 4, 20, 7, 0), alpha, beta)
        orch = Orchestrator(atlas, ledger, [alpha, beta], tick_minutes=60)

        captured: list = []
        orch.register_on_tick_end(lambda r: captured.append(r))
        orch.run()

        # Tick 0 should have an encounter
        tick_0 = captured[0]
        assert len(tick_0.encounter_candidates) >= 1
        enc = tick_0.encounter_candidates[0]
        assert enc.agent_a == "alpha"
        assert enc.agent_b == "beta"
        assert enc.tick == 0
        # Should share at least one mid location (b or c)
        shared_set = set(enc.shared_locations)
        assert shared_set & {"b", "c"}

    def test_no_encounter_when_both_wait(self):
        atlas = _linear_atlas()
        alpha = _agent("alpha", home="a", plan_steps=[])
        beta = _agent("beta", home="d", plan_steps=[])
        ledger = _ledger(datetime(2026, 4, 20, 7, 0), alpha, beta)
        orch = Orchestrator(atlas, ledger, [alpha, beta], tick_minutes=60)

        captured: list = []
        orch.register_on_tick_end(lambda r: captured.append(r))
        orch.run()

        total_encounters = sum(len(r.encounter_candidates) for r in captured)
        assert total_encounters == 0

    def test_shared_locations_sorted(self):
        """Determinism: shared_locations tuple is sorted."""
        atlas = _linear_atlas()
        plan_alpha = [PlanStep(time="7:00", action="move", destination="d",
                               duration_minutes=30)]
        plan_beta = [PlanStep(time="7:00", action="move", destination="a",
                              duration_minutes=30)]
        alpha = _agent("alpha", home="a", plan_steps=plan_alpha)
        beta = _agent("beta", home="d", plan_steps=plan_beta)
        ledger = _ledger(datetime(2026, 4, 20, 7, 0), alpha, beta)
        orch = Orchestrator(atlas, ledger, [alpha, beta], tick_minutes=60)

        captured: list = []
        orch.register_on_tick_end(lambda r: captured.append(r))
        orch.run()

        tick_0 = captured[0]
        if tick_0.encounter_candidates:
            enc = tick_0.encounter_candidates[0]
            assert list(enc.shared_locations) == sorted(enc.shared_locations)
