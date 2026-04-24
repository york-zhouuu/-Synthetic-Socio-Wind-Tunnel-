"""Tests for SuiteAggregate builder."""

from __future__ import annotations

import pytest

from synthetic_socio_wind_tunnel.metrics import (
    DayMetricsSummary,
    RunMetrics,
    build_suite_aggregate,
)


def _run(seed: int, *, variant: str = "baseline",
         trajectory: float | None = None,
         encounter_total: float = 100.0,
         num_days: int = 3) -> RunMetrics:
    per_day = tuple(
        DayMetricsSummary(
            day_index=i,
            encounter_count_total=int(encounter_total / num_days),
            move_success_count=50,
        )
        for i in range(num_days)
    )
    return RunMetrics(
        seed=seed, variant_name=variant, num_days=num_days, per_day=per_day,
        trajectory_deviation_m=trajectory,
        encounter_stats={"total": encounter_total, "per_day_median": encounter_total / num_days},
    )


class TestAggregator:
    def test_basic_3_seeds(self):
        runs = [_run(s, trajectory=300.0 + s * 5) for s in range(3)]
        agg = build_suite_aggregate(runs)
        assert agg.seed_count == 3
        assert agg.seeds == (0, 1, 2)
        assert agg.degraded_preliminary_not_publishable is True  # < 30

    def test_30_seeds_no_degraded(self):
        runs = [_run(s, trajectory=300.0 + s) for s in range(30)]
        agg = build_suite_aggregate(runs)
        assert agg.seed_count == 30
        assert agg.degraded_preliminary_not_publishable is False

    def test_per_metric_stats_have_all_keys(self):
        runs = [_run(s, trajectory=300.0 + s * 10) for s in range(10)]
        agg = build_suite_aggregate(runs)
        stats = agg.per_metric_stats["trajectory_deviation_m"]
        assert set(stats.keys()) == {
            "median", "iqr_lo", "iqr_hi", "ci95_lo", "ci95_hi",
        }
        # median should be around 345 (first 10 values: 300-390)
        assert 330 <= stats["median"] <= 360

    def test_mixed_variant_rejected(self):
        r1 = _run(0, variant="a")
        r2 = _run(1, variant="b")
        with pytest.raises(ValueError):
            build_suite_aggregate([r1, r2])

    def test_empty_rejected(self):
        with pytest.raises(ValueError):
            build_suite_aggregate([])

    def test_time_series_included(self):
        runs = [_run(s, num_days=5) for s in range(5)]
        agg = build_suite_aggregate(runs)
        assert "encounter_count_per_day" in agg.per_day_time_series
        assert len(agg.per_day_time_series["encounter_count_per_day"]) == 5
