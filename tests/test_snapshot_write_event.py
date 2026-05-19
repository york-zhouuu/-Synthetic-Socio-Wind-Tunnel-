"""Phase G7 — snapshot write event captures size + RSS delta."""

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


def test_snapshot_write_event_captures_size_and_rss(
    tmp_output_dir: Path, tmp_path: Path,
) -> None:
    """spec: SNAPSHOT_WRITE event SHALL include size + RSS delta."""
    from synthetic_socio_wind_tunnel.observability import instrumentation
    inst = instrumentation.get_instrumentation()

    # Simulate writing a 10MB file
    snapshot_path = tmp_path / "fake.snapshot.json"
    payload = b"x" * (10 * 1024 * 1024)
    snapshot_path.write_bytes(payload)

    # Call the emit_snapshot_write helper directly (timing + rss capture)
    inst.emit_snapshot_write(
        tick_global=200, path=str(snapshot_path),
        duration_sec=0.5,
        rss_before_mb=2000, rss_peak_during_mb=2100, rss_after_mb=2050,
    )

    events = _read_events(tmp_output_dir)
    snap_events = [e for e in events if e.get("kind") == "SNAPSHOT_WRITE"]
    assert len(snap_events) == 1
    e = snap_events[0]
    assert e["tick_global"] == 200
    assert e["path"] == str(snapshot_path)
    assert e["size_bytes"] == 10 * 1024 * 1024
    assert e["rss_peak_during_mb"] >= e["rss_before_mb"]
    assert e["duration_sec"] >= 0


def test_snapshot_write_event_uses_actual_file_size(
    tmp_output_dir: Path, tmp_path: Path,
) -> None:
    """The size_bytes SHALL be re-read from disk at emit time, not
    passed in (so it can't be wrong)."""
    from synthetic_socio_wind_tunnel.observability import instrumentation
    inst = instrumentation.get_instrumentation()

    snapshot_path = tmp_path / "size.snapshot.json"
    snapshot_path.write_bytes(b"a" * 12345)

    inst.emit_snapshot_write(
        tick_global=100, path=str(snapshot_path),
        duration_sec=0.1,
        rss_before_mb=1000, rss_peak_during_mb=1100, rss_after_mb=1050,
    )

    events = _read_events(tmp_output_dir)
    snap_events = [e for e in events if e.get("kind") == "SNAPSHOT_WRITE"]
    assert snap_events[0]["size_bytes"] == 12345


def test_snapshot_write_handles_missing_file(
    tmp_output_dir: Path, tmp_path: Path,
) -> None:
    """If file doesn't exist (failed write), size_bytes SHALL be null
    or 0; SHALL NOT raise."""
    from synthetic_socio_wind_tunnel.observability import instrumentation
    inst = instrumentation.get_instrumentation()

    inst.emit_snapshot_write(
        tick_global=100, path=str(tmp_path / "nonexistent.snapshot.json"),
        duration_sec=0.5,
        rss_before_mb=1000, rss_peak_during_mb=1000, rss_after_mb=1000,
    )
    events = _read_events(tmp_output_dir)
    snap_events = [e for e in events if e.get("kind") == "SNAPSHOT_WRITE"]
    assert len(snap_events) == 1
    assert snap_events[0]["size_bytes"] in (None, 0)
