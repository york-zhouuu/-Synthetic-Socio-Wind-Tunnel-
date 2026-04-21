"""Determinism test — same seed / setup → same Ledger snapshot."""

from __future__ import annotations

import json
from datetime import datetime

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


def _build_simulation():
    region = (
        RegionBuilder("r", "r")
        .add_outdoor("a", "a", area_type="street")
        .polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        .end_outdoor()
        .add_outdoor("b", "b", area_type="street")
        .polygon([(15, 0), (25, 0), (25, 10), (15, 10)])
        .end_outdoor()
        .connect("a", "b", path_type="road", distance=5.0)
        .build()
    )
    atlas = Atlas(region)

    profiles = [
        ("alpha", "a", "b"),
        ("beta", "b", "a"),
        ("chen", "a", "b"),
    ]
    agents = []
    ledger = Ledger()
    ledger.current_time = datetime(2026, 4, 20, 7, 0, 0)
    for aid, home, dest in profiles:
        profile = AgentProfile(
            agent_id=aid, name=aid, age=30, occupation="x",
            household="single", home_location=home,
        )
        plan = DailyPlan(agent_id=aid, date="2026-04-20", steps=[
            PlanStep(time="7:00", action="move", destination=dest,
                     duration_minutes=60),
        ])
        agent = AgentRuntime(profile=profile, plan=plan, current_location=home)
        ledger.set_entity(EntityState(entity_id=aid, location_id=home,
                                       position=Coord(x=0, y=0)))
        agents.append(agent)
    return atlas, ledger, agents


def _snapshot(ledger: Ledger) -> str:
    """Produce a stable serialization for comparison."""
    # Just serialize entities since that's the main state we care about
    entities = sorted(
        (eid, state.location_id)
        for eid, state in ledger._data.entities.items()  # type: ignore[attr-defined]
    )
    return json.dumps(entities, sort_keys=True)


class TestDeterminism:

    def test_same_seed_same_ledger_snapshot(self):
        # Run 1
        atlas_1, ledger_1, agents_1 = _build_simulation()
        orch_1 = Orchestrator(atlas_1, ledger_1, agents_1, tick_minutes=60, seed=42)
        orch_1.run()
        snap_1 = _snapshot(ledger_1)

        # Run 2 — same setup
        atlas_2, ledger_2, agents_2 = _build_simulation()
        orch_2 = Orchestrator(atlas_2, ledger_2, agents_2, tick_minutes=60, seed=42)
        orch_2.run()
        snap_2 = _snapshot(ledger_2)

        assert snap_1 == snap_2

    def test_same_seed_same_summary(self):
        atlas_1, ledger_1, agents_1 = _build_simulation()
        orch_1 = Orchestrator(atlas_1, ledger_1, agents_1, tick_minutes=60, seed=42)
        summary_1 = orch_1.run()

        atlas_2, ledger_2, agents_2 = _build_simulation()
        orch_2 = Orchestrator(atlas_2, ledger_2, agents_2, tick_minutes=60, seed=42)
        summary_2 = orch_2.run()

        assert summary_1.total_commits_succeeded == summary_2.total_commits_succeeded
        assert summary_1.total_commits_failed == summary_2.total_commits_failed
        assert summary_1.total_encounters == summary_2.total_encounters
