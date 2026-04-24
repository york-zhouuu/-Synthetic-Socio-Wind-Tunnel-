"""E2E smoke for tools/run_variant_suite.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
CLI = REPO_ROOT / "tools" / "run_variant_suite.py"


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI)] + args,
        capture_output=True, text=True, cwd=REPO_ROOT,
    )


class TestCLIValidation:
    def test_unknown_variant_exits_nonzero(self, tmp_path: Path):
        result = _run_cli([
            "--variants", "unknown_foo",
            "--seeds", "1", "--num-days", "1", "--agents", "5",
            "--mode", "dev", "--phase-days", "1,0,0",
            "--output-dir", str(tmp_path),
            "--suite-name", "invalid_smoke",
        ])
        assert result.returncode != 0
        assert "unknown" in (result.stdout + result.stderr).lower()


@pytest.mark.slow
class TestCLIMinimalSmoke:
    """Heaviest test in this module — runs actual simulation; ~2s."""

    def test_two_variant_suite_produces_all_artifacts(self, tmp_path: Path):
        result = _run_cli([
            "--variants", "baseline,hyperlocal_push",
            "--seeds", "2", "--num-days", "3", "--agents", "10",
            "--mode", "dev", "--phase-days", "1,1,1",
            "--output-dir", str(tmp_path),
            "--suite-name", "e2e_smoke",
        ])
        assert result.returncode == 0, result.stdout + result.stderr

        # Find suite dir under tmp_path
        suite_dirs = list(tmp_path.glob("*_e2e_smoke"))
        assert len(suite_dirs) == 1
        suite_dir = suite_dirs[0]

        # Variant dirs + seed files
        baseline_dir = suite_dir / "variant_baseline"
        hp_dir = suite_dir / "variant_hyperlocal_push"
        assert baseline_dir.is_dir()
        assert hp_dir.is_dir()
        assert len(list(baseline_dir.glob("seed_*.json"))) == 2
        assert len(list(hp_dir.glob("seed_*.json"))) == 2
        assert (baseline_dir / "aggregate.json").exists()
        assert (hp_dir / "aggregate.json").exists()

        # Contest + report
        contest_file = suite_dir / "contest.json"
        report_file = suite_dir / "report.md"
        assert contest_file.exists()
        assert report_file.exists()

        # Contest JSON has 2 rows
        data = json.loads(contest_file.read_text(encoding="utf-8"))
        assert len(data["rows"]) == 2
        names = {r["variant_name"] for r in data["rows"]}
        assert names == {"baseline", "hyperlocal_push"}

        # Report contains five acts
        text = report_file.read_text(encoding="utf-8")
        for act in ("Act 1", "Act 2", "Act 3", "Act 4", "Act 5"):
            assert act in text
