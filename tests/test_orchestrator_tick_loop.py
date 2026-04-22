"""Integration tests for Orchestrator.run — tick loop, dispatch, timing."""

from __future__ import annotations

from datetime import datetime, timedelta

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


def _small_atlas() -> Atlas:
    region = (
        RegionBuilder("r", "r")
        .add_outdoor("street_a", "Street A", area_type="street")
        .polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        .end_outdoor()
        .add_outdoor("street_b", "Street B", area_type="street")
        .polygon([(15, 0), (25, 0), (25, 10), (15, 10)])
        .end_outdoor()
        .add_outdoor("street_c", "Street C", area_type="street")
        .polygon([(30, 0), (40, 0), (40, 10), (30, 10)])
        .end_outdoor()
        .connect("street_a", "street_b", path_type="road", distance=5.0)
        .connect("street_b", "street_c", path_type="road", distance=5.0)
        .build()
    )
    return Atlas(region)


def _agent(
    agent_id: str, home: str = "street_a", plan_steps: list[PlanStep] | None = None
) -> AgentRuntime:
    profile = AgentProfile(
        agent_id=agent_id, name=agent_id, age=30, occupation="x",
        household="single", home_location=home,
    )
    plan = None
    if plan_steps is not None:
        plan = DailyPlan(agent_id=agent_id, date="2026-04-20", steps=plan_steps)
    return AgentRuntime(profile=profile, plan=plan, current_location=home)


def _ledger_with_agents(*agents: AgentRuntime, start_time: datetime | None = None) -> Ledger:
    ledger = Ledger()
    ledger.current_time = start_time or datetime(2026, 4, 20, 7, 0, 0)
    for a in agents:
        ledger.set_entity(EntityState(
            entity_id=a.profile.agent_id,
            location_id=a.current_location,
            position=Coord(x=0.0, y=0.0),
        ))
    return ledger


class TestConstruction:

    def test_multi_day_rejected(self):
        """Orchestrator.run() 单日语义；多日走 MultiDayRunner。"""
        atlas = _small_atlas()
        agent = _agent("alpha")
        ledger = _ledger_with_agents(agent)
        with pytest.raises(ValueError) as exc:
            Orchestrator(atlas, ledger, [agent], num_days=2)
        assert "MultiDayRunner" in str(exc.value)

    def test_negative_num_days_rejected(self):
        atlas = _small_atlas()
        agent = _agent("alpha")
        ledger = _ledger_with_agents(agent)
        with pytest.raises(ValueError):
            Orchestrator(atlas, ledger, [agent], num_days=0)

    def test_tick_minutes_must_divide_1440(self):
        atlas = _small_atlas()
        agent = _agent("alpha")
        ledger = _ledger_with_agents(agent)
        with pytest.raises(ValueError):
            Orchestrator(atlas, ledger, [agent], tick_minutes=7)  # 1440 % 7 != 0

    def test_tick_minutes_must_be_positive(self):
        atlas = _small_atlas()
        agent = _agent("alpha")
        ledger = _ledger_with_agents(agent)
        with pytest.raises(ValueError):
            Orchestrator(atlas, ledger, [agent], tick_minutes=0)

    def test_default_tick_minutes_5(self):
        atlas = _small_atlas()
        agent = _agent("alpha")
        ledger = _ledger_with_agents(agent)
        orch = Orchestrator(atlas, ledger, [agent])
        assert orch._ticks_per_day == 288

    def test_tick_minutes_10_gives_144(self):
        atlas = _small_atlas()
        agent = _agent("alpha")
        ledger = _ledger_with_agents(agent)
        orch = Orchestrator(atlas, ledger, [agent], tick_minutes=10)
        assert orch._ticks_per_day == 144


class TestRun:

    def test_single_agent_wait_for_full_day(self):
        """Agent with no plan → WaitIntent every tick, no errors."""
        atlas = _small_atlas()
        agent = _agent("alpha")  # no plan
        ledger = _ledger_with_agents(agent)
        orch = Orchestrator(atlas, ledger, [agent])

        summary = orch.run()

        assert summary.total_ticks == 288
        # All WaitIntents commit; no failures
        assert summary.total_commits_succeeded == 288
        assert summary.total_commits_failed == 0
        # Ledger time advanced 24h
        assert ledger.current_time == datetime(2026, 4, 21, 7, 0, 0)

    def test_move_intent_eventually_arrives(self):
        atlas = _small_atlas()
        plan_steps = [
            PlanStep(time="7:00", action="move", destination="street_c",
                     duration_minutes=60),
        ]
        agent = _agent("alpha", home="street_a", plan_steps=plan_steps)
        ledger = _ledger_with_agents(agent)
        orch = Orchestrator(atlas, ledger, [agent])

        summary = orch.run()

        # After any amount of ticks, agent should be at street_c
        final = ledger.get_entity("alpha")
        assert final.location_id == "street_c"
        assert summary.total_ticks == 288


class TestDispatch:

    def test_wait_intent_no_simulation_event(self):
        atlas = _small_atlas()
        agent = _agent("alpha")  # no plan → WaitIntent
        ledger = _ledger_with_agents(agent)
        pre_event_count = len(ledger.get_recent_events(limit=100))
        orch = Orchestrator(atlas, ledger, [agent], tick_minutes=60)  # just 24 ticks
        orch.run()

        # WaitIntents shouldn't have generated move/door events
        events_after = ledger.get_recent_events(limit=100)
        for ev in events_after:
            assert "move_entity" not in ev.get("type", "")


class TestHookLifecycle:

    def test_all_hooks_fire(self):
        atlas = _small_atlas()
        agent = _agent("alpha")
        ledger = _ledger_with_agents(agent)
        orch = Orchestrator(atlas, ledger, [agent], tick_minutes=60)

        start_calls: list = []
        tick_start_calls: list = []
        tick_end_calls: list = []
        end_calls: list = []

        orch.register_on_simulation_start(lambda c: start_calls.append(c))
        orch.register_on_tick_start(lambda c: tick_start_calls.append(c))
        orch.register_on_tick_end(lambda r: tick_end_calls.append(r))
        orch.register_on_simulation_end(lambda s: end_calls.append(s))

        orch.run()

        assert len(start_calls) == 1
        assert len(tick_start_calls) == 24
        assert len(tick_end_calls) == 24
        assert len(end_calls) == 1
