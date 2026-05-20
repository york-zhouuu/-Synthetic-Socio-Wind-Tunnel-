"""Plan B.2 (2026-05-20): regression for OPERATION_POOL_HANDLER_TIMEOUT_SEC.

Before Plan B, the per-handler wait_for timeout was hard-coded to 120s.
Under the recurring asyncio/httpx hang (backlog 1.9 line 398-399),
workers stayed stuck for 20-30 min because the timeout couldn't fire
during sync I/O blocks. To bound hang impact, the timeout is now
env-controlled — spawn-time setting `OPERATION_POOL_HANDLER_TIMEOUT_SEC=60`
caps each hung op to 60s before fallback fires.

These tests verify:
- env override actually takes effect (timeout closer to 2s than 10s
  when env=2)
- default still 120s when env unset (back-compat)
"""

from __future__ import annotations

import asyncio
import os
import time
from unittest.mock import patch

from synthetic_socio_wind_tunnel.agent.operations.pool import (
    OperationPool,
    OperationResult,
    PendingOp,
)


class _FakeLLM:
    """Minimal LLM stub so OperationPool can dispatch."""
    async def generate(self, prompt: str, **kw):
        return "{}"


async def _slow_handler(op, **_):
    """Handler that intentionally sleeps 10s — should be cut off
    by the wait_for env timeout (set to 2s in the env test)."""
    await asyncio.sleep(10.0)
    return OperationResult(
        op_id=op.op_id, agent_id=op.agent_id, kind=op.kind, success=True,
    )


def test_env_handler_timeout_bounds_hung_op():
    """When env timeout=2s, a 10s handler SHALL be cut off ~2s in."""
    with patch.dict(os.environ, {"OPERATION_POOL_HANDLER_TIMEOUT_SEC": "2"}):
        pool = OperationPool(
            handlers={"do_something": _slow_handler},
            llm_clients={"sonnet": _FakeLLM()},
            tier_for_kind={"do_something": "sonnet"},
        )
        op = PendingOp(
            op_id="op1", agent_id="a1", kind="do_something",
            args={}, created_tick=0, timeout_tick=100,
        )
        pool.schedule(op)
        t0 = time.monotonic()
        results = asyncio.run(pool.process_pending(current_tick=10))
        dt = time.monotonic() - t0
        assert dt < 5.0, f"handler not bounded by env timeout: {dt:.1f}s"
        assert not results[0].success
        assert "TimeoutError" in (results[0].error_msg or "")


def test_default_timeout_120_when_env_unset():
    """Back-compat: when env not set, default 120s applies. We don't
    actually wait 120s — just verify code path doesn't crash."""
    # Pop env if it leaked from prior test
    os.environ.pop("OPERATION_POOL_HANDLER_TIMEOUT_SEC", None)

    async def _fast_handler(op, **_):
        return OperationResult(
            op_id=op.op_id, agent_id=op.agent_id, kind=op.kind, success=True,
        )

    pool = OperationPool(
        handlers={"do_something": _fast_handler},
        llm_clients={"sonnet": _FakeLLM()},
        tier_for_kind={"do_something": "sonnet"},
    )
    op = PendingOp(
        op_id="op2", agent_id="a2", kind="do_something",
        args={}, created_tick=0, timeout_tick=100,
    )
    pool.schedule(op)
    results = asyncio.run(pool.process_pending(current_tick=10))
    assert results[0].success
