"""Layer 2 — _run_with_retry integration (Phase G2).

Spec: openspec/specs/run-resilience/spec.md
Requirement: "_run_with_retry 必须重试 SDK 网络层异常"
"""

from __future__ import annotations

import asyncio

import pytest

from synthetic_socio_wind_tunnel.run_resilience.circuit_breaker import (
    PerKeyCircuitBreaker,
)
from synthetic_socio_wind_tunnel.run_resilience.retry import RetryPolicy
from tools.tier_llm_factory import _run_with_retry


def test_retries_apiconnection_error_2_then_success() -> None:
    """spec scenario: 2 次 APIConnectionError + 1 次 success.

    Mock op raises openai.APIConnectionError on attempts 1, 2; returns
    "ok" on attempt 3. max_attempts=3 → SHALL succeed.
    """
    import openai
    attempts = {"n": 0}

    async def _op() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise openai.APIConnectionError(request=None)
        return "ok"

    # Tiny backoff so test is fast
    policy = RetryPolicy(max_attempts=3, base_backoff_seconds=0.01,
                         max_backoff_seconds=0.05, jitter_ratio=0.0)
    breaker = PerKeyCircuitBreaker()

    result = asyncio.run(_run_with_retry(
        operation=_op, policy=policy, breaker=breaker,
    ))

    assert result == "ok"
    assert attempts["n"] == 3
    # Breaker should NOT be in failure state
    assert breaker.state == "closed"
    assert breaker._consecutive_failures == 0


def test_exhausts_apiconnection_error_3_times() -> None:
    """spec scenario: 3 次 APIConnectionError 全失败后 record_failure 1 次."""
    import openai

    async def _op() -> str:
        raise openai.APIConnectionError(request=None)

    policy = RetryPolicy(max_attempts=3, base_backoff_seconds=0.01,
                         max_backoff_seconds=0.05, jitter_ratio=0.0)
    breaker = PerKeyCircuitBreaker(failure_threshold=10)  # high so 1 fail
                                                          # doesn't open it

    with pytest.raises(openai.APIConnectionError):
        asyncio.run(_run_with_retry(
            operation=_op, policy=policy, breaker=breaker,
        ))

    # Exactly 1 failure recorded (not 3 — _run_with_retry calls
    # record_failure once at the end of exhaustion, not per attempt)
    assert breaker._consecutive_failures == 1


def test_breaker_record_failure_not_called_during_retry() -> None:
    """spec: retry success path SHALL NOT touch record_failure.

    Mock op raises ConnectError 2x then succeeds. record_failure SHALL
    NOT be invoked (only record_success at end). 验证 retry 路径不
    accidentally count as failure.
    """
    import httpx
    attempts = {"n": 0}
    record_failure_calls = []

    async def _op() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise httpx.ConnectError("simulated")
        return "ok"

    policy = RetryPolicy(max_attempts=3, base_backoff_seconds=0.01,
                         max_backoff_seconds=0.05, jitter_ratio=0.0)
    breaker = PerKeyCircuitBreaker()
    orig_rf = breaker.record_failure

    def _spy():
        record_failure_calls.append(None)
        orig_rf()

    breaker.record_failure = _spy  # type: ignore[method-assign]

    result = asyncio.run(_run_with_retry(
        operation=_op, policy=policy, breaker=breaker,
    ))
    assert result == "ok"
    assert len(record_failure_calls) == 0, (
        f"record_failure called {len(record_failure_calls)} times during "
        f"successful retry sequence — should be 0"
    )
