"""Phase G1 — RuntimeInstrumentation module skeleton + JSONL output.

TDD red phase: module doesn't exist yet → ImportError.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


def _get_module():
    from synthetic_socio_wind_tunnel.observability import instrumentation
    return instrumentation


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Ensure each test gets fresh singleton."""
    try:
        from synthetic_socio_wind_tunnel.observability import instrumentation
        instrumentation.reset_for_tests()
        yield
        instrumentation.reset_for_tests()
    except ImportError:
        yield


@pytest.fixture
def tmp_output_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point instrumentation at a per-test output directory."""
    monkeypatch.setenv("INSTRUMENTATION_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("INSTRUMENTATION_SEED", "42")
    # Force 100% sample for tests so emit_llm_call always writes
    monkeypatch.setenv("LLM_SAMPLE_RATE", "1.0")
    return tmp_path


def test_get_instrumentation_creates_3_jsonl_files(
    tmp_output_dir: Path,
) -> None:
    """spec: first access creates singleton + opens 3 files."""
    m = _get_module()
    inst = m.get_instrumentation()
    inst.emit_event(kind="PHASE", phase="TEST")  # force a write

    expected = [
        tmp_output_dir / "seed_42.memstat.jsonl",
        tmp_output_dir / "seed_42.events.jsonl",
        tmp_output_dir / "seed_42.llm.jsonl",
    ]
    for p in expected:
        assert p.exists(), f"missing {p}"

    # Subsequent calls return same instance
    inst2 = m.get_instrumentation()
    assert inst is inst2


def test_instrumentation_disable_returns_noop_stub(
    tmp_output_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """spec: INSTRUMENTATION_DISABLE=1 returns no-op stub."""
    monkeypatch.setenv("INSTRUMENTATION_DISABLE", "1")
    m = _get_module()
    inst = m.get_instrumentation()
    # Calling methods on the stub SHALL NOT raise
    inst.emit_event(kind="PHASE", phase="TEST")
    inst.emit_llm_call(tier="sonnet", provider="stub", model="x",
                       kind="do_something", agent_id="a",
                       latency_ms=10, status="success",
                       attempt=0, max_attempts=3)
    inst.sample_metrics(tick_global=100, day_index=0, tick_in_day=100)
    # NO files created
    assert not (tmp_output_dir / "seed_42.memstat.jsonl").exists()
    assert not (tmp_output_dir / "seed_42.events.jsonl").exists()
    assert not (tmp_output_dir / "seed_42.llm.jsonl").exists()


def test_reset_for_tests_closes_files(tmp_output_dir: Path) -> None:
    """spec: reset_for_tests closes files + clears singleton."""
    m = _get_module()
    inst1 = m.get_instrumentation()
    inst1.emit_event(kind="PHASE", phase="A")

    m.reset_for_tests()

    inst2 = m.get_instrumentation()
    inst2.emit_event(kind="PHASE", phase="B")
    assert inst1 is not inst2  # fresh instance

    # events.jsonl SHALL contain both events
    text = (tmp_output_dir / "seed_42.events.jsonl").read_text()
    lines = [l for l in text.splitlines() if l]
    assert len(lines) >= 2
    assert any('"A"' in l for l in lines)
    assert any('"B"' in l for l in lines)


def test_failure_isolation_emit_event_does_not_raise_on_io_error(
    tmp_output_dir: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """spec: emit failures SHALL log warning + NOT raise."""
    m = _get_module()
    inst = m.get_instrumentation()
    # Force file write to fail
    with patch.object(
        inst, "_events_fh",
        new=type("BadFH", (), {
            "write": lambda *a, **k: (_ for _ in ()).throw(
                OSError("simulated disk full"),
            ),
            "flush": lambda *a, **k: None,
        })(),
    ):
        # Must not raise
        inst.emit_event(kind="PHASE", phase="X")

    # SHALL have logged warning
    warns = [r for r in caplog.records
             if "instrumentation" in r.message.lower()]
    assert len(warns) >= 1


def test_event_jsonl_has_version_field(tmp_output_dir: Path) -> None:
    """Each line SHALL have `v: 1` for schema evolution."""
    m = _get_module()
    inst = m.get_instrumentation()
    inst.emit_event(kind="PHASE", phase="TEST", extra="data")

    text = (tmp_output_dir / "seed_42.events.jsonl").read_text()
    lines = [l for l in text.splitlines() if l]
    # Index 0 is auto-emitted PROCESS_START; our event is later
    parsed_lines = [json.loads(l) for l in lines]
    our = [p for p in parsed_lines if p.get("phase") == "TEST"]
    assert len(our) == 1
    parsed = our[0]
    assert parsed["v"] == 1
    assert parsed["kind"] == "PHASE"
    assert parsed["phase"] == "TEST"
    assert parsed["extra"] == "data"
    assert "ts_iso" in parsed


def test_emit_llm_call_writes_to_llm_jsonl(tmp_output_dir: Path) -> None:
    """LLM events go to llm.jsonl not events.jsonl."""
    m = _get_module()
    inst = m.get_instrumentation()
    inst.emit_llm_call(
        tier="sonnet", provider="deepseek", model="deepseek-v4-pro",
        kind="do_something", agent_id="a_001",
        latency_ms=1234, status="success",
        attempt=0, max_attempts=3,
    )
    llm_path = tmp_output_dir / "seed_42.llm.jsonl"
    events_path = tmp_output_dir / "seed_42.events.jsonl"
    assert llm_path.exists()
    text = llm_path.read_text()
    lines = [l for l in text.splitlines() if l]
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["tier"] == "sonnet"
    assert parsed["status"] == "success"
    # events.jsonl SHALL NOT have this line
    if events_path.exists():
        assert "do_something" not in events_path.read_text()
