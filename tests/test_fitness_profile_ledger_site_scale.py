"""Tests for profile / ledger / site / scale / cost audits."""

from __future__ import annotations

import pytest

from synthetic_socio_wind_tunnel.atlas import Atlas
from synthetic_socio_wind_tunnel.cartography.builder import RegionBuilder
from synthetic_socio_wind_tunnel.fitness.audits import (
    audit_cost_baseline,
    audit_ledger_observability,
    audit_profile_distribution,
    audit_scale_baseline,
    audit_site_fitness,
)
from synthetic_socio_wind_tunnel.fitness.report import AuditStatus


def _small_atlas() -> Atlas:
    region = (
        RegionBuilder("r", "r")
        .add_outdoor("street_a", "Street A", area_type="street")
        .polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        .end_outdoor()
        .add_outdoor("street_b", "Street B", area_type="street")
        .polygon([(15, 0), (25, 0), (25, 10), (15, 10)])
        .end_outdoor()
        .connect("street_a", "street_b", path_type="road", distance=5.0)
        .build()
    )
    return Atlas(region)


class TestProfile:

    def test_all_pass_on_lane_cove_profile(self):
        cat = audit_profile_distribution(seed=42)
        assert cat.category == "profile-distribution"
        statuses = [r.status for r in cat.results]
        assert all(s == AuditStatus.PASS for s in statuses), [
            (r.id, r.status.value, r.detail) for r in cat.results
        ]


class TestLedger:

    def test_trajectory_and_encounter_pass(self):
        atlas = _small_atlas()
        cat = audit_ledger_observability(atlas)
        assert cat.category == "ledger-observability"
        by_id = {r.id: r for r in cat.results}
        assert by_id["ledger.trajectory-export"].status == AuditStatus.PASS
        assert by_id["ledger.encounter-export"].status == AuditStatus.PASS
        assert by_id["ledger.snapshot-determinism"].status == AuditStatus.PASS


class TestSite:

    def test_returns_fitness_object_and_all_pass(self):
        atlas = _small_atlas()
        cat, sf = audit_site_fitness(atlas)
        assert cat.category == "site-fitness"
        # All results pass (it's diagnostic, not gating)
        for r in cat.results:
            assert r.status == AuditStatus.PASS
        assert 0.0 <= sf.named_building_ratio <= 1.0
        assert 0.0 <= sf.residential_ratio <= 1.0


class TestScale:

    def test_quick_scale_under_budget(self):
        atlas = _small_atlas()
        cat, baseline = audit_scale_baseline(atlas, scale="quick")
        assert baseline.agents == 100
        assert baseline.ticks == 72
        assert baseline.wall_seconds_total < 120.0
        result = cat.results[0]
        assert result.status == AuditStatus.PASS
        assert result.extras["p50_seconds"] >= 0.0

    def test_scale_skips_empty_atlas(self):
        empty_region = (
            RegionBuilder("r", "r")
            .build()
        )
        atlas = Atlas(empty_region)
        cat, baseline = audit_scale_baseline(atlas, scale="quick")
        # Empty atlas → skipped
        assert cat.results[0].status == AuditStatus.SKIP


class TestCost:

    def test_default_args_within_budget(self):
        cat, baseline = audit_cost_baseline()
        result = cat.results[0]
        assert result.status == AuditStatus.PASS
        assert baseline.total_usd_upper <= 200.0

    def test_exceeds_budget_fails(self):
        # Extreme: 50 protagonists + many replans → should blow past $200
        cat, baseline = audit_cost_baseline(
            total_agents=1000,
            protagonists=50,
            replans_per_agent_per_day=(20, 100),
        )
        result = cat.results[0]
        assert result.status == AuditStatus.FAIL
        assert result.mitigation_change == "model-budget"
