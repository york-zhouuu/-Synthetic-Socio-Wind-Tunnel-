"""Tests for ContestReport scoring + forbidden-word guard."""

from __future__ import annotations

import pytest

from synthetic_socio_wind_tunnel.metrics import (
    ContestReport,
    SuiteAggregate,
    build_contest_report,
)
from synthetic_socio_wind_tunnel.metrics.contest import _assert_no_forbidden


def _aggregate(
    variant_name: str,
    *,
    median: float = 100.0,
    ci95_lo: float = 95.0,
    ci95_hi: float = 105.0,
    seed_count: int = 30,
    metric: str = "encounter.per_day_median",
    variant_metadata: dict | None = None,
) -> SuiteAggregate:
    return SuiteAggregate(
        variant_name=variant_name,
        seed_count=seed_count,
        seeds=tuple(range(seed_count)),
        per_metric_stats={
            metric: {
                "median": median,
                "iqr_lo": median - 3,
                "iqr_hi": median + 3,
                "ci95_lo": ci95_lo,
                "ci95_hi": ci95_hi,
            },
        },
        variant_metadata=variant_metadata or {"name": variant_name},
    )


class TestForbiddenWords:
    def test_clean_text_passes(self):
        _assert_no_forbidden("evidence consistent with H_info")

    def test_proved_raises(self):
        with pytest.raises(ValueError):
            _assert_no_forbidden("this proved the hypothesis")

    def test_case_insensitive(self):
        with pytest.raises(ValueError):
            _assert_no_forbidden("result CONFIRMED H1")

    def test_falsified_raises(self):
        with pytest.raises(ValueError):
            _assert_no_forbidden("model falsified under test")


class TestContestReportDirection:
    def test_baseline_only(self):
        aggs = {"baseline": _aggregate("baseline", median=50)}
        contest = build_contest_report(aggs, suite_name="test")
        assert contest.baseline_row is not None
        assert contest.baseline_row.evidence_alignment == "inconclusive"
        assert contest.find("baseline") is not None

    def test_variant_consistent_lower_direction(self):
        """hyperlocal_push: lower trajectory 距离 = consistent."""
        aggs = {
            "baseline": _aggregate(
                "baseline", median=500,
                ci95_lo=480, ci95_hi=520,
                metric="trajectory_deviation_m",
                variant_metadata={"name": "baseline"},
            ),
            "hyperlocal_push": _aggregate(
                "hyperlocal_push", median=100,
                ci95_lo=80, ci95_hi=120,  # hi < baseline_lo=480 → consistent
                metric="trajectory_deviation_m",
                variant_metadata={
                    "name": "hyperlocal_push", "hypothesis": "H_info",
                },
            ),
        }
        contest = build_contest_report(aggs, suite_name="test")
        row = contest.find("hyperlocal_push")
        assert row is not None
        assert row.evidence_alignment == "consistent"
        assert "consistent with" in row.notes.lower()

    def test_variant_inconclusive_on_overlap(self):
        aggs = {
            "baseline": _aggregate(
                "baseline", median=100,
                ci95_lo=90, ci95_hi=110,
                metric="encounter.per_day_median",
            ),
            "shared_anchor": _aggregate(
                "shared_anchor", median=105,
                ci95_lo=95, ci95_hi=115,  # overlaps baseline
                metric="encounter.per_day_median",
                variant_metadata={"name": "shared_anchor", "hypothesis": "H_meaning"},
            ),
        }
        contest = build_contest_report(aggs, suite_name="test")
        row = contest.find("shared_anchor")
        assert row.evidence_alignment == "inconclusive"

    def test_not_consistent_reverse_direction(self):
        """shared_anchor direction='higher'; variant < baseline → not_consistent."""
        aggs = {
            "baseline": _aggregate(
                "baseline", median=100,
                ci95_lo=90, ci95_hi=110,
                metric="encounter.per_day_median",
            ),
            "shared_anchor": _aggregate(
                "shared_anchor", median=50,
                ci95_lo=40, ci95_hi=60,  # hi < baseline_lo → opposite direction
                metric="encounter.per_day_median",
                variant_metadata={"name": "shared_anchor", "hypothesis": "H_meaning"},
            ),
        }
        contest = build_contest_report(aggs, suite_name="test")
        row = contest.find("shared_anchor")
        assert row.evidence_alignment == "not_consistent"

    def test_no_forbidden_words_in_any_notes(self):
        aggs = {
            "baseline": _aggregate("baseline", median=100, metric="encounter.per_day_median"),
            "hyperlocal_push": _aggregate(
                "hyperlocal_push", median=50, metric="trajectory_deviation_m",
                variant_metadata={"name": "hyperlocal_push", "hypothesis": "H_info"},
            ),
            "shared_anchor": _aggregate(
                "shared_anchor", median=200, metric="encounter.per_day_median",
                variant_metadata={"name": "shared_anchor", "hypothesis": "H_meaning"},
            ),
        }
        contest = build_contest_report(aggs, suite_name="test")
        for row in contest.rows:
            for word in ("proved", "falsified", "confirmed", "refuted"):
                assert word.lower() not in row.notes.lower()

    def test_mirror_delta_symmetric(self):
        aggs = {
            "hyperlocal_push": _aggregate(
                "hyperlocal_push", median=100,
                metric="trajectory_deviation_m",
                variant_metadata={
                    "name": "hyperlocal_push", "hypothesis": "H_info",
                    "paired_variant": "global_distraction",
                },
            ),
            "global_distraction": _aggregate(
                "global_distraction", median=400,
                metric="trajectory_deviation_m",
                variant_metadata={
                    "name": "global_distraction", "hypothesis": "H_info",
                    "paired_variant": "hyperlocal_push",
                    "is_mirror": True,
                },
            ),
        }
        contest = build_contest_report(aggs, suite_name="test")
        row_a = contest.find("hyperlocal_push")
        row_ap = contest.find("global_distraction")
        assert row_a.mirror_delta == -300.0  # 100 - 400
        assert row_ap.mirror_delta == 300.0

    def test_preliminary_noted_in_notes(self):
        aggs = {
            "baseline": _aggregate(
                "baseline", median=100, seed_count=5, metric="encounter.per_day_median",
            ),
            "hyperlocal_push": _aggregate(
                "hyperlocal_push", median=50, seed_count=5,
                metric="trajectory_deviation_m",
                variant_metadata={"name": "hyperlocal_push", "hypothesis": "H_info"},
            ),
        }
        # Mark degraded
        aggs["baseline"] = aggs["baseline"].model_copy(
            update={"degraded_preliminary_not_publishable": True},
        )
        aggs["hyperlocal_push"] = aggs["hyperlocal_push"].model_copy(
            update={"degraded_preliminary_not_publishable": True},
        )
        contest = build_contest_report(aggs, suite_name="test")
        row = contest.find("hyperlocal_push")
        assert "preliminary" in row.notes.lower()
