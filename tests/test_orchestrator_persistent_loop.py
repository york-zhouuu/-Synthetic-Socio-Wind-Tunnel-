"""H3 (2026-05-21): Orchestrator uses single persistent asyncio loop.

The 2026-05-20 hang root-cause hypothesis is per-tick `asyncio.run()`
creating fresh event loops that corrupt httpx.AsyncClient's
internal asyncio primitives (Lock, Semaphore) bound to the
first-use loop. Fix: persistent loop reused across all ticks.

Tests verify:
- N tick_end calls SHALL use the SAME loop instance
- No async hooks → no loop created
- Loop closed on simulation_end
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime

from synthetic_socio_wind_tunnel.agent import AgentProfile, AgentRuntime
from synthetic_socio_wind_tunnel.atlas import Atlas
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.cartography.builder import RegionBuilder
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.orchestrator import Orchestrator


def _small_atlas() -> Atlas:
    region = (
        RegionBuilder("r", "r")
        .add_outdoor("a", "A", area_type="street")
        .polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        .end_outdoor()
        .add_outdoor("b", "B", area_type="street")
        .polygon([(15, 0), (25, 0), (25, 10), (15, 10)])
        .end_outdoor()
        .connect("a", "b", path_type="road", distance=5.0)
        .build()
    )
    return Atlas(region)


def _make_orch():
    atlas = _small_atlas()
    ledger = Ledger()
    ledger.current_time = datetime.combine(date(2026, 4, 22), datetime.min.time())
    profile = AgentProfile(
        agent_id="alpha", name="alpha", age=30, occupation="x",
        household="single", home_location="a",
    )
    agent = AgentRuntime(profile=profile, current_location="a")
    ledger.set_entity(EntityState(
        entity_id=agent.profile.agent_id,
        location_id="a",
        position=Coord(x=0.0, y=0.0),
    ))
    return Orchestrator(atlas, ledger, [agent])


def test_async_hook_uses_persistent_loop():
    """N async hook invocations SHALL reuse the same loop instance."""
    orch = _make_orch()
    seen_loops: list = []

    async def _hook(tick_result):
        # Capture the running loop
        seen_loops.append(asyncio.get_running_loop())

    orch.register_on_tick_end_async(_hook)
    orch.run(day_index=0)
    # Should have at least 1 tick's worth of loops; all same instance
    assert len(seen_loops) >= 1
    first = seen_loops[0]
    for loop in seen_loops[1:]:
        assert loop is first, (
            f"Expected persistent loop reuse; got new loop at iter {seen_loops.index(loop)}"
        )


def test_no_async_hook_no_loop_created():
    """If no async hooks registered, no persistent loop should exist."""
    orch = _make_orch()
    # No async hook registered
    orch.run(day_index=0)
    # _persistent_loop attribute either absent or None
    loop = getattr(orch, "_persistent_loop", None)
    assert loop is None, (
        f"No async hooks → no loop should be created; got {loop}"
    )


def test_loop_closed_on_simulation_end():
    """When sim ends, the persistent loop SHALL be closed."""
    orch = _make_orch()
    async def _hook(tick_result):
        pass
    orch.register_on_tick_end_async(_hook)
    orch.run(day_index=0)
    loop = getattr(orch, "_persistent_loop", None)
    # Either loop is None (cleanup nulled it) or it's closed
    if loop is not None:
        assert loop.is_closed(), (
            "Persistent loop SHALL be closed after on_simulation_end"
        )


def test_legacy_no_async_hook_still_runs():
    """Sync-only orchestrator (no async hooks) SHALL still work — no regression."""
    orch = _make_orch()
    sync_called = []
    orch.register_on_tick_end(lambda tr: sync_called.append(tr))
    summary = orch.run(day_index=0)
    assert summary.total_ticks > 0
    assert len(sync_called) > 0
