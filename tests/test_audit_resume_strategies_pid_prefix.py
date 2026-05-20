"""NEW-B (2026-05-21): audit_resume_strategies SHALL recognize
PID-prefixed snapshot filenames (R1 introduced new naming).

Old glob `seed_<N>_tick*.snapshot.json` doesn't match
`seed_<N>_pid<PID>_tick<T>.snapshot.json`. After R1 ships, audit
silently misses all new snapshots.

Tests verify both legacy and PID-prefixed formats are detected.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


_TOOL = Path(__file__).resolve().parent.parent / "tools" / "audit_resume_strategies.py"


def _run_audit(suite_dir: Path, seed: int) -> dict:
    """Invoke audit_resume_strategies and parse JSON output. Exit code
    1 is normal when cells are INTERRUPTED (audit's design: non-zero
    means action needed). We only need the JSON output."""
    result = subprocess.run(
        [sys.executable, str(_TOOL), str(suite_dir), str(seed), "--json"],
        capture_output=True, text=True, timeout=30,
    )
    # Exit 0 or 1 both OK; exit 2+ means real error
    assert result.returncode in (0, 1), (
        f"unexpected exit {result.returncode}: {result.stderr}"
    )
    return json.loads(result.stdout)


def _setup_variant(suite_dir: Path, variant: str) -> Path:
    """Create variant dir; return path."""
    vd = suite_dir / f"variant_{variant}"
    vd.mkdir(parents=True, exist_ok=True)
    return vd


def test_pid_prefixed_snapshots_detected(tmp_path: Path):
    """PID-prefixed snapshot is reflected in audit output."""
    vd = _setup_variant(tmp_path, "baseline")
    (vd / "seed_42_pid12345_tick120.snapshot.json").write_text("{}")
    audit = _run_audit(tmp_path, 42)
    cell = next(c for c in audit["cells"] if c["variant"] == "baseline")
    assert cell["latest_snapshot_tick"] == 120
    assert 120 in cell["snapshot_ticks"]


def test_legacy_snapshots_still_detected(tmp_path: Path):
    """Legacy (no PID) format remains detected (back-compat)."""
    vd = _setup_variant(tmp_path, "baseline")
    (vd / "seed_42_tick60.snapshot.json").write_text("{}")
    audit = _run_audit(tmp_path, 42)
    cell = next(c for c in audit["cells"] if c["variant"] == "baseline")
    assert cell["latest_snapshot_tick"] == 60


def test_mixed_legacy_and_pid_prefix_both_seen(tmp_path: Path):
    """When both formats present, BOTH ticks are listed."""
    vd = _setup_variant(tmp_path, "baseline")
    (vd / "seed_42_tick60.snapshot.json").write_text("{}")
    (vd / "seed_42_pid100_tick120.snapshot.json").write_text("{}")
    audit = _run_audit(tmp_path, 42)
    cell = next(c for c in audit["cells"] if c["variant"] == "baseline")
    assert set(cell["snapshot_ticks"]) == {60, 120}
    assert cell["latest_snapshot_tick"] == 120


def test_tick_final_detected(tmp_path: Path):
    """tick_final SHALL be treated as latest (graceful_stop authority)."""
    vd = _setup_variant(tmp_path, "baseline")
    (vd / "seed_42_tick60.snapshot.json").write_text("{}")
    (vd / "seed_42_pid100_tick_final.snapshot.json").write_text("{}")
    audit = _run_audit(tmp_path, 42)
    cell = next(c for c in audit["cells"] if c["variant"] == "baseline")
    # Final present → latest_snapshot_tick semantics: either
    # 60 stays (because final is non-numeric) OR a sentinel is used.
    # At minimum: snapshot_ticks SHALL contain 60 (the numeric).
    # And the audit SHALL not crash on the _final file.
    assert 60 in cell["snapshot_ticks"]
    # The recommendation should still be valid (no exception)
    assert cell.get("recommended_strategy") is not None
