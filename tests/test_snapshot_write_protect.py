"""WRITE-PROTECT (2026-05-21): snapshot/summary/partial files chmod 0444.

R1 (PID-prefixed filenames) + R2 (auto-backup on resume) protect
against unintended same-named writes during resume. WRITE-PROTECT
closes the per-file gap: after atomic write, chmod 0444 so the OS
refuses any subsequent overwrite (operator typo, external `cp -f`,
buggy diag tool, etc).

prune still works because we explicitly chmod +w before unlink.

Tests:
- snapshot file mode = 0o444 after write
- partial / day_summary file mode = 0o444
- attempting to overwrite raises PermissionError
- prune deletes read-only files successfully
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
import pytest

from synthetic_socio_wind_tunnel.run_resilience.state_snapshot import (
    SimulationCheckpoint,
    prune_snapshots,
    snapshot_path,
)
from synthetic_socio_wind_tunnel.run_resilience.checkpoint import (
    DayCheckpointWriter,
)


def _minimal_checkpoint() -> SimulationCheckpoint:
    return SimulationCheckpoint(
        seed=42, tick_index=12, day_index=0,
        simulated_time=datetime(2026, 4, 22, 1, 0, 0),
    )


def test_snapshot_chmod_0444_after_write(tmp_path: Path):
    """SimulationCheckpoint.write_atomic SHALL chmod 0444 the final file."""
    snap = _minimal_checkpoint()
    p = snapshot_path(tmp_path, seed=42, tick_index_global=12, spawn_id=100)
    snap.write_atomic(p)
    mode = os.stat(p).st_mode & 0o777
    assert mode == 0o444, f"Expected 0o444, got 0o{mode:o}"


def test_snapshot_overwrite_blocked_by_chmod(tmp_path: Path):
    """A chmod-0444 file SHALL refuse open(..., 'w')."""
    snap = _minimal_checkpoint()
    p = snapshot_path(tmp_path, seed=42, tick_index_global=12, spawn_id=100)
    snap.write_atomic(p)
    with pytest.raises(PermissionError):
        with p.open("w") as f:
            f.write("malicious overwrite")


def test_prune_still_works_on_readonly_files(tmp_path: Path):
    """prune_snapshots SHALL delete read-only files (chmod +w before unlink)."""
    import time
    for i, tick in enumerate([12, 24, 36, 48, 60]):
        snap = _minimal_checkpoint()
        p = snapshot_path(tmp_path, seed=42, tick_index_global=tick, spawn_id=100)
        snap.write_atomic(p)
        # Set ascending mtimes for deterministic ordering
        ts = time.time() - (5 - i) * 10
        os.utime(p, (ts, ts))

    deleted = prune_snapshots(tmp_path, seed=42, keep=2)
    assert len(deleted) == 3, f"expected 3 deletes, got {len(deleted)}"
    survivors = sorted(tmp_path.glob("seed_42_*.snapshot.json"))
    assert len(survivors) == 2


def test_day_summary_chmod_0444(tmp_path: Path):
    """DayCheckpointWriter.write_day_summary SHALL chmod 0444."""
    w = DayCheckpointWriter()
    p = w.write_day_summary(
        day_index=0,
        summary_dict={"day_index": 0, "tick_count": 288},
        output_dir=tmp_path,
        seed=42,
    )
    mode = os.stat(p).st_mode & 0o777
    assert mode == 0o444, f"Expected 0o444, got 0o{mode:o}"


def test_partial_chmod_0444(tmp_path: Path):
    """DayCheckpointWriter.write_partial SHALL chmod 0444."""
    w = DayCheckpointWriter()
    p = w.write_partial(
        output_dir=tmp_path,
        seed=42,
        day_index=0,
        simulated_date=date(2026, 4, 22),
        run_metrics={},
        ledger_snapshot={},
        memory_dump={},
        provider="stub",
    )
    mode = os.stat(p).st_mode & 0o777
    assert mode == 0o444, f"Expected 0o444, got 0o{mode:o}"
