"""Tests for metrics data models."""

from __future__ import annotations

import json
import sys

from synthetic_socio_wind_tunnel.metrics import (
    ContestReport,
    ContestRow,
    DayMetricsSummary,
    RunMetrics,
    SuiteAggregate,
)


class TestRunMetrics:
    def test_construct_minimal(self):
        rm = RunMetrics(seed=42, variant_name="baseline", num_days=3, per_day=())
        assert rm.seed == 42
        assert rm.trajectory_deviation_m is None
        assert rm.weak_tie_formation_count is None
        assert rm.info_propagation_hops is None
        assert rm.extensions == {}

    def test_json_roundtrip(self):
        day = DayMetricsSummary(
            day_index=0, encounter_count_total=10, distinct_encounter_pairs=3,
            move_success_count=100, move_fail_count=5,
        )
        rm = RunMetrics(
            seed=42, variant_name="hyperlocal_push", num_days=1,
            per_day=(day,),
            trajectory_deviation_m=302.5,
            encounter_stats={"total": 10.0, "per_day_median": 10.0},
        )
        s = rm.model_dump_json()
        restored = RunMetrics.model_validate_json(s)
        assert restored == rm

    def test_with_extensions_known_field(self):
        rm = RunMetrics(seed=0, variant_name="baseline", num_days=1, per_day=())
        new = rm.with_extensions(weak_tie_formation_count=12)
        assert new.weak_tie_formation_count == 12
        # original unchanged
        assert rm.weak_tie_formation_count is None

    def test_with_extensions_unknown_field_goes_to_extensions(self):
        rm = RunMetrics(seed=0, variant_name="baseline", num_days=1, per_day=())
        new = rm.with_extensions(my_custom_metric=0.42)
        assert new.extensions == {"my_custom_metric": 0.42}
        assert rm.extensions == {}

    def test_frozen(self):
        rm = RunMetrics(seed=0, variant_name="baseline", num_days=1, per_day=())
        try:
            rm.seed = 1  # type: ignore[misc]
        except (TypeError, Exception):
            return
        raise AssertionError("RunMetrics should be frozen")


class TestSuiteAggregate:
    def test_construct(self):
        agg = SuiteAggregate(
            variant_name="x", seed_count=3, seeds=(0, 1, 2),
        )
        assert agg.seed_count == 3
        assert agg.degraded_preliminary_not_publishable is False

    def test_degraded_flag(self):
        agg = SuiteAggregate(
            variant_name="x", seed_count=5, seeds=(0, 1, 2, 3, 4),
            degraded_preliminary_not_publishable=True,
        )
        assert agg.degraded_preliminary_not_publishable is True


class TestContestReport:
    def test_find_variant(self):
        row_a = ContestRow(variant_name="a", hypothesis="H_info")
        row_b = ContestRow(variant_name="b")
        report = ContestReport(suite_name="test", rows=(row_a, row_b))
        assert report.find("a") is row_a
        assert report.find("missing") is None


class TestNoHeavyDeps:
    def test_no_numpy_pandas_loaded(self):
        import synthetic_socio_wind_tunnel.metrics  # noqa: F401
        # 不应加载 numpy/pandas/scipy
        assert "numpy" not in sys.modules
        assert "pandas" not in sys.modules
        assert "scipy" not in sys.modules
