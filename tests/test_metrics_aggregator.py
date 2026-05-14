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


def _run_with_weak_tie(seed: int, weak_tie_count: int | None,
                      tie_total_eod: int | None = None) -> RunMetrics:
    """Helper: build RunMetrics with thesis-downstream tie outcomes."""
    per_day = (
        DayMetricsSummary(
            day_index=0,
            encounter_count_total=100,
            move_success_count=50,
            tie_count_total=tie_total_eod,
            tie_count_weak=tie_total_eod,
            tie_count_strong=0 if tie_total_eod is not None else None,
        ),
    )
    return RunMetrics(
        seed=seed, variant_name="baseline", num_days=1, per_day=per_day,
        encounter_stats={"total": 100.0},
        weak_tie_formation_count=weak_tie_count,
    )


class TestAggregatorWeakTie:
    """fix-remaining-mechanics: aggregator must expose thesis-downstream
    weak-tie counts so B3 sensitivity sweep can compare across rates."""

    def test_weak_tie_exposed_when_present(self):
        runs = [_run_with_weak_tie(s, weak_tie_count=100 + s * 10) for s in range(7)]
        agg = build_suite_aggregate(runs)
        assert "weak_tie_formation_count" in agg.per_metric_stats
        stats = agg.per_metric_stats["weak_tie_formation_count"]
        assert set(stats.keys()) == {
            "median", "iqr_lo", "iqr_hi", "ci95_lo", "ci95_hi",
        }
        # median of [100,110,...,160] is 130
        assert stats["median"] == pytest.approx(130.0, abs=0.1)

    def test_weak_tie_absent_when_none(self):
        runs = [_run_with_weak_tie(s, weak_tie_count=None) for s in range(5)]
        agg = build_suite_aggregate(runs)
        assert "weak_tie_formation_count" not in agg.per_metric_stats

    def test_per_day_tie_count_eod_exposed(self):
        runs = [
            _run_with_weak_tie(s, weak_tie_count=50, tie_total_eod=200 + s * 5)
            for s in range(7)
        ]
        agg = build_suite_aggregate(runs)
        assert "tie_count_total_eod" in agg.per_metric_stats
        assert "tie_count_weak_eod" in agg.per_metric_stats
