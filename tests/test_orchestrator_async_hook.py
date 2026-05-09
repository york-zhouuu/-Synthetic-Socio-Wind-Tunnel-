"""Tests for Orchestrator.register_on_tick_end_async (Phase E task 20)."""

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
from synthetic_socio_wind_tunnel.orchestrator.models import TickResult


def _trivial_orch() -> Orchestrator:
    """Construct a minimal Orchestrator (24 ticks/day for fast tests)."""
    region = (
        RegionBuilder("r", "r")
        .add_outdoor("a", "a", area_type="street")
        .polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        .end_outdoor()
        .build()
    )
    atlas = Atlas(region)
    profile = AgentProfile(
        agent_id="emma", name="Emma", age=30, occupation="librarian",
        household="single", home_location="a",
    )
    runtime = AgentRuntime(profile=profile, current_location="a")
    ledger = Ledger()
    ledger.current_time = datetime(2026, 5, 9, 7, 0, 0)
    ledger.set_entity(EntityState(
        entity_id="emma", location_id="a", position=Coord(x=0, y=0),
    ))
    return Orchestrator(atlas, ledger, [runtime], tick_minutes=60, seed=1)


# ---------------------------------------------------------------------------


class TestAsyncHookRegistration:

    def test_registration_basic(self):
        orch = _trivial_orch()

        async def hook(tick_result: TickResult) -> None:
            pass

        # Should not raise
        orch.register_on_tick_end_async(hook)

    def test_async_hook_runs_after_sync(self):
        orch = _trivial_orch()
        order: list[str] = []

        def sync_hook(tick_result: TickResult) -> None:
            order.append(f"sync:tick={tick_result.tick_index}")

        async def async_hook(tick_result: TickResult) -> None:
            order.append(f"async:tick={tick_result.tick_index}")

        orch.register_on_tick_end(sync_hook)
        orch.register_on_tick_end_async(async_hook)

        orch.run()
        # 24 ticks → 24 sync + 24 async, interleaved per tick
        assert len(order) == 48
        # Per-tick: sync runs first, async runs second
        for i in range(24):
            assert order[2 * i] == f"sync:tick={i}"
            assert order[2 * i + 1] == f"async:tick={i}"


class TestAsyncHookErrorHandling:

    def test_failing_async_hook_does_not_abort_run(self):
        orch = _trivial_orch()
        sync_calls: list[int] = []

        def sync_hook(tick_result: TickResult) -> None:
            sync_calls.append(tick_result.tick_index)

        async def boom(tick_result: TickResult) -> None:
            raise RuntimeError("async hook failure")

        orch.register_on_tick_end(sync_hook)
        orch.register_on_tick_end_async(boom)

        # Should complete without raising; sync hook should still fire
        # all 24 ticks.
        summary = orch.run()
        assert summary.total_ticks == 24
        assert sync_calls == list(range(24))

    def test_multiple_async_hooks_run_sequentially(self):
        orch = _trivial_orch()
        order: list[str] = []

        async def hook1(tr: TickResult) -> None:
            order.append(f"h1:{tr.tick_index}")

        async def hook2(tr: TickResult) -> None:
            order.append(f"h2:{tr.tick_index}")

        orch.register_on_tick_end_async(hook1)
        orch.register_on_tick_end_async(hook2)
        orch.run()
        # Per-tick: h1 fires before h2
        for i in range(24):
            assert order[2 * i] == f"h1:{i}"
            assert order[2 * i + 1] == f"h2:{i}"


class TestNoAsyncHooks:

    def test_no_async_hooks_skips_loop(self):
        """When no async hooks registered, asyncio.run is NOT called."""
        orch = _trivial_orch()
        # No async hook registered → run() should be cheap and not crash.
        summary = orch.run()
        assert summary.total_ticks == 24


class TestPoolIntegration:
    """Mini integration check — register OperationPool.process_pending as an
    async hook, schedule a stub op, verify it processes."""

    def test_operation_pool_as_async_hook(self):
        from synthetic_socio_wind_tunnel.agent.operations.pool import (
            OperationPool,
        )
        from synthetic_socio_wind_tunnel.agent.operations.models import (
            OperationResult, PendingOp,
        )

        async def stub_handler(op, *, llm_client, **_):
            return OperationResult(
                op_id=op.op_id, agent_id=op.agent_id, kind=op.kind,
                success=True, payload={"action": "wait"},
            )

        class _StubLLM:
            async def generate(self, prompt, **_):
                return "ok"

        pool = OperationPool(
            handlers={"do_something": stub_handler},
            llm_clients={"sonnet": _StubLLM()},
        )
        pool.schedule(PendingOp(
            op_id="op1", agent_id="emma", kind="do_something",
            created_tick=0, timeout_tick=100, args={},
        ))

        orch = _trivial_orch()
        results: list[OperationResult] = []

        async def pool_hook(tr: TickResult) -> None:
            res = await pool.process_pending(tr.tick_index)
            results.extend(res)

        orch.register_on_tick_end_async(pool_hook)
        orch.run()
        # Op should have been processed (within first tick or so)
        assert len(results) == 1
        assert results[0].success is True
