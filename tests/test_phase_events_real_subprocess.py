"""G1 — subprocess dev smoke verifies all PHASE events fire from real
worker code paths (not just emit API).

This is the test that would have caught the 2026-05-20 wiring gap.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parents[1]


@pytest.mark.slow
def test_dev_smoke_emits_all_phase_events_in_order(tmp_path: Path) -> None:
    """Run real dev smoke subprocess; verify events.jsonl phase order."""
    suite_dir = tmp_path / "smoke_phase"
    suite_dir.mkdir()
    variant_dir = suite_dir / "variant_baseline"
    variant_dir.mkdir()

    env = os.environ.copy()
    env.pop("INSTRUMENTATION_OUTPUT_DIR", None)  # let runtime default
    env.pop("INSTRUMENTATION_SEED", None)
    env["INSTRUMENTATION_DISABLE"] = ""  # ensure enabled
    # Use short cadence so we get plenty of samples in the smoke
    env["INSTRUMENTATION_SAMPLE_EVERY_N_TICKS"] = "12"
    # Make sure llm calls don't pollute (we don't assert LLM here)
    env["LLM_SAMPLE_RATE"] = "0.01"

    cmd = [
        sys.executable, "tools/run_variant_suite.py",
        "--variants", "baseline",
        "--seeds", "1", "--seed-start", "42",
        "--num-days", "1", "--agents", "50",
        "--num-protagonists", "25",
        "--mode", "dev", "--phase-days", "1,0,0",
        "--output-dir", str(tmp_path),
        "--suite-name", "smoke_phase",
        "--skip-preflight",
    ]
    result = subprocess.run(
        cmd, env=env, capture_output=True, text=True,
        timeout=180, cwd=str(_REPO),
    )
    assert result.returncode == 0, (
        f"smoke failed: rc={result.returncode}\nstderr={result.stderr[-2000:]}"
    )

    # Find the actual variant_baseline dir (suite name is timestamp-prefixed)
    suite_dirs = list(tmp_path.glob("*_smoke_phase"))
    assert len(suite_dirs) == 1, f"expected 1 suite dir, got {suite_dirs}"
    actual_variant_dir = suite_dirs[0] / "variant_baseline"
    events_path = actual_variant_dir / "seed_42.events.jsonl"
    assert events_path.exists(), (
        f"events.jsonl missing at {events_path}; "
        f"actual_variant_dir contents: {list(actual_variant_dir.iterdir())}"
    )

    events = [json.loads(l) for l in events_path.read_text().splitlines() if l]
    phases = [
        e["phase"] for e in events
        if e.get("kind") == "PHASE"
    ]

    # Required phases for a non-resume dev smoke run
    required_in_order = [
        "PROCESS_START", "SETUP_START", "SETUP_DONE",
        "TICK_LOOP_START", "DAY_START", "DAY_END", "EXIT",
    ]
    # Check each required phase appears, in the right order
    seen = []
    for p in phases:
        if p in required_in_order and p not in seen:
            seen.append(p)
    assert seen == required_in_order, (
        f"phase event order mismatch:\n"
        f"  expected: {required_in_order}\n"
        f"  got:      {seen}\n"
        f"  all phases: {phases}"
    )


@pytest.mark.slow
def test_setup_done_has_duration_and_rss_delta(tmp_path: Path) -> None:
    """SETUP_DONE event SHALL include duration_sec and rss_before/after."""
    suite_dir = tmp_path / "smoke_setup"
    suite_dir.mkdir()
    variant_dir = suite_dir / "variant_baseline"
    variant_dir.mkdir()

    env = os.environ.copy()
    env.pop("INSTRUMENTATION_OUTPUT_DIR", None)  # let runtime default
    env.pop("INSTRUMENTATION_SEED", None)
    env["INSTRUMENTATION_DISABLE"] = ""  # ensure enabled
    env["LLM_SAMPLE_RATE"] = "0"

    cmd = [
        sys.executable, "tools/run_variant_suite.py",
        "--variants", "baseline",
        "--seeds", "1", "--seed-start", "42",
        "--num-days", "1", "--agents", "30",
        "--num-protagonists", "10",
        "--mode", "dev", "--phase-days", "1,0,0",
        "--output-dir", str(tmp_path),
        "--suite-name", "smoke_setup",
        "--skip-preflight",
    ]
    result = subprocess.run(
        cmd, env=env, capture_output=True, text=True,
        timeout=180, cwd=str(_REPO),
    )
    assert result.returncode == 0, result.stderr[-2000:]

    suite_dirs = list(tmp_path.glob("*_smoke_setup"))
    events_path = (
        suite_dirs[0] / "variant_baseline" / "seed_42.events.jsonl"
    )
    events = [json.loads(l) for l in events_path.read_text().splitlines() if l]
    setup_done = [
        e for e in events
        if e.get("kind") == "PHASE" and e.get("phase") == "SETUP_DONE"
    ]
    assert len(setup_done) >= 1
    ev = setup_done[0]
    assert "duration_sec" in ev
    assert ev["duration_sec"] >= 0
    assert "rss_before_mb" in ev
    assert "rss_after_mb" in ev
    # Setup typically grows RSS as state is loaded
    assert ev["rss_after_mb"] >= ev["rss_before_mb"]
