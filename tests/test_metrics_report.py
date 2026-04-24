"""Tests for ReportWriter Markdown output."""

from __future__ import annotations

from pathlib import Path

import pytest

from synthetic_socio_wind_tunnel.metrics import (
    SuiteAggregate,
    build_contest_report,
    write_markdown,
)


def _aggregate(
    variant_name: str, median: float = 100.0, seed_count: int = 30,
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
                "iqr_lo": median - 5,
                "iqr_hi": median + 5,
                "ci95_lo": median - 10,
                "ci95_hi": median + 10,
            },
        },
        per_day_time_series={
            "encounter_count_per_day": (median, median + 5, median + 3, median + 1, median - 2),
        },
        variant_metadata=variant_metadata or {"name": variant_name},
    )


class TestReportWriter:
    def test_five_act_structure(self, tmp_path: Path):
        aggs = {
            "baseline": _aggregate("baseline"),
            "hyperlocal_push": _aggregate(
                "hyperlocal_push", median=50,
                metric="trajectory_deviation_m",
                variant_metadata={
                    "name": "hyperlocal_push", "hypothesis": "H_info",
                    "theoretical_lineage": "Shannon",
                    "success_criterion": "lower distance",
                    "failure_criterion": "no change",
                    "chain_position": "algorithmic-input",
                },
            ),
        }
        contest = build_contest_report(aggs, suite_name="test_suite")
        report_file = write_markdown(contest, aggs, tmp_path)

        assert report_file.exists()
        text = report_file.read_text(encoding="utf-8")

        # 五幕结构齐全
        assert "## Act 1 — Baseline" in text
        assert "## Act 2 — Four Doctors" in text
        assert "## Act 3 — The Contest" in text
        assert "## Act 4 — Decay" in text
        assert "## Act 5 — The Mirror" in text

    def test_html_trace_comment_present(self, tmp_path: Path):
        aggs = {"baseline": _aggregate("baseline")}
        contest = build_contest_report(aggs, suite_name="x")
        text = write_markdown(contest, aggs, tmp_path).read_text(encoding="utf-8")
        assert "<!-- auto-generated from" in text

    def test_missing_baseline_warning(self, tmp_path: Path):
        aggs = {
            "hyperlocal_push": _aggregate(
                "hyperlocal_push", median=100,
                metric="trajectory_deviation_m",
                variant_metadata={
                    "name": "hyperlocal_push", "hypothesis": "H_info",
                    "theoretical_lineage": "", "success_criterion": "",
                    "failure_criterion": "", "chain_position": "algorithmic-input",
                },
            ),
        }
        contest = build_contest_report(aggs, suite_name="no_baseline")
        text = write_markdown(contest, aggs, tmp_path).read_text(encoding="utf-8")
        assert "no baseline" in text.lower()

    def test_forbidden_words_not_in_output(self, tmp_path: Path):
        aggs = {
            "baseline": _aggregate("baseline", median=100),
            "hyperlocal_push": _aggregate(
                "hyperlocal_push", median=30,
                metric="trajectory_deviation_m",
                variant_metadata={
                    "name": "hyperlocal_push", "hypothesis": "H_info",
                    "theoretical_lineage": "L", "success_criterion": "S",
                    "failure_criterion": "F", "chain_position": "algorithmic-input",
                },
            ),
        }
        contest = build_contest_report(aggs, suite_name="dual")
        text = write_markdown(contest, aggs, tmp_path).read_text(encoding="utf-8").lower()
        for word in ("proved", "falsified", "confirmed", "refuted"):
            assert word not in text

    def test_paired_mirror_in_act5(self, tmp_path: Path):
        aggs = {
            "hyperlocal_push": _aggregate(
                "hyperlocal_push", median=50,
                metric="trajectory_deviation_m",
                variant_metadata={
                    "name": "hyperlocal_push", "hypothesis": "H_info",
                    "theoretical_lineage": "", "success_criterion": "",
                    "failure_criterion": "", "chain_position": "algorithmic-input",
                    "paired_variant": "global_distraction",
                },
            ),
            "global_distraction": _aggregate(
                "global_distraction", median=400,
                metric="trajectory_deviation_m",
                variant_metadata={
                    "name": "global_distraction", "hypothesis": "H_info",
                    "theoretical_lineage": "", "success_criterion": "",
                    "failure_criterion": "", "chain_position": "algorithmic-input",
                    "is_mirror": True, "paired_variant": "hyperlocal_push",
                },
            ),
        }
        contest = build_contest_report(aggs, suite_name="dual")
        text = write_markdown(contest, aggs, tmp_path).read_text(encoding="utf-8")
        assert "mirror delta" in text.lower()
