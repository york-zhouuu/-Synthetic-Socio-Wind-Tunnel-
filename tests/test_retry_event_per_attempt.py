"""Phase G5 — retry event per attempt (not just at exhaustion)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _reset_singleton():
    try:
        from synthetic_socio_wind_tunnel.observability import instrumentation
        instrumentation.reset_for_tests()
        yield
        instrumentation.reset_for_tests()
    except ImportError:
        yield


@pytest.fixture
def tmp_output_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("INSTRUMENTATION_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("INSTRUMENTATION_SEED", "42")
    return tmp_path


def _read_events(out: Path) -> list[dict]:
    f = out / "seed_42.events.jsonl"
    if not f.exists():
        return []
    return [json.loads(l) for l in f.read_text().splitlines() if l]


def test_retry_event_emits_per_failed_attempt(tmp_output_dir: Path) -> None:
    """spec: 2 fails + 1 success → 2 RETRY events, not 1."""
    import openai
    from synthetic_socio_wind_tunnel.observability import instrumentation
    from synthetic_socio_wind_tunnel.run_resilience.circuit_breaker import (
        PerKeyCircuitBreaker,
    )
    from synthetic_socio_wind_tunnel.run_resilience.retry import RetryPolicy
    from tools.tier_llm_factory import _run_with_retry

    instrumentation.get_instrumentation()

    attempts = []

    async def _op() -> str:
        attempts.append(None)
        if len(attempts) < 3:
            raise openai.APIConnectionError(request=None)
        return "ok"

    policy = RetryPolicy(
        max_attempts=3, base_backoff_seconds=0.01,
        max_backoff_seconds=0.05, jitter_ratio=0.0,
    )
    breaker = PerKeyCircuitBreaker()
    result = asyncio.run(_run_with_retry(
        operation=_op, policy=policy, breaker=breaker,
    ))
    assert result == "ok"

    events = _read_events(tmp_output_dir)
    retry_events = [e for e in events if e.get("kind") == "RETRY"]
    assert len(retry_events) == 2, (
        f"expected 2 RETRY events for 2 failed attempts, "
        f"got {len(retry_events)}"
    )
    # Each event SHALL have attempt + exc_class
    for i, ev in enumerate(retry_events):
        assert "attempt" in ev
        assert "exc_class" in ev
        assert "APIConnectionError" in ev["exc_class"]
        assert "backoff_sec" in ev
        assert ev["backoff_sec"] >= 0


def test_no_retry_event_on_first_success(tmp_output_dir: Path) -> None:
    """First-attempt success SHALL not emit RETRY events."""
    from synthetic_socio_wind_tunnel.observability import instrumentation
    from synthetic_socio_wind_tunnel.run_resilience.circuit_breaker import (
        PerKeyCircuitBreaker,
    )
    from synthetic_socio_wind_tunnel.run_resilience.retry import RetryPolicy
    from tools.tier_llm_factory import _run_with_retry

    instrumentation.get_instrumentation()

    async def _op() -> str:
        return "ok"

    policy = RetryPolicy(max_attempts=3)
    breaker = PerKeyCircuitBreaker()
    result = asyncio.run(_run_with_retry(
        operation=_op, policy=policy, breaker=breaker,
    ))
    assert result == "ok"

    events = _read_events(tmp_output_dir)
    retry_events = [e for e in events if e.get("kind") == "RETRY"]
    assert len(retry_events) == 0


def test_exhausted_emits_max_minus_1_retry_events(
    tmp_output_dir: Path,
) -> None:
    """All 3 attempts fail → 2 RETRY events (attempts 0 and 1 before
    last attempt 2)."""
    import openai
    from synthetic_socio_wind_tunnel.observability import instrumentation
    from synthetic_socio_wind_tunnel.run_resilience.circuit_breaker import (
        PerKeyCircuitBreaker,
    )
    from synthetic_socio_wind_tunnel.run_resilience.retry import RetryPolicy
    from tools.tier_llm_factory import _run_with_retry

    instrumentation.get_instrumentation()

    async def _op() -> str:
        raise openai.APIConnectionError(request=None)

    policy = RetryPolicy(
        max_attempts=3, base_backoff_seconds=0.01,
        max_backoff_seconds=0.05, jitter_ratio=0.0,
    )
    breaker = PerKeyCircuitBreaker(failure_threshold=10)
    with pytest.raises(openai.APIConnectionError):
        asyncio.run(_run_with_retry(
            operation=_op, policy=policy, breaker=breaker,
        ))

    events = _read_events(tmp_output_dir)
    retry_events = [e for e in events if e.get("kind") == "RETRY"]
    # 3 attempts, retry event fires after each FAILED attempt that
    # will retry — so attempts 0 and 1 fail+retry; attempt 2 fails+raise.
    # Expected: 2 RETRY events.
    assert len(retry_events) == 2, (
        f"3 failed attempts → expected 2 RETRY events "
        f"(retries between attempts), got {len(retry_events)}"
    )
