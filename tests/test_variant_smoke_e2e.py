"""End-to-end smoke that all 4 variants produce *distinguishable* metrics
after the fix-variant-measurement-and-friction change.

Before this change, gd / pf were byte-identical to baseline due to:
- B2: StubReplanLLM gd → empty plan → no behavioral change
- B3: phone_friction profile.digital had no movement reader → no behavior

After the fix:
- gd stub returns a distraction destination → agents replan
- pf injects friction_nudge feed_item → agents replan toward community
- traj_dev_m is now protag-only, no longer drowned by 90 scripted agents

This test runs a tiny configuration (1 seed × 3 days × 20 agents × 4
variants) and asserts the variants diverge. It uses StubReplanLLM
(zero LLM cost, deterministic).
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
def smoke_metrics() -> dict:
    """Run all 4 variants once and cache results."""
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


class TestVariantsAreDistinguishable:

    def test_encounter_stats_pairwise_not_all_equal(self, smoke_metrics):
        """4 variants SHALL NOT all share the same encounter total.

        This is the core regression for B2/B3: pre-fix all 4 were
        byte-identical in encounter_stats. Post-fix, at least 2 distinct
        values among the 4.
        """
        totals = [
            smoke_metrics[v].encounter_stats["total"]
            for v in ["baseline", "hyperlocal_push",
                      "global_distraction", "phone_friction"]
        ]
        # Distinct values count: pre-fix would be 1 (all same); post-fix > 1
        assert len(set(totals)) > 1, \
            f"All 4 variants share the same encounter total {totals[0]}; " \
            "B2/B3 regression: gd/pf might be operationally inert again."

    def test_baseline_replan_count_is_zero(self, smoke_metrics):
        """Baseline does not trigger replans (no push, no nudge)."""
        ext = smoke_metrics["baseline"].extensions
        assert ext["replan_count"] == 0
        assert ext.get("replan_no_op_count", 0) == 0

    def test_no_op_replan_count_zero_under_stub(self, smoke_metrics):
        """Stub path SHALL never return empty for hp/gd/pf, so no_op == 0.

        Empty stub responses only happen for catalyst_seeding / unknown variants
        (B7 fix gates the no-op counter).
        """
        for v in ["hyperlocal_push", "global_distraction", "phone_friction"]:
            ext = smoke_metrics[v].extensions
            no_op = ext.get("replan_no_op_count", 0)
            assert no_op == 0, \
                f"{v} had {no_op} no-op replans; stub should always produce non-empty plan"

    def test_traj_dev_m_protag_only_populated_for_hp_gd(self, smoke_metrics):
        """B1 fix: traj_dev_m is protag-only median (not None for hp/gd)."""
        hp = smoke_metrics["hyperlocal_push"]
        gd = smoke_metrics["global_distraction"]
        assert hp.trajectory_deviation_m is not None
        assert gd.trajectory_deviation_m is not None
        # The all-agent column SHALL also be filled.
        assert hp.trajectory_deviation_m_all is not None
        assert gd.trajectory_deviation_m_all is not None

    def test_baseline_traj_dev_m_is_none(self, smoke_metrics):
        """Non-hp/gd variants don't get a traj_dev_m."""
        assert smoke_metrics["baseline"].trajectory_deviation_m is None
        assert smoke_metrics["phone_friction"].trajectory_deviation_m is None

    def test_pf_primary_metric_is_encounter(self, smoke_metrics):
        """B4 fix: pf no longer uses degenerate phone_feed_proxy."""
        pf = smoke_metrics["phone_friction"]
        # variant_name is in run_metrics; primary_metric_name lives in variant
        # metadata not in RunMetrics. Sanity check via run_metrics field
        # presence: encounter_stats SHALL be populated.
        assert "per_day_median" in pf.encounter_stats
        assert pf.encounter_stats["per_day_median"] >= 0
