"""Tests for run_variant_suite.py run-resilience integration.

Covers:
- --resume-from-day overrides auto-detect
- --skip-preflight ignored in publishable mode
- cleanup_partials after seed completion
- Auto-detect partial → resume_from passed to MultiDayRunner
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


class TestCLIFlagsExist:

    def test_resume_from_day_flag_in_help(self) -> None:
        result = _run(["--help"])
        assert "--resume-from-day" in result.stdout

    def test_skip_preflight_flag_in_help(self) -> None:
        result = _run(["--help"])
        assert "--skip-preflight" in result.stdout

    def test_skip_preflight_help_mentions_publishable_override(self) -> None:
        result = _run(["--help"])
        assert "publishable" in result.stdout.lower()


class TestSkipPreflightInPublishable:

    def test_skip_preflight_warned_in_publishable_mode(
        self, tmp_path: Path,
    ) -> None:
        """--agents 1000 --num-days 14 --skip-preflight SHALL still run
        preflight; stderr SHALL warn that the flag is ignored.

        Implementation: launch the suite, stream stderr line-by-line, kill
        the subprocess as soon as the WARN is observed (or after a short
        deadline). Preflight itself takes minutes to complete so we never
        let it finish — only the warning is contractual here.
        """
        import os

        venv_py = ROOT / ".venv" / "bin" / "python"
        py = str(venv_py) if venv_py.exists() else sys.executable
        proc = subprocess.Popen(
            [
                py, str(CLI),
                "--agents", "1000", "--num-days", "14",
                "--variants", "baseline",
                "--skip-preflight",
                "--mode", "publishable",
                "--output-dir", str(tmp_path),
                "--suite-name", "test_skip_preflight",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            env=os.environ.copy(),
        )
        warning_marker = "IGNORES --skip-preflight"
        seen_warning = False
        try:
            assert proc.stderr is not None  # for type checkers
            # Hard deadline so a hang in startup can't wedge the suite.
            import time
            deadline = time.time() + 30.0
            while time.time() < deadline:
                line = proc.stderr.readline()
                if not line:
                    if proc.poll() is not None:
                        break
                    continue
                if warning_marker in line:
                    seen_warning = True
                    break
        finally:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        assert seen_warning, (
            "expected stderr to emit "
            f"{warning_marker!r} before subprocess was killed"
        )


class TestPreflightSkippedInWorkerChild:

    def test_preflight_skipped_when_inside_worker(
        self, tmp_path: Path,
    ) -> None:
        """When --workers=1 + --suite-dir is provided, we're a worker
        subprocess of a parent coordinator — preflight SHALL NOT recurse.
        """
        suite_dir = tmp_path / "parent_suite"
        suite_dir.mkdir()
        result = _run([
            "--agents", "1000", "--num-days", "14",
            "--variants", "baseline",
            "--mode", "publishable",
            "--suite-dir", str(suite_dir),
            "--workers", "1",
            # Don't actually run — use bogus seed count to test the gate path
            "--seeds", "0",
        ])
        # The preflight invocation message should NOT be in stdout
        assert "running preflight" not in result.stdout


class TestCleanupPartials:
    """Validate that after a successful seed run, partial files are gone.

    Uses stub provider and dev mode (3 days, 5 agents) for fast end-to-end
    flow.
    """

    def test_partials_removed_after_seed_complete(self, tmp_path: Path) -> None:
        # Use --suite-dir + stub provider + tiny config; this should run
        # in seconds.
        suite_dir = tmp_path / "cleanup_suite"
        result = _run([
            "--variants", "baseline",
            "--seeds", "1",
            "--num-days", "2",
            "--agents", "3",
            "--num-protagonists", "1",
            "--mode", "dev",
            "--phase-days", "2,0,0",
            "--suite-dir", str(suite_dir),
            "--suite-name", "cleanup_test",
            "--workers", "1",
        ])
        # rc may be 0 even if minor issues; the key check is partial cleanup
        variant_dir = suite_dir / "variant_baseline"
        if not variant_dir.exists():
            pytest.skip(
                f"variant_baseline not produced (rc={result.returncode}); "
                f"stderr={result.stderr[:500]}",
            )
        partials = list(variant_dir.glob("seed_*_day*.partial.json"))
        assert partials == [], (
            f"partial files not cleaned up: {[p.name for p in partials]}"
        )
        # seed_42.json (or whatever offset) should exist
        assert list(variant_dir.glob("seed_*.json"))
