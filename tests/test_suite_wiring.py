"""E2E wiring tests — variants actually change agent behavior."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SUITE_CLI = REPO_ROOT / "tools" / "run_variant_suite.py"

# Add tools/ to import path
sys.path.insert(0, str(REPO_ROOT / "tools"))


def _import_run_helper():
    """Import run_seed_with_metrics from tools/run_variant_suite."""
    import importlib
    if "run_variant_suite" in sys.modules:
        del sys.modules["run_variant_suite"]
    mod = importlib.import_module("run_variant_suite")
    return mod.run_seed_with_metrics


class TestReplanCountPropagation:
    def test_baseline_replan_count_is_zero(self):
        run_seed = _import_run_helper()
        _result, run_metrics, _meta = run_seed(
            seed=42, n_agents=10, start_date=date(2026, 4, 25),
            num_days=3, mode="dev", variant_name="baseline",
            phase_days="1,1,1",
        )
        ext = run_metrics.extensions
        assert ext["replan_count"] == 0
        assert ext["replan_by_day"] == [0, 0, 0]

    def test_hyperlocal_push_replan_count_positive(self):
        run_seed = _import_run_helper()
        _result, run_metrics, _meta = run_seed(
            seed=42, n_agents=10, start_date=date(2026, 4, 25),
            num_days=3, mode="dev", variant_name="hyperlocal_push",
            phase_days="1,1,1",
        )
        ext = run_metrics.extensions
        assert ext["replan_count"] > 0
        assert sum(ext["replan_by_day"]) == ext["replan_count"]
        # by_day 长度 == num_days
        assert len(ext["replan_by_day"]) == 3
        # intervention day(day 1) 应有 replan；baseline day 0 不应
        assert ext["replan_by_day"][0] == 0

    def test_sum_equals_total(self):
        run_seed = _import_run_helper()
        _result, run_metrics, _meta = run_seed(
            seed=42, n_agents=10, start_date=date(2026, 4, 25),
            num_days=3, mode="dev", variant_name="hyperlocal_push",
            phase_days="1,1,1",
        )
        ext = run_metrics.extensions
        assert ext["replan_count"] == sum(ext["replan_by_day"])


class TestBehavioralDifference:
    """suite-wiring 的核心成功信号：variant 真的改变 agent 行为。"""

    def test_hyperlocal_push_lower_deviation_than_global_distraction(self):
        """H_info 方向断言：推 hyperlocal → agent 离 target 更近；
        推 global news → agent 不被拉动，保持 baseline 距离。"""
        run_seed = _import_run_helper()
        _r_hp, m_hp, _ = run_seed(
            seed=42, n_agents=20, start_date=date(2026, 4, 25),
            num_days=3, mode="dev", variant_name="hyperlocal_push",
            phase_days="1,1,1",
        )
        _r_gd, m_gd, _ = run_seed(
            seed=42, n_agents=20, start_date=date(2026, 4, 25),
            num_days=3, mode="dev", variant_name="global_distraction",
            phase_days="1,1,1",
        )
        # H_info 方向：hp 距离 < gd 距离
        assert m_hp.trajectory_deviation_m is not None
        assert m_gd.trajectory_deviation_m is not None
        assert m_hp.trajectory_deviation_m < m_gd.trajectory_deviation_m, (
            f"hp {m_hp.trajectory_deviation_m} should be < gd "
            f"{m_gd.trajectory_deviation_m}"
        )

    def test_hyperlocal_push_replan_vs_baseline(self):
        run_seed = _import_run_helper()
        _r_bl, m_bl, _ = run_seed(
            seed=42, n_agents=20, start_date=date(2026, 4, 25),
            num_days=3, mode="dev", variant_name="baseline",
            phase_days="1,1,1",
        )
        _r_hp, m_hp, _ = run_seed(
            seed=42, n_agents=20, start_date=date(2026, 4, 25),
            num_days=3, mode="dev", variant_name="hyperlocal_push",
            phase_days="1,1,1",
        )
        assert m_bl.extensions["replan_count"] == 0
        assert m_hp.extensions["replan_count"] > 0


class TestRealLLMFlag:
    def test_without_flag_no_anthropic_import_needed(self, tmp_path: Path):
        """Default --use-real-llm off: CLI runs even without anthropic installed."""
        # Pass a marker env to ensure subprocess doesn't try to import anthropic
        result = subprocess.run(
            [
                sys.executable, str(SUITE_CLI),
                "--variants", "baseline",
                "--seeds", "1", "--num-days", "3", "--agents", "5",
                "--mode", "dev", "--phase-days", "1,1,1",
                "--output-dir", str(tmp_path),
                "--suite-name", "no_llm_smoke",
            ],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        assert result.returncode == 0, result.stdout + result.stderr


class TestDumpFields:
    def test_seed_json_has_replan_extensions(self, tmp_path: Path):
        """Run the CLI; verify dumped seed JSON has replan_count/replan_by_day."""
        result = subprocess.run(
            [
                sys.executable, str(SUITE_CLI),
                "--variants", "hyperlocal_push",
                "--seeds", "1", "--num-days", "3", "--agents", "10",
                "--mode", "dev", "--phase-days", "1,1,1",
                "--output-dir", str(tmp_path),
                "--suite-name", "dump_check",
            ],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        assert result.returncode == 0, result.stdout + result.stderr

        suite_dirs = list(tmp_path.glob("*_dump_check"))
        assert len(suite_dirs) == 1
        seed_files = list((suite_dirs[0] / "variant_hyperlocal_push").glob("seed_*.json"))
        assert len(seed_files) == 1
        data = json.loads(seed_files[0].read_text(encoding="utf-8"))
        ext = data["run_metrics"]["extensions"]
        assert "replan_count" in ext
        assert "replan_by_day" in ext
