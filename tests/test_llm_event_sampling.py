"""Phase G6 — LLM event sampling: success 1%, errors 100%."""

from __future__ import annotations

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


def _read_llm(out: Path) -> list[dict]:
    f = out / "seed_42.llm.jsonl"
    if not f.exists():
        return []
    return [json.loads(l) for l in f.read_text().splitlines() if l]


def test_success_calls_sampled_at_default_rate(
    tmp_output_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """10000 success calls @ default 1% → ~100 ± 30 rows."""
    monkeypatch.setenv("LLM_SAMPLE_RATE", "0.01")
    from synthetic_socio_wind_tunnel.observability import instrumentation
    inst = instrumentation.get_instrumentation()

    for i in range(10000):
        inst.emit_llm_call(
            tier="sonnet", provider="deepseek", model="deepseek-v4-pro",
            kind="do_something", agent_id=f"a_{i}",
            latency_ms=1000, status="success",
            attempt=0, max_attempts=3,
        )

    rows = _read_llm(tmp_output_dir)
    # Poisson std ≈ sqrt(100) = 10; allow 4σ window for stability
    assert 60 <= len(rows) <= 200, f"sampled {len(rows)} of 10000"


def test_error_calls_100_percent_recorded(
    tmp_output_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All fallback / exhausted calls recorded regardless of sample rate."""
    monkeypatch.setenv("LLM_SAMPLE_RATE", "0.001")  # 0.1%
    from synthetic_socio_wind_tunnel.observability import instrumentation
    inst = instrumentation.get_instrumentation()

    for i in range(500):
        inst.emit_llm_call(
            tier="sonnet", provider="deepseek", model="deepseek-v4-pro",
            kind="do_something", agent_id=f"a_{i}",
            latency_ms=5000, status="fallback",
            exc_class="openai.APIConnectionError",
            attempt=0, max_attempts=3,
        )

    rows = _read_llm(tmp_output_dir)
    # All 500 SHALL be recorded
    assert len(rows) == 500
    assert all(r["status"] == "fallback" for r in rows)


def test_zero_sample_rate_still_records_errors(
    tmp_output_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM_SAMPLE_RATE=0 → 0 success rows, but errors still 100%."""
    monkeypatch.setenv("LLM_SAMPLE_RATE", "0")
    from synthetic_socio_wind_tunnel.observability import instrumentation
    inst = instrumentation.get_instrumentation()

    for _ in range(100):
        inst.emit_llm_call(
            tier="sonnet", provider="deepseek", model="x",
            kind="do_something", agent_id="a", latency_ms=100,
            status="success", attempt=0, max_attempts=3,
        )
    for _ in range(20):
        inst.emit_llm_call(
            tier="sonnet", provider="deepseek", model="x",
            kind="do_something", agent_id="a", latency_ms=5000,
            status="fallback", attempt=0, max_attempts=3,
            exc_class="openai.APIConnectionError",
        )

    rows = _read_llm(tmp_output_dir)
    success = [r for r in rows if r["status"] == "success"]
    fallback = [r for r in rows if r["status"] == "fallback"]
    assert len(success) == 0
    assert len(fallback) == 20


def test_llm_event_has_required_fields(tmp_output_dir: Path) -> None:
    """Each llm.jsonl line SHALL have required schema fields."""
    from synthetic_socio_wind_tunnel.observability import instrumentation
    inst = instrumentation.get_instrumentation()
    # Force sample (status=success at rate=1)
    import os
    os.environ["LLM_SAMPLE_RATE"] = "1.0"
    instrumentation.reset_for_tests()
    inst = instrumentation.get_instrumentation()

    inst.emit_llm_call(
        tier="sonnet", provider="deepseek", model="deepseek-v4-pro",
        kind="do_something", agent_id="a_42_0001",
        latency_ms=1234, status="success",
        attempt=1, max_attempts=3, key_id=3,
        prompt_chars=8400, response_chars=410,
    )

    rows = _read_llm(tmp_output_dir)
    assert len(rows) >= 1
    r = rows[0]
    required = {
        "v", "ts_iso", "tier", "provider", "model", "kind",
        "agent_id", "key_id", "attempt", "max_attempts",
        "latency_ms", "status",
    }
    assert required.issubset(set(r.keys()))
