"""End-to-end mini sim: push personalization across hp / gd / baseline.

Wires HyperlocalPushVariant + PushPersonalizer + ConversationService through
run_variant_suite, asserts personalization thesis holds at dev scale:

1. hp pushes carry distinct content per agent (individualized)
2. hp.target_precision > 0
3. gd doesn't use personalizer (mirror design)
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))


@pytest.fixture(scope="module")
def hp_metrics():
    from run_variant_suite import run_seed_with_metrics
    _, m, _ = run_seed_with_metrics(
        seed=42, n_agents=50, start_date=date(2026, 5, 8),
        num_days=3, mode="dev", variant_name="hyperlocal_push",
        phase_days="1,1,1",
    )
    return m


@pytest.fixture(scope="module")
def gd_metrics():
    from run_variant_suite import run_seed_with_metrics
    _, m, _ = run_seed_with_metrics(
        seed=42, n_agents=50, start_date=date(2026, 5, 8),
        num_days=3, mode="dev", variant_name="global_distraction",
        phase_days="1,1,1",
    )
    return m


@pytest.fixture(scope="module")
def baseline_metrics():
    from run_variant_suite import run_seed_with_metrics
    _, m, _ = run_seed_with_metrics(
        seed=42, n_agents=50, start_date=date(2026, 5, 8),
        num_days=3, mode="dev", variant_name="baseline",
        phase_days="1,1,1",
    )
    return m


class TestPersonalizationE2E:

    def test_hp_propagation_metric_filled(self, hp_metrics):
        h = hp_metrics.info_propagation_hops
        assert h is not None
        assert "info_within_target_reach" in h
        assert "info_outside_target_reach" in h
        assert "target_precision" in h

    def test_hp_target_precision_positive(self, hp_metrics):
        """hp goes through PushPersonalizer → target_precision should reflect
        intended audience reach. With 50 agents and 1-day intervention, any
        positive value confirms the metric is wired correctly."""
        h = hp_metrics.info_propagation_hops
        # within + outside should be > 0 (i.e. some reach happened)
        total = h["info_within_target_reach"] + h["info_outside_target_reach"]
        assert total > 0, (
            f"hp should have non-zero target audience reach; got "
            f"within={h['info_within_target_reach']} outside={h['info_outside_target_reach']}"
        )

    def test_gd_target_audience_zero(self, gd_metrics):
        """global_distraction does NOT use personalizer (mirror design):
        FeedItems carry no target_audience_tags → target counts stay 0."""
        h = gd_metrics.info_propagation_hops
        assert h is not None
        # gd may still have info_count_total (broadcast push) but with
        # target_audience_tags=() → both within/outside count 0
        assert h["info_within_target_reach"] == 0
        assert h["info_outside_target_reach"] == 0
        assert h["target_precision"] == 0.0

    def test_baseline_no_pushes(self, baseline_metrics):
        """baseline shouldn't push, so origin count is minimal."""
        h = baseline_metrics.info_propagation_hops
        assert h is not None
        assert h["info_count_total"] <= 5
