"""Phase G3 — SNAPSHOT_WRITE event includes events_evicted_before_write.

Spec: prune-before-snapshot-write 'SNAPSHOT_WRITE event 包含
events_evicted_before_write'.
"""

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


def test_snapshot_event_includes_evict_count(
    tmp_output_dir: Path, tmp_path: Path,
) -> None:
    """SNAPSHOT_WRITE event SHALL include events_evicted_before_write."""
    from synthetic_socio_wind_tunnel.observability import instrumentation
    inst = instrumentation.get_instrumentation()

    snapshot_path = tmp_path / "test.snapshot.json"
    snapshot_path.write_bytes(b"x" * 1024)

    inst.emit_snapshot_write(
        tick_global=200, path=str(snapshot_path),
        duration_sec=0.5,
        rss_before_mb=2000, rss_peak_during_mb=2100, rss_after_mb=2050,
        events_evicted_before_write=50000,
    )

    events = _read_events(tmp_output_dir)
    snap_events = [e for e in events if e.get("kind") == "SNAPSHOT_WRITE"]
    assert len(snap_events) == 1
    assert snap_events[0]["events_evicted_before_write"] == 50000


def test_snapshot_event_evict_count_defaults_to_zero(
    tmp_output_dir: Path, tmp_path: Path,
) -> None:
    """When events_evicted_before_write is not passed, SHALL default to 0
    (backward-compat for callers not yet updated)."""
    from synthetic_socio_wind_tunnel.observability import instrumentation
    inst = instrumentation.get_instrumentation()

    snapshot_path = tmp_path / "test.snapshot.json"
    snapshot_path.write_bytes(b"x" * 512)

    inst.emit_snapshot_write(
        tick_global=100, path=str(snapshot_path),
        duration_sec=0.1,
        rss_before_mb=1000, rss_peak_during_mb=1050, rss_after_mb=1020,
    )

    events = _read_events(tmp_output_dir)
    snap_events = [e for e in events if e.get("kind") == "SNAPSHOT_WRITE"]
    assert len(snap_events) == 1
    assert snap_events[0]["events_evicted_before_write"] == 0
