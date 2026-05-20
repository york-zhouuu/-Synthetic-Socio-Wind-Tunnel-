"""R1 (2026-05-21): snapshot filename SHALL NOT collide across spawns.

2026-05-20 evening, baseline scout was killed and re-resumed for diag.
The diag worker's internal tick counter happened to reach 276 again,
overwriting the original `seed_43_tick276.snapshot.json`. The original
state at sim day 0 23:00 was permanently lost — destroying β=1
cross-variant alignment.

Root cause: `seed_<N>_tick<T>.snapshot.json` uses the worker's own
internal tick counter (resets to 0 per spawn). Multiple spawns write
to the same filename.

Fix: include `pid<PID>` in the filename. Two spawns naturally produce
different PIDs → different filenames → no collision.

Tests verify:
- Two spawns at same internal tick 12 produce TWO files (no overwrite)
- find_latest_snapshot uses mtime (latest write wins across spawns)
- Legacy format (no PID) still readable + resumable
- prune_snapshots uses mtime ordering (newest K kept)
"""

from __future__ import annotations

import time
from pathlib import Path

from synthetic_socio_wind_tunnel.run_resilience.state_snapshot import (
    find_latest_snapshot,
    prune_snapshots,
    snapshot_path,
)


def _touch_snapshot(path: Path, content: dict | None = None) -> Path:
    """Write a minimal valid snapshot file."""
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = content or {"placeholder": True}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_two_spawns_dont_collide(tmp_path: Path):
    """Two different PIDs writing tick=12 SHALL produce two distinct files."""
    # spawn A (PID 100) writes tick 12
    a_path = snapshot_path(
        tmp_path, seed=42, tick_index_global=12, spawn_id=100,
    )
    _touch_snapshot(a_path, {"pid": 100, "tick": 12, "marker": "spawn_a"})

    # spawn B (PID 200) writes its internal tick 12 — should be DIFFERENT file
    b_path = snapshot_path(
        tmp_path, seed=42, tick_index_global=12, spawn_id=200,
    )
    _touch_snapshot(b_path, {"pid": 200, "tick": 12, "marker": "spawn_b"})

    # Both files exist; A NOT overwritten
    assert a_path != b_path, "Same path → collision"
    assert a_path.exists()
    assert b_path.exists()

    import json
    a_data = json.loads(a_path.read_text())
    b_data = json.loads(b_path.read_text())
    assert a_data["marker"] == "spawn_a"
    assert b_data["marker"] == "spawn_b"


def test_find_latest_picks_newest_mtime(tmp_path: Path):
    """Across multiple spawns, latest by mtime wins (not highest tick)."""
    older = snapshot_path(
        tmp_path, seed=42, tick_index_global=120, spawn_id=100,
    )
    _touch_snapshot(older, {"pid": 100, "tick": 120})
    # Make older clearly older
    import os
    older_ts = time.time() - 60
    os.utime(older, (older_ts, older_ts))

    # Newer file with LOWER tick number but later mtime
    newer = snapshot_path(
        tmp_path, seed=42, tick_index_global=12, spawn_id=200,
    )
    _touch_snapshot(newer, {"pid": 200, "tick": 12})

    found = find_latest_snapshot(tmp_path, seed=42)
    assert found == newer, (
        f"expected newest mtime ({newer.name}), got {found.name if found else None}"
    )


def test_legacy_format_still_discoverable(tmp_path: Path):
    """Legacy files without PID SHALL remain resumable (back-compat)."""
    legacy = tmp_path / "seed_42_tick120.snapshot.json"
    _touch_snapshot(legacy, {"tick": 120, "legacy": True})

    found = find_latest_snapshot(tmp_path, seed=42)
    assert found == legacy


def test_legacy_and_new_format_mix(tmp_path: Path):
    """When both formats exist, latest by mtime wins."""
    legacy = tmp_path / "seed_42_tick120.snapshot.json"
    _touch_snapshot(legacy)
    import os
    legacy_ts = time.time() - 100
    os.utime(legacy, (legacy_ts, legacy_ts))

    new_format = snapshot_path(
        tmp_path, seed=42, tick_index_global=12, spawn_id=999,
    )
    _touch_snapshot(new_format)

    found = find_latest_snapshot(tmp_path, seed=42)
    assert found == new_format, (
        "newer mtime SHALL win regardless of format"
    )


def test_prune_by_mtime_keeps_newest(tmp_path: Path):
    """prune_snapshots SHALL keep K newest by mtime, delete the rest."""
    import os
    paths = []
    base_time = time.time() - 500
    for i, (tick, pid) in enumerate([
        (12, 100), (24, 100), (12, 200), (24, 200), (36, 200),
    ]):
        p = snapshot_path(tmp_path, seed=42, tick_index_global=tick, spawn_id=pid)
        _touch_snapshot(p)
        ts = base_time + i * 10  # ascending mtimes
        os.utime(p, (ts, ts))
        paths.append(p)

    # keep last 2 by mtime — paths[3] and paths[4] should survive
    deleted = prune_snapshots(tmp_path, seed=42, keep=2)
    assert len(deleted) == 3
    survivors = [p for p in paths if p.exists()]
    assert len(survivors) == 2
    # The 2 newest (paths[3], paths[4]) are kept
    assert set(survivors) == {paths[3], paths[4]}


def test_snapshot_path_back_compat_no_spawn_id(tmp_path: Path):
    """snapshot_path with NO spawn_id SHALL produce legacy filename."""
    p = snapshot_path(tmp_path, seed=42, tick_index_global=12)
    assert p.name == "seed_42_tick12.snapshot.json"


def test_snapshot_path_new_format_with_spawn_id(tmp_path: Path):
    """snapshot_path WITH spawn_id SHALL produce PID-prefixed filename."""
    p = snapshot_path(tmp_path, seed=42, tick_index_global=12, spawn_id=12345)
    assert p.name == "seed_42_pid12345_tick12.snapshot.json"
