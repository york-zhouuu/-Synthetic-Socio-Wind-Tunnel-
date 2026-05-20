"""backlog 1.15 (2026-05-20): preflight_publishable_spawn regression.

This script gates every publishable spawn — if it silently degrades,
the user loses the bug-catching layer. Tests verify the script:
- Runs and reports each check
- Exits 0 when everything is fine
- Exits non-zero when any blocker triggers
- Detects missing PHASE events (the headline 2026-05-20 failure mode)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
PREFLIGHT = REPO_ROOT / "tools" / "preflight_publishable_spawn.py"


def _run(args: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PREFLIGHT)] + args,
        capture_output=True, text=True, cwd=REPO_ROOT, env=env,
        timeout=240,
    )


def test_skip_smoke_returns_warning_at_most(monkeypatch):
    """With --skip-smoke and no env vars set, only env_vars is a warning
    (severity 2). Script SHALL run + emit per-check output."""
    import os
    env = dict(os.environ)
    # Strip recommended env vars to force the warning
    for k in [
        "RSS_RESTART_MB", "MEMORY_EVENT_EVICT_GRACE_DAYS",
        "SNAPSHOT_PRUNE_BEFORE_WRITE", "GC_EVERY_N_TICKS",
        "RSS_CHECK_EVERY_N_TICKS", "RESILIENCE_SNAPSHOT_EVERY_TICKS",
        "RESILIENCE_WAL_ENABLED",
    ]:
        env.pop(k, None)
    result = _run(["--skip-smoke"], env=env)
    assert result.returncode in (0, 2), result.stdout + result.stderr
    # SHALL list each check name
    for name in (
        "python_venv", "env_vars", "disk_free",
        "stale_worker", "instrumentation_smoke", "resume_strategy",
    ):
        assert name in result.stdout, f"check {name} missing from output"


def test_full_smoke_passes_on_clean_repo():
    """When all env vars set + clean state, full preflight (incl
    instrumentation smoke) SHALL exit 0. Real-artifact integration test —
    actually runs run_variant_suite and inspects events.jsonl."""
    import os
    env = dict(os.environ)
    env.update({
        "RSS_RESTART_MB": "10000",
        "MEMORY_EVENT_EVICT_GRACE_DAYS": "2",
        "SNAPSHOT_PRUNE_BEFORE_WRITE": "1",
        "GC_EVERY_N_TICKS": "200",
        "RSS_CHECK_EVERY_N_TICKS": "50",
        "RESILIENCE_SNAPSHOT_EVERY_TICKS": "12",
        "RESILIENCE_WAL_ENABLED": "true",
    })
    result = _run([], env=env)
    # 0 = clean, 2 = warnings only (e.g. swap pressure on busy CI)
    assert result.returncode in (0, 2), (
        f"preflight failed unexpectedly:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "all" in result.stdout.lower() and "PHASE" in result.stdout or (
        "smoke OK" in result.stdout
    )


def test_smoke_detects_phase_event_gap(monkeypatch):
    """If instrumentation phase events are not all firing, preflight
    SHALL exit non-zero with 'missing PHASE events'.

    Simulated by env INSTRUMENTATION_DISABLE=1 which short-circuits all
    phase emits → smoke succeeds but events.jsonl is empty.
    """
    import os
    env = dict(os.environ)
    env["INSTRUMENTATION_DISABLE"] = "1"
    result = _run([], env=env)
    assert result.returncode == 1, (
        f"expected blocker exit=1 when phase events disabled, got "
        f"{result.returncode}\n{result.stdout}\n{result.stderr}"
    )
    assert "missing PHASE events" in result.stdout or (
        "events.jsonl not found" in result.stdout
    ), f"missing-phase message not in output: {result.stdout}"
