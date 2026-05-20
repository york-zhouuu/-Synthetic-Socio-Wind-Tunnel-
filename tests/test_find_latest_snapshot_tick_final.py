"""Bug D regression — find_latest_snapshot SHALL recognize tick_final.

The pre-fix logic did `int(stem)` which raised ValueError for
`tick_final` and silently skipped, causing auto-resume to pick stale
periodic snapshots after a graceful_stop.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from synthetic_socio_wind_tunnel.run_resilience.state_snapshot import (
    find_latest_snapshot,
)


def _touch(p: Path, *, mtime: float) -> None:
    p.write_text("{}")
    os.utime(p, (mtime, mtime))


def test_tick_final_preferred_when_newer(tmp_path: Path) -> None:
    """tick_final with newer mtime SHALL win over numeric snapshot."""
    now = time.time()
    _touch(tmp_path / "seed_42_tick3444.snapshot.json", mtime=now - 1000)
    _touch(tmp_path / "seed_42_tick_final.snapshot.json", mtime=now)
    result = find_latest_snapshot(tmp_path, seed=42)
    assert result is not None
    assert result.name == "seed_42_tick_final.snapshot.json"


def test_numeric_wins_when_tick_final_is_stale(tmp_path: Path) -> None:
    """If tick_final is older than newest numeric, numeric wins (stale)."""
    now = time.time()
    _touch(tmp_path / "seed_42_tick_final.snapshot.json", mtime=now - 1000)
    _touch(tmp_path / "seed_42_tick3984.snapshot.json", mtime=now)
    result = find_latest_snapshot(tmp_path, seed=42)
    assert result is not None
    assert result.name == "seed_42_tick3984.snapshot.json"


def test_only_numeric_pick_latest_mtime(tmp_path: Path) -> None:
    """2026-05-21 R1 (fix-snapshot-filename-spawn-collision): selection
    moved from highest-tick to latest-mtime. When no tick_final, mtime
    wins — supports PID-prefixed spawn collision avoidance where
    newer respawn may have LOWER internal tick number than older spawn."""
    now = time.time()
    _touch(tmp_path / "seed_42_tick3000.snapshot.json", mtime=now)
    _touch(tmp_path / "seed_42_tick3500.snapshot.json", mtime=now - 100)
    result = find_latest_snapshot(tmp_path, seed=42)
    assert result is not None
    # Latest mtime wins (regardless of tick number)
    assert result.name == "seed_42_tick3000.snapshot.json"


def test_only_tick_final_present_picks_it(tmp_path: Path) -> None:
    """If tick_final is the only snapshot, return it."""
    _touch(tmp_path / "seed_42_tick_final.snapshot.json", mtime=time.time())
    result = find_latest_snapshot(tmp_path, seed=42)
    assert result is not None
    assert result.name == "seed_42_tick_final.snapshot.json"


def test_no_snapshots_returns_none(tmp_path: Path) -> None:
    """Regression: empty dir → None."""
    result = find_latest_snapshot(tmp_path, seed=42)
    assert result is None
