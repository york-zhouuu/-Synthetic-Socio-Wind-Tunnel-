"""E2E smoke — retry path survives realistic SDK transient failure.

Spec: openspec/specs/run-resilience/spec.md
Requirement: "_run_with_retry 必须重试 SDK 网络层异常"

Realistic scenario: a DeepSeek-style client (httpx-backed openai SDK)
hits 2 connection failures then succeeds on attempt 3. Validates the
full chain — class-name classify → _run_with_retry backoff → circuit
breaker stays healthy.
"""

from __future__ import annotations

import asyncio

import pytest

from synthetic_socio_wind_tunnel.run_resilience.circuit_breaker import (
    PerKeyCircuitBreaker,
)
from synthetic_socio_wind_tunnel.run_resilience.retry import RetryPolicy
from tools.tier_llm_factory import _run_with_retry


def test_deepseek_style_transient_failure_recovers_via_retry() -> None:
    """Mimic D2 attempt 6's failure mode (without the self-DDoS root cause).

    Operation raises real openai.APIConnectionError on attempts 1, 2;
    succeeds on attempt 3 with a plausible-looking response payload.
    Retry policy with realistic defaults SHALL recover.
    """
    import openai
    attempts = []
    payloads = ["fail-1", "fail-2", '{"action":"wait"}']

    async def _deepseek_call() -> str:
        n = len(attempts)
        attempts.append(payloads[n])
        if n < 2:
            raise openai.APIConnectionError(request=None)
        return payloads[n]

    # Real-ish retry policy — small backoff to keep test < 1s
    policy = RetryPolicy(
        max_attempts=3,
        base_backoff_seconds=0.05,
        max_backoff_seconds=0.2,
        jitter_ratio=0.0,
    )
    breaker = PerKeyCircuitBreaker(
        failure_threshold=5, cooldown_seconds=300.0,
    )

    result = asyncio.run(_run_with_retry(
        operation=_deepseek_call, policy=policy, breaker=breaker,
    ))

    assert result == '{"action":"wait"}'
    assert len(attempts) == 3, f"expected 3 attempts, got {len(attempts)}"

    # Critical assertion: circuit breaker MUST remain healthy.
    # Before this change, the first APIConnectionError would burn
    # a failure count immediately (zero retry).
    assert breaker.state == "closed"
    assert breaker._consecutive_failures == 0


def test_httpx_remote_protocol_error_recovers_via_retry() -> None:
    """httpx.RemoteProtocolError (TLS / chunked transfer mid-flight cut)
    SHALL be retried — common during cross-border DeepSeek calls."""
    import httpx
    attempts = []

    async def _flaky_call() -> str:
        attempts.append(None)
        if len(attempts) < 3:
            raise httpx.RemoteProtocolError(
                "Server disconnected before sending response",
            )
        return "ok"

    policy = RetryPolicy(
        max_attempts=3, base_backoff_seconds=0.05,
        max_backoff_seconds=0.2, jitter_ratio=0.0,
    )
    breaker = PerKeyCircuitBreaker()
    result = asyncio.run(_run_with_retry(
        operation=_flaky_call, policy=policy, breaker=breaker,
    ))
    assert result == "ok"
    assert breaker.state == "closed"


def test_fatal_401_does_not_retry() -> None:
    """Regression: 401 auth fatal SHALL NOT be retried even after fix."""
    class _Auth401(Exception):
        def __init__(self) -> None:
            super().__init__("unauthorized")
            self.status_code = 401

    attempts = []

    async def _bad_auth() -> str:
        attempts.append(None)
        raise _Auth401()

    policy = RetryPolicy(
        max_attempts=3, base_backoff_seconds=0.05,
        max_backoff_seconds=0.2, jitter_ratio=0.0,
    )
    breaker = PerKeyCircuitBreaker()
    with pytest.raises(_Auth401):
        asyncio.run(_run_with_retry(
            operation=_bad_auth, policy=policy, breaker=breaker,
        ))
    # SHALL fail on first attempt (no retry on fatal)
    assert len(attempts) == 1
    # And SHALL record breaker failure
    assert breaker._consecutive_failures == 1
