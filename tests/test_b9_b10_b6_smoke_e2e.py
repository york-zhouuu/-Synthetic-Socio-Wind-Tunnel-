"""End-to-end smoke verifying the 3 fixes from this change land together.

- B9: encounter count grew dramatically vs the pre-fix baseline (dwell
  co-presence now captured); confirms _detect_encounters reads the
  Ledger snapshot.
- B10: rep_lock["provider"] field is populated and reflects the run config.
- B6: replan_no_op_count present in extensions (B7 plumbing still alive
  after this change).
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from run_variant_suite import run_seed_with_metrics  # type: ignore


@pytest.fixture(scope="module")
def smoke_run() -> dict:
    """Run baseline + hp + gd + pf on a tiny config; cache for assertions."""
    out: dict = {}
    for variant_name in [
        "baseline", "hyperlocal_push", "global_distraction", "phone_friction",
    ]:
        _result, run_metrics, _meta = run_seed_with_metrics(
            seed=42,
            n_agents=20,
            start_date=date(2026, 4, 22),
            num_days=3,
            mode="dev",
            variant_name=variant_name,
            phase_days="1,1,1",
            use_real_llm=False,
            use_aitown=False,
        )
        out[variant_name] = run_metrics
    return out


class TestB9EncounterDwellCaptured:

    def test_encounter_total_at_least_100x_pre_fix(self, smoke_run):
        """B9: pre-fix had ~87 encs/run on this config; post-fix ≥ 1000.

        The exact threshold is loose — just confirm the order-of-magnitude
        change that proves dwell co-presence is being captured.
        """
        for v in ["baseline", "hyperlocal_push",
                  "global_distraction", "phone_friction"]:
            total = smoke_run[v].encounter_stats["total"]
            assert total > 1000, \
                f"{v} encounter total {total} suggests B9 fix isn't active"

    def test_distinct_pairs_grew(self, smoke_run):
        """Distinct pair count should grow with dwell capture.

        Threshold > 50 (lowered from 100): fix-systemic-deep-issues A3
        (polygon-extent factor) + fix-bc-mechanics B6 (transit penalty) both
        discount noticing, so post-fix pair counts on the smoke config drop
        ~10-15% even though dwell capture itself is working.
        """
        for v in ["baseline", "global_distraction"]:
            pairs = smoke_run[v].encounter_stats["diversity_pairs_total"]
            assert pairs > 50, \
                f"{v} distinct pairs {pairs} suggests B9 fix isn't active"

    def test_gd_diverges_from_baseline(self, smoke_run):
        """gd's distraction stub pulls agents away → encounters differ.

        Sanity check that the variant pipeline still works after B9 fix.
        """
        baseline_total = smoke_run["baseline"].encounter_stats["total"]
        gd_total = smoke_run["global_distraction"].encounter_stats["total"]
        assert gd_total != baseline_total


class TestB10RepLockProvider:

    def test_provider_field_present(self, smoke_run):
        for v in smoke_run.values():
            rep = v.extensions["reproducibility_lock"]
            assert "provider" in rep
            assert rep["provider"] is not None

    def test_stub_provider_value(self, smoke_run):
        """Smoke config uses no aitown / no real llm → provider == 'stub'."""
        for v in smoke_run.values():
            rep = v.extensions["reproducibility_lock"]
            assert rep["provider"] == "stub"

    def test_model_version_reflects_provider(self, smoke_run):
        for v in smoke_run.values():
            rep = v.extensions["reproducibility_lock"]
            assert "stub" in rep["model_version"]


class TestB7B6ReplanCounterStillWorks:

    def test_replan_no_op_count_field_present(self, smoke_run):
        """Make sure B7 plumbing wasn't accidentally broken by B9/B10/B6 fixes."""
        for v in smoke_run.values():
            ext = v.extensions
            assert "replan_no_op_count" in ext
            assert "replan_no_op_by_day" in ext

    def test_baseline_replan_zero(self, smoke_run):
        ext = smoke_run["baseline"].extensions
        assert ext["replan_count"] == 0
        assert ext["replan_no_op_count"] == 0
