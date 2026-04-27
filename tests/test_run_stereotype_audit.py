"""Integration tests for tools/run_stereotype_audit.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "tools" / "run_stereotype_audit.py"
_OUT = _REPO / "data" / "calibration" / "stereotype_audit_report.json"


def _run_audit(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True, text=True, timeout=timeout, cwd=str(_REPO),
    )


class TestCLIArgs:

    def test_publishable_without_use_real_llm_exits_2(self):
        """publishable scale requires --use-real-llm to avoid weak claim."""
        result = _run_audit("--scale", "publishable", timeout=10)
        assert result.returncode == 2
        assert "requires --use-real-llm" in result.stderr


class TestDevMode:
    """dev mode is stub-only and should run in well under 30s."""

    @pytest.fixture(scope="class")
    def report(self):
        result = _run_audit("--scale", "dev", timeout=120)
        assert result.returncode == 0, result.stderr
        assert _OUT.exists()
        return json.loads(_OUT.read_text())

    def test_report_top_level_fields(self, report):
        assert "generated" in report
        assert report["scale"] == "dev"
        assert "swap_test" in report
        assert "blind_test" in report
        assert "cross_model_test" in report
        assert "overall_passed" in report
        assert isinstance(report["overall_passed"], bool)

    def test_swap_test_has_two_axes(self, report):
        axes = report["swap_test"]["axes"]
        assert "gender" in axes
        assert "ethnicity_group" in axes
        assert isinstance(axes["gender"]["passed"], bool)

    def test_swap_test_pairs_have_distance_fields(self, report):
        for axis_result in report["swap_test"]["axes"].values():
            for pair in axis_result["pairs"]:
                assert "from" in pair
                assert "to" in pair
                assert "destination_overlap_pct" in pair
                assert "passed" in pair
                assert 0.0 <= pair["destination_overlap_pct"] <= 1.0

    def test_blind_test_fields(self, report):
        bt = report["blind_test"]
        assert "passed" in bt
        assert "destination_overlap_pct" in bt
        assert bt["acceptance_threshold"] == 0.80
        assert bt["blinded_attribute"] == "ethnicity_group"

    def test_cross_model_skipped_in_dev_mode(self, report):
        ct = report["cross_model_test"]
        assert "skipped" in ct.get("state", "").lower()

    def test_dev_mode_acceptance_level(self, report):
        # dev mode tags as dev_only regardless of pass/fail
        assert report["acceptance_level"] in ("dev_only", "failing")

    def test_stub_mode_swap_pairs_all_pass(self, report):
        """Stub LLM doesn't read profile fields, so swap should yield overlap=1.0."""
        for axis_result in report["swap_test"]["axes"].values():
            for pair in axis_result["pairs"]:
                assert pair["passed"], (
                    f"stub-mode swap pair {pair['from']}→{pair['to']} "
                    f"failed with overlap={pair['destination_overlap_pct']}; "
                    "indicates RNG seed leakage in scripted_plan"
                )


class TestSchemaCompletenessForPublishableContract:
    """If publishable suite reads this report, it relies on the schema."""

    def test_required_keys_present(self):
        result = _run_audit("--scale", "dev", timeout=120)
        assert result.returncode == 0
        report = json.loads(_OUT.read_text())
        # Contract for publishable suite report integration:
        assert isinstance(report.get("overall_passed"), bool)
        assert isinstance(report.get("scale"), str)
        for protocol in ("swap_test", "blind_test", "cross_model_test"):
            assert protocol in report, f"missing protocol section: {protocol}"
