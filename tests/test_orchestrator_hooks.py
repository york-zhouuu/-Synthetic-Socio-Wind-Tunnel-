"""Tests for orchestrator hook registry."""

from __future__ import annotations

from datetime import datetime

import pytest

from synthetic_socio_wind_tunnel.agent import AgentProfile, AgentRuntime
from synthetic_socio_wind_tunnel.atlas import Atlas
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.cartography.builder import RegionBuilder
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.orchestrator import Orchestrator


def _minimal_setup():
    region = (
        RegionBuilder("r", "r")
        .add_outdoor("a", "a", area_type="street")
        .polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        .end_outdoor()
        .build()
    )
    atlas = Atlas(region)
    profile = AgentProfile(
        agent_id="alpha", name="alpha", age=30, occupation="x",
        household="single", home_location="a",
    )
    agent = AgentRuntime(profile=profile, current_location="a")
    ledger = Ledger()
    ledger.current_time = datetime(2026, 4, 20, 7, 0, 0)
    ledger.set_entity(EntityState(entity_id="alpha", location_id="a",
                                   position=Coord(x=0, y=0)))
    return atlas, ledger, agent


class TestMultipleCallbacksOrdering:

    def test_callbacks_fire_in_registration_order(self):
        atlas, ledger, agent = _minimal_setup()
        orch = Orchestrator(atlas, ledger, [agent], tick_minutes=60)

        call_order: list[str] = []
        orch.register_on_tick_end(lambda r: call_order.append(f"a_{r.tick_index}"))
        orch.register_on_tick_end(lambda r: call_order.append(f"b_{r.tick_index}"))

        orch.run()

        # For each tick we see a then b
        for i in range(0, len(call_order), 2):
            assert call_order[i].startswith("a_")
            assert call_order[i + 1].startswith("b_")


class TestHookException:

    def test_exception_in_tick_end_propagates(self):
        atlas, ledger, agent = _minimal_setup()
        orch = Orchestrator(atlas, ledger, [agent], tick_minutes=60)

        def boom(_r):
            raise RuntimeError("boom")

        orch.register_on_tick_end(boom)

        with pytest.raises(RuntimeError, match="boom"):
            orch.run()

    def test_exception_in_tick_start_propagates(self):
        atlas, ledger, agent = _minimal_setup()
        orch = Orchestrator(atlas, ledger, [agent], tick_minutes=60)

        def boom(_c):
            raise ValueError("tick_start exploded")

        orch.register_on_tick_start(boom)

        with pytest.raises(ValueError, match="tick_start exploded"):
            orch.run()

    def test_exception_in_sim_start_propagates(self):
        atlas, ledger, agent = _minimal_setup()
        orch = Orchestrator(atlas, ledger, [agent], tick_minutes=60)

        orch.register_on_simulation_start(lambda c: (_ for _ in ()).throw(RuntimeError("nope")))

        with pytest.raises(RuntimeError):
            orch.run()
