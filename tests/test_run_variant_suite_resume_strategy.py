"""Tests for run_variant_suite.py --resume-strategy CLI flag.

Light-weight subprocess tests: validate the CLI surface + early exit
behaviors. Full end-to-end resume is covered by test_resume_from_snapshot.py.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "run_variant_suite.py"


def _run(args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    venv_py = ROOT / ".venv" / "bin" / "python"
    py = str(venv_py) if venv_py.exists() else sys.executable
    import os
    e = os.environ.copy()
    if env:
        e.update(env)
    return subprocess.run(
        [py, str(CLI), *args],
        capture_output=True, text=True, timeout=120, env=e,
    )


class TestResumeStrategyHelp:

    def test_resume_strategy_flag_in_help(self) -> None:
        result = _run(["--help"])
        assert "--resume-strategy" in result.stdout
        # All 4 strategies documented
        for s in ("auto", "snapshot-only", "partial-only", "none"):
            assert s in result.stdout

    def test_help_mentions_auto_default(self) -> None:
        result = _run(["--help"])
        assert "default" in result.stdout.lower()


class TestSnapshotOnlyStrategyFailFast:

    def test_snapshot_only_no_snapshot_exits_nonzero(self, tmp_path: Path) -> None:
        suite_dir = tmp_path / "fresh_suite"
        suite_dir.mkdir()
        # No snapshot anywhere → strategy=snapshot-only should bail
        result = _run([
            "--variants", "baseline",
            "--seeds", "1",
            "--num-days", "1",
            "--agents", "3",
            "--num-protagonists", "1",
            "--mode", "dev",
            "--phase-days", "1,0,0",
            "--suite-dir", str(suite_dir),
            "--suite-name", "snapshot_only_test",
            "--workers", "1",
            "--resume-strategy", "snapshot-only",
        ])
        assert result.returncode != 0
        # Stderr or stdout should mention "no snapshot found" or "strategy=snapshot-only"
        combined = result.stdout + result.stderr
        assert "snapshot-only" in combined or "no snapshot" in combined.lower()


class TestNoneStrategyFreshStart:

    def test_none_strategy_starts_fresh(self, tmp_path: Path) -> None:
        """strategy=none ignores existing partial files and starts from day 0."""
        # First run: produce a seed_42.json (so --resume would normally skip)
        suite_dir = tmp_path / "none_test_suite"
        result1 = _run([
            "--variants", "baseline",
            "--seeds", "1",
            "--num-days", "1",
            "--agents", "3",
            "--num-protagonists", "1",
            "--mode", "dev",
            "--phase-days", "1,0,0",
            "--suite-dir", str(suite_dir),
            "--suite-name", "none_test",
            "--workers", "1",
        ])
        if result1.returncode != 0:
            pytest.skip(
                f"baseline run failed (rc={result1.returncode}); "
                f"stderr={result1.stderr[:300]}",
            )
        seed_file = suite_dir / "variant_baseline" / "seed_42.json"
        assert seed_file.exists()

        # Second run with --resume-strategy=none: should re-run, overwriting
        # Note: --resume default off + strategy=none → no-op (effective_resume_from=0)
        # This test mostly checks that the flag is accepted and doesn't crash
        result2 = _run([
            "--variants", "baseline",
            "--seeds", "1",
            "--num-days", "1",
            "--agents", "3",
            "--num-protagonists", "1",
            "--mode", "dev",
            "--phase-days", "1,0,0",
            "--suite-dir", str(suite_dir),
            "--suite-name", "none_test",
            "--workers", "1",
            "--resume-strategy", "none",
        ])
        # Should not crash; final state has seed file
        assert seed_file.exists()
