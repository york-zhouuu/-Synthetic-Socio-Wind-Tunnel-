"""Phase G3 — phase event ordering + atexit EXIT."""

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


def _read_events(out: Path) -> list[dict]:
    f = out / "seed_42.events.jsonl"
    if not f.exists():
        return []
    return [json.loads(l) for l in f.read_text().splitlines() if l]


def test_phase_events_emit_in_documented_order(tmp_output_dir: Path) -> None:
    """spec: phase events appear in this fixed order on success path."""
    from synthetic_socio_wind_tunnel.observability import instrumentation
    inst = instrumentation.get_instrumentation()
    # get_instrumentation() auto-emits PROCESS_START on first call —
    # we don't emit it again manually below
    inst.emit_event(kind="PHASE", phase="SETUP_START")
    inst.emit_event(kind="PHASE", phase="SETUP_DONE", duration_sec=1.2)
    inst.emit_event(kind="PHASE", phase="SNAPSHOT_LOAD_START")
    inst.emit_event(kind="PHASE", phase="SNAPSHOT_LOAD_DONE",
                    duration_sec=10.5, rss_before_mb=2000,
                    rss_after_mb=15000)
    inst.emit_event(kind="PHASE", phase="TICK_LOOP_START")
    inst.emit_event(kind="PHASE", phase="DAY_START", day_index=0)
    inst.emit_event(kind="PHASE", phase="DAY_END", day_index=0)
    inst.emit_event(kind="PHASE", phase="EXIT", reason="done")

    events = _read_events(tmp_output_dir)
    phases = [e["phase"] for e in events if e["kind"] == "PHASE"]
    expected = [
        "PROCESS_START", "SETUP_START", "SETUP_DONE",
        "SNAPSHOT_LOAD_START", "SNAPSHOT_LOAD_DONE", "TICK_LOOP_START",
        "DAY_START", "DAY_END", "EXIT",
    ]
    assert phases == expected, f"order mismatch: {phases}"


def test_phase_events_have_required_fields(tmp_output_dir: Path) -> None:
    """Each PHASE event SHALL have ts_iso, ts_monotonic, rss_mb."""
    from synthetic_socio_wind_tunnel.observability import instrumentation
    inst = instrumentation.get_instrumentation()
    inst.emit_event(kind="PHASE", phase="TEST_PHASE")
    events = _read_events(tmp_output_dir)
    e = events[0]
    assert "ts_iso" in e
    assert "ts_monotonic" in e
    # rss_mb should be auto-attached by the emit_event impl
    assert "rss_mb" in e


def test_atexit_emits_exit_event(
    tmp_output_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """spec: atexit hook SHALL emit EXIT event as final line."""
    from synthetic_socio_wind_tunnel.observability import instrumentation
    inst = instrumentation.get_instrumentation()
    inst.emit_event(kind="PHASE", phase="PROCESS_START")

    # Simulate atexit by calling shutdown directly
    inst.shutdown(reason="atexit")

    events = _read_events(tmp_output_dir)
    assert len(events) >= 2
    last = events[-1]
    assert last["kind"] == "PHASE"
    assert last["phase"] == "EXIT"
    assert last.get("reason") == "atexit"


def test_no_duplicate_process_start(tmp_output_dir: Path) -> None:
    """PROCESS_START SHALL fire at most once per process (first
    get_instrumentation() call)."""
    from synthetic_socio_wind_tunnel.observability import instrumentation
    inst1 = instrumentation.get_instrumentation()
    inst2 = instrumentation.get_instrumentation()
    inst3 = instrumentation.get_instrumentation()
    assert inst1 is inst2 is inst3

    events = _read_events(tmp_output_dir)
    process_starts = [e for e in events
                      if e.get("kind") == "PHASE"
                      and e.get("phase") == "PROCESS_START"]
    assert len(process_starts) <= 1
