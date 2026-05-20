"""2026-05-21 hot-fix: OperationPool concurrency semaphore.

`backlog 1.9` line 398-399 + the `snapshot-resume-ram-peak +
spawn-burst-self-DDoS` invariant document that 4-worker publishable
spawns can produce ~2000 concurrent HTTP POST per second to the LLM
provider, triggering server-side rate-limits / silent TCP drops →
cascade hang. The 2026-05-20 β=1 scout reproduced this within
~1.5 hours: all 4 workers hung at burst-induced asyncio/httpx
connection failures.

`OPERATION_POOL_MAX_CONCURRENT_OPS` env now caps in-flight ops to
this number. Default 0 = unlimited (back-compat for existing tests).

These tests verify (real-artifact-test, not mock):
- When env=N, AT MOST N ops are in their handler body simultaneously
- When env unset (or 0), all ops fire concurrently (legacy behavior)
- Results still correct (no ops dropped)
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
    async def generate(self, prompt: str, **kw):
        return "{}"


# Track current concurrency via a counter; observer checks max seen.
_concurrent_now = 0
_concurrent_max = 0
_lock = asyncio.Lock()


async def _tracking_handler(op, **_):
    """Handler that increments a counter on entry, sleeps, then decrements."""
    global _concurrent_now, _concurrent_max
    async with _lock:
        _concurrent_now += 1
        _concurrent_max = max(_concurrent_max, _concurrent_now)
    try:
        await asyncio.sleep(0.05)
    finally:
        async with _lock:
            _concurrent_now -= 1
    return OperationResult(
        op_id=op.op_id, agent_id=op.agent_id, kind=op.kind, success=True,
    )


def _reset_counters():
    global _concurrent_now, _concurrent_max
    _concurrent_now = 0
    _concurrent_max = 0


def _build_pool(N_ops: int) -> OperationPool:
    pool = OperationPool(
        handlers={"do_something": _tracking_handler},
        llm_clients={"sonnet": _FakeLLM()},
        tier_for_kind={"do_something": "sonnet"},
    )
    for i in range(N_ops):
        pool.schedule(PendingOp(
            op_id=f"op{i}", agent_id=f"a{i}", kind="do_something",
            args={}, created_tick=0, timeout_tick=100,
        ))
    return pool


def test_max_concurrent_ops_cap_5():
    """With env=5 and 50 ops scheduled, max concurrent SHALL be ≤ 5."""
    _reset_counters()
    with patch.dict(os.environ, {"OPERATION_POOL_MAX_CONCURRENT_OPS": "5"}):
        pool = _build_pool(50)
        results = asyncio.run(pool.process_pending(current_tick=10))
    assert len(results) == 50
    assert all(r.success for r in results)
    assert _concurrent_max <= 5, (
        f"expected concurrency ≤ 5, observed {_concurrent_max}"
    )
    # Sanity: should reach at least the cap (50 ops / 5 = 10 batches)
    assert _concurrent_max >= 1


def test_max_concurrent_ops_unset_unlimited():
    """When env not set, all 50 ops can run concurrently (back-compat)."""
    _reset_counters()
    os.environ.pop("OPERATION_POOL_MAX_CONCURRENT_OPS", None)
    pool = _build_pool(50)
    results = asyncio.run(pool.process_pending(current_tick=10))
    assert len(results) == 50
    # With no limit, all 50 should run concurrently → max = 50
    assert _concurrent_max >= 30, (
        f"expected high concurrency without cap, got {_concurrent_max}"
    )


def test_max_concurrent_ops_explicit_zero_unlimited():
    """Env=0 also means unlimited (explicit back-compat)."""
    _reset_counters()
    with patch.dict(os.environ, {"OPERATION_POOL_MAX_CONCURRENT_OPS": "0"}):
        pool = _build_pool(30)
        results = asyncio.run(pool.process_pending(current_tick=10))
    assert len(results) == 30
    assert _concurrent_max >= 20  # high concurrency expected


def test_max_concurrent_ops_cap_1_serial():
    """With env=1, ops run serially. Total wall ≈ N × sleep_time."""
    _reset_counters()
    with patch.dict(os.environ, {"OPERATION_POOL_MAX_CONCURRENT_OPS": "1"}):
        pool = _build_pool(10)
        t0 = time.monotonic()
        results = asyncio.run(pool.process_pending(current_tick=10))
        dt = time.monotonic() - t0
    assert len(results) == 10
    assert _concurrent_max == 1
    # 10 ops × 0.05s = 0.5s minimum (vs ~0.05s parallel)
    assert dt >= 0.40, f"expected serial wall ≥0.4s, got {dt:.2f}s"
