"""G2 — subprocess dev smoke verifies memstat sampling actually fires.

This would have caught 2026-05-20 02:08 wiring gap where memstat.jsonl
was 0 lines despite spec claiming "every N tick".
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parents[1]


def _run_smoke(
    tmp_path: Path, *, suite_name: str = "smoke_memstat",
    extra_env: dict | None = None, agents: int = 50, num_days: int = 1,
) -> Path:
    """Run dev smoke subprocess; return variant_baseline output dir."""
    env = os.environ.copy()
    env.pop("INSTRUMENTATION_OUTPUT_DIR", None)  # let runtime default
    env.pop("INSTRUMENTATION_SEED", None)
    env["INSTRUMENTATION_SAMPLE_EVERY_N_TICKS"] = "12"
    env["LLM_SAMPLE_RATE"] = "0.01"
    if extra_env:
        env.update(extra_env)

    cmd = [
        sys.executable, "tools/run_variant_suite.py",
        "--variants", "baseline",
        "--seeds", "1", "--seed-start", "42",
        "--num-days", str(num_days), "--agents", str(agents),
        "--num-protagonists", str(max(10, agents // 2)),
        "--mode", "dev", "--phase-days",
        f"{num_days},0,0" if num_days <= 1 else "1,1,1",
        "--output-dir", str(tmp_path),
        "--suite-name", suite_name,
        "--skip-preflight",
    ]
    result = subprocess.run(
        cmd, env=env, capture_output=True, text=True,
        timeout=180, cwd=str(_REPO),
    )
    assert result.returncode == 0, (
        f"smoke failed: rc={result.returncode}\n"
        f"stderr={result.stderr[-2000:]}"
    )
    suite_dirs = list(tmp_path.glob(f"*_{suite_name}"))
    assert len(suite_dirs) == 1
    return suite_dirs[0] / "variant_baseline"


@pytest.mark.slow
def test_dev_smoke_produces_memstat_samples(tmp_path: Path) -> None:
    """288 tick / 12 = 24 expected samples. Allow some slack for
    early-tick skip + completion timing → ≥ 15."""
    out_dir = _run_smoke(tmp_path)
    memstat_path = out_dir / "seed_42.memstat.jsonl"
    assert memstat_path.exists(), (
        f"memstat.jsonl missing — sample_metrics wiring broken. "
        f"dir contents: {list(out_dir.iterdir())}"
    )
    samples = [
        json.loads(l) for l in memstat_path.read_text().splitlines() if l
    ]
    assert len(samples) >= 15, (
        f"expected ≥ 15 memstat samples (288 tick / 12), "
        f"got {len(samples)}"
    )


@pytest.mark.slow
def test_memstat_total_events_reflects_live_service(tmp_path: Path) -> None:
    """Last sample's memory_store.total_events SHALL be > 0 — proving
    that live MemoryService is being read, not a placeholder default."""
    out_dir = _run_smoke(
        tmp_path, suite_name="smoke_memstat_live", agents=50,
    )
    memstat_path = out_dir / "seed_42.memstat.jsonl"
    samples = [
        json.loads(l) for l in memstat_path.read_text().splitlines() if l
    ]
    assert samples, "no samples"
    last = samples[-1]
    total_events = last.get("memory_store", {}).get("total_events", 0)
    assert total_events > 0, (
        f"memory_store.total_events=0 in last sample — sample_metrics "
        f"is not actually reading the live MemoryService. "
        f"Full memory_store field: {last.get('memory_store')}"
    )


@pytest.mark.slow
def test_instrumentation_disable_skips_memstat(tmp_path: Path) -> None:
    """env=1 → no memstat file (or empty)."""
    out_dir = _run_smoke(
        tmp_path, suite_name="smoke_memstat_off",
        extra_env={"INSTRUMENTATION_DISABLE": "1"},
    )
    memstat_path = out_dir / "seed_42.memstat.jsonl"
    if memstat_path.exists():
        content = memstat_path.read_text().strip()
        assert content == "", (
            f"INSTRUMENTATION_DISABLE=1 but memstat.jsonl has content"
        )
