"""Tests for OperationPool (agent-stack-aitown-port Phase A)."""

from __future__ import annotations

import asyncio

import pytest

from synthetic_socio_wind_tunnel.agent.operations import (
    ConcurrentOperationError,
    OperationPool,
    OperationResult,
    PendingOp,
)


# --- Test stubs ---------------------------------------------------------


class _StubLLM:
    def __init__(self, name: str = "stub") -> None:
        self.name = name
        self.calls: list[str] = []

    async def generate(self, prompt: str, *, model: str = "", **kw) -> str:
        self.calls.append(prompt)
        return f"[{self.name}]:{prompt[:20]}"


async def _success_handler(op: PendingOp, *, llm_client, **kw) -> OperationResult:
    text = await llm_client.generate(f"hello {op.agent_id}")
    return OperationResult(
        op_id=op.op_id, agent_id=op.agent_id, kind=op.kind,
        success=True,
        payload={"text": text},
        prompt_tokens=10, completion_tokens=5, model=getattr(llm_client, "name", ""),
    )


async def _failure_handler(op: PendingOp, *, llm_client, **kw) -> OperationResult:
    return OperationResult(
        op_id=op.op_id, agent_id=op.agent_id, kind=op.kind,
        success=False, error_msg="forced failure",
    )


async def _raising_handler(op: PendingOp, *, llm_client, **kw) -> OperationResult:
    raise RuntimeError("handler crashed")


async def _slow_handler(op: PendingOp, *, llm_client, delay: float = 0.05, **kw) -> OperationResult:
    await asyncio.sleep(delay)
    return OperationResult(
        op_id=op.op_id, agent_id=op.agent_id, kind=op.kind,
        success=True, payload={"slept": delay},
    )


def _op(agent_id: str = "emma", kind: str = "do_something",
        created: int = 10, timeout: int = 34) -> PendingOp:
    return PendingOp(
        op_id=f"op_{agent_id}_{created}_{kind}",
        agent_id=agent_id,
        kind=kind,  # type: ignore[arg-type]
        created_tick=created, timeout_tick=timeout,
    )


# --- Tests --------------------------------------------------------------


class TestPendingOpModel:

    def test_construct_ok(self):
        op = PendingOp(
            op_id="op1", agent_id="emma", kind="do_something",
            created_tick=10, timeout_tick=20,
        )
        assert op.timeout_tick > op.created_tick

    def test_invalid_timeout_rejected(self):
        with pytest.raises(ValueError, match="timeout_tick"):
            PendingOp(
                op_id="op1", agent_id="emma", kind="do_something",
                created_tick=10, timeout_tick=10,
            )

    def test_frozen(self):
        op = PendingOp(
            op_id="op1", agent_id="emma", kind="do_something",
            created_tick=10, timeout_tick=20,
        )
        with pytest.raises(Exception):
            op.agent_id = "linda"  # type: ignore[misc]


class TestOperationResultModel:

    def test_total_tokens_sum(self):
        r = OperationResult(
            op_id="x", agent_id="emma", kind="do_something",
            success=True, prompt_tokens=12, completion_tokens=8,
        )
        assert r.total_tokens == 20

    def test_default_failure_state(self):
        r = OperationResult(
            op_id="x", agent_id="emma", kind="do_something",
            success=False, error_msg="oops",
        )
        assert r.success is False
        assert r.payload == {}


class TestSchedule:

    def _make_pool(self, handlers=None):
        handlers = handlers or {"do_something": _success_handler}
        return OperationPool(
            handlers=handlers,
            llm_clients={"sonnet": _StubLLM("sonnet"), "haiku": _StubLLM("haiku"), "nano": _StubLLM("nano")},
        )

    def test_schedule_one_op(self):
        pool = self._make_pool()
        pool.schedule(_op())
        assert pool.in_flight_count() == 1
        assert pool.get_pending("emma") is not None

    def test_double_schedule_same_agent_raises(self):
        pool = self._make_pool()
        pool.schedule(_op())
        with pytest.raises(ConcurrentOperationError, match="emma"):
            pool.schedule(_op())

    def test_unknown_kind_rejected(self):
        pool = self._make_pool()  # only do_something registered
        with pytest.raises(ValueError, match="no handler"):
            pool.schedule(_op(kind="reflect"))

    def test_cancel_clears_pending(self):
        pool = self._make_pool()
        pool.schedule(_op())
        assert pool.cancel("emma") is True
        assert pool.in_flight_count() == 0

    def test_cancel_unknown_returns_false(self):
        pool = self._make_pool()
        assert pool.cancel("unknown") is False


class TestProcessPending:

    def _make_pool(self):
        return OperationPool(
            handlers={"do_something": _success_handler},
            llm_clients={"sonnet": _StubLLM("sonnet"), "haiku": _StubLLM("haiku")},
        )

    def test_runs_handler_concurrently(self):
        pool = OperationPool(
            handlers={"do_something": _slow_handler},
            llm_clients={"sonnet": _StubLLM()},
        )
        # Schedule 5 slow (50ms each) ops
        for i in range(5):
            pool.schedule(_op(agent_id=f"a{i}", created=10))
        import time
        t0 = time.perf_counter()
        results = asyncio.run(pool.process_pending(current_tick=11))
        elapsed = time.perf_counter() - t0
        # If serial: 5 × 50ms = 250ms. Concurrent: ~50-80ms.
        assert len(results) == 5
        assert all(r.success for r in results)
        assert elapsed < 0.20, f"expected <200ms, got {elapsed*1000:.0f}ms"

    def test_completed_clears_pending(self):
        pool = self._make_pool()
        pool.schedule(_op())
        asyncio.run(pool.process_pending(current_tick=11))
        assert pool.in_flight_count() == 0

    def test_timeout_skips_handler(self):
        pool = OperationPool(
            handlers={"do_something": _success_handler},
            llm_clients={"sonnet": _StubLLM()},
        )
        pool.schedule(_op(created=10, timeout=15))
        # current_tick beyond timeout
        results = asyncio.run(pool.process_pending(current_tick=20))
        # Timed out → no result returned (only completed in list)
        assert results == []
        assert pool.in_flight_count() == 0
        summary = pool.get_cost_summary()
        assert summary["timeouts"] == 1

    def test_handler_exception_becomes_failed_result(self):
        pool = OperationPool(
            handlers={"do_something": _raising_handler},
            llm_clients={"sonnet": _StubLLM()},
        )
        pool.schedule(_op())
        results = asyncio.run(pool.process_pending(current_tick=11))
        assert len(results) == 1
        assert results[0].success is False
        assert "RuntimeError" in (results[0].error_msg or "")
        assert pool.get_cost_summary()["errors"] == 1


class TestTierRouting:

    def test_uses_default_tier_per_kind(self):
        sonnet = _StubLLM("sonnet")
        haiku = _StubLLM("haiku")
        nano = _StubLLM("nano")
        pool = OperationPool(
            handlers={
                "do_something": _success_handler,
                "score_importance": _success_handler,
            },
            llm_clients={"sonnet": sonnet, "haiku": haiku, "nano": nano},
        )
        pool.schedule(_op(agent_id="a1", kind="do_something"))
        pool.schedule(_op(agent_id="a2", kind="score_importance"))
        asyncio.run(pool.process_pending(current_tick=11))
        # do_something → sonnet; score_importance → nano
        assert len(sonnet.calls) == 1
        assert len(nano.calls) == 1
        assert haiku.calls == []  # nothing routed to haiku in this run

    def test_custom_tier_override(self):
        sonnet = _StubLLM("sonnet")
        nano = _StubLLM("nano")
        pool = OperationPool(
            handlers={"reflect": _success_handler},
            llm_clients={"sonnet": sonnet, "nano": nano},
            tier_for_kind={"reflect": "nano"},  # override default haiku → nano
        )
        pool.schedule(_op(kind="reflect"))
        asyncio.run(pool.process_pending(current_tick=11))
        assert len(nano.calls) == 1
        assert len(sonnet.calls) == 0


class TestCostTelemetry:

    def test_cost_summary_aggregates(self):
        pool = OperationPool(
            handlers={
                "do_something": _success_handler,
                "score_importance": _success_handler,
            },
            llm_clients={"sonnet": _StubLLM(), "nano": _StubLLM()},
        )
        for i in range(3):
            pool.schedule(_op(agent_id=f"a{i}", kind="do_something"))
        asyncio.run(pool.process_pending(current_tick=11))
        for i in range(2):
            pool.schedule(_op(agent_id=f"b{i}", kind="score_importance"))
        asyncio.run(pool.process_pending(current_tick=11))

        summary = pool.get_cost_summary()
        assert summary["total_ops"] == 5
        assert summary["by_kind"]["do_something"] == 3
        assert summary["by_kind"]["score_importance"] == 2
        # each handler returns 10 prompt + 5 completion → 3×15 sonnet, 2×15 nano
        assert summary["by_tier"]["sonnet"]["count"] == 3
        assert summary["by_tier"]["sonnet"]["prompt_tokens"] == 30
        assert summary["by_tier"]["nano"]["count"] == 2

    def test_no_default_tier_falls_back_to_first_available(self):
        """If requested tier missing, falls back to default tier or first available."""
        only_haiku = _StubLLM("haiku")
        pool = OperationPool(
            handlers={"reflect": _success_handler},
            llm_clients={"haiku": only_haiku},  # no sonnet, no nano
            default_tier="haiku",
        )
        pool.schedule(_op(kind="reflect"))
        asyncio.run(pool.process_pending(current_tick=11))
        assert len(only_haiku.calls) == 1
