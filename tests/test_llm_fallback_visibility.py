"""backlog 1.13 第二阶段 regression: per-day LLM fallback% must surface
through DayRunSummary → SuiteAggregate so high-fallback "silent disaster"
variants are visible in contest.json + report.md.
"""

from __future__ import annotations

from datetime import date

import pytest

from synthetic_socio_wind_tunnel.metrics.aggregator import build_suite_aggregate
from synthetic_socio_wind_tunnel.metrics.models import RunMetrics
from synthetic_socio_wind_tunnel.orchestrator.multi_day import (
    DayRunSummary,
    MultiDayResult,
)


def _make_run_metrics(
    seed: int,
    *,
    max_fb: float = 0.0,
    avg_fb: float = 0.0,
) -> RunMetrics:
    """Synthetic RunMetrics carrying just the fallback extension fields."""
    rm = RunMetrics(
        variant_name="phone_friction",
        seed=seed,
        num_days=14,
        per_day=(),
    )
    return rm.with_extensions(
        max_llm_fallback_pct=max_fb,
        avg_llm_fallback_pct=avg_fb,
        all_keys_open_total=0,
    )


def test_day_run_summary_carries_fallback_fields() -> None:
    """DayRunSummary SHALL expose llm_fallback_pct + all_keys_open_count."""
    d = DayRunSummary(
        day_index=0,
        simulated_date=date(2026, 4, 22),
        tick_count=288,
        commit_succeeded=200,
        commit_failed=0,
        encounter_count=10,
        llm_fallback_pct=0.12,
        llm_total_samples=400,
        all_keys_open_count=2,
    )
    assert d.llm_fallback_pct == 0.12
    assert d.llm_total_samples == 400
    assert d.all_keys_open_count == 2


def test_multi_day_result_dump_includes_fallback() -> None:
    result = MultiDayResult(
        per_day_summaries=(
            DayRunSummary(
                day_index=0, simulated_date=date(2026, 4, 22),
                tick_count=288, commit_succeeded=100, commit_failed=0,
                encounter_count=5,
                llm_fallback_pct=0.05, llm_total_samples=200, all_keys_open_count=0,
            ),
        ),
        total_ticks=288, total_encounters=5, seed=42,
        started_at=date(2026, 4, 22), ended_at=date(2026, 4, 22),
    )
    dump = result.model_dump()
    pd0 = dump["per_day_summaries"][0]
    assert pd0["llm_fallback_pct"] == 0.05
    assert pd0["llm_total_samples"] == 200
    assert pd0["all_keys_open_count"] == 0


def test_aggregate_rolls_up_max_and_warns_above_5pct() -> None:
    """max_llm_fallback_pct across seeds; warning when > 0.05."""
    runs = [
        _make_run_metrics(seed=42, max_fb=0.03, avg_fb=0.01),
        _make_run_metrics(seed=43, max_fb=0.08, avg_fb=0.04),  # day spike
        _make_run_metrics(seed=44, max_fb=0.01, avg_fb=0.005),
    ]
    agg = build_suite_aggregate(runs, variant_metadata={"name": "phone_friction"})
    assert agg.max_llm_fallback_pct == pytest.approx(0.08)
    assert agg.avg_llm_fallback_pct == pytest.approx((0.01 + 0.04 + 0.005) / 3)
    assert agg.high_fallback_warning is True


def test_aggregate_no_warning_when_all_below_threshold() -> None:
    runs = [
        _make_run_metrics(seed=42, max_fb=0.02, avg_fb=0.01),
        _make_run_metrics(seed=43, max_fb=0.04, avg_fb=0.02),
    ]
    agg = build_suite_aggregate(runs)
    assert agg.high_fallback_warning is False
    assert agg.max_llm_fallback_pct == pytest.approx(0.04)


def test_aggregate_legacy_runs_without_extension_default_zero() -> None:
    """RunMetrics from before this change SHALL default to 0.0 fallback,
    no warning, no crash (back-compat)."""
    legacy_run = RunMetrics(
        variant_name="baseline",
        seed=42,
        num_days=14,
        per_day=(),
    )
    # NO with_extensions(max_llm_fallback_pct=...) call
    agg = build_suite_aggregate([legacy_run])
    assert agg.max_llm_fallback_pct == 0.0
    assert agg.high_fallback_warning is False


# --- 2026-05-20 Part 2.2: warning SHALL flow to contest.json + report.md ---


def _agg_with_fb(
    variant_name: str,
    *,
    max_fb: float,
    variant_metadata: dict | None = None,
) -> "SuiteAggregate":
    from synthetic_socio_wind_tunnel.metrics import SuiteAggregate
    return SuiteAggregate(
        variant_name=variant_name,
        seed_count=30,
        seeds=tuple(range(30)),
        per_metric_stats={
            "encounter.per_day_median": {
                "median": 100.0, "iqr_lo": 97.0, "iqr_hi": 103.0,
                "ci95_lo": 95.0, "ci95_hi": 105.0,
            },
            "trajectory_deviation_m": {
                "median": 50.0, "iqr_lo": 48.0, "iqr_hi": 52.0,
                "ci95_lo": 45.0, "ci95_hi": 55.0,
            },
        },
        variant_metadata=variant_metadata or {"name": variant_name},
        max_llm_fallback_pct=max_fb,
        avg_llm_fallback_pct=max_fb * 0.5,
        high_fallback_warning=max_fb > 0.05,
    )


def test_contest_row_propagates_high_fallback_warning() -> None:
    """build_contest_report SHALL set high_fallback_warning on rows
    whose aggregate had it. silent-disaster regression."""
    from synthetic_socio_wind_tunnel.metrics import build_contest_report
    aggs = {
        "baseline": _agg_with_fb("baseline", max_fb=0.02),
        "phone_friction": _agg_with_fb(
            "phone_friction",
            max_fb=0.18,  # well over 5% — silent disaster territory
            variant_metadata={"name": "phone_friction", "hypothesis": "H_pull"},
        ),
    }
    contest = build_contest_report(aggs, suite_name="t")
    pf_row = contest.find("phone_friction")
    assert pf_row is not None
    assert pf_row.high_fallback_warning is True
    assert pf_row.max_llm_fallback_pct == pytest.approx(0.18)
    assert "fallback-template" in pf_row.notes
    assert "18.0%" in pf_row.notes  # human-readable rate inline
    # baseline row should NOT carry the flag
    base = contest.find("baseline")
    assert base is not None
    assert base.high_fallback_warning is False
    assert "fallback-template" not in base.notes


def test_report_md_emits_high_fallback_line(tmp_path) -> None:
    """write_markdown SHALL print a warning line whenever the variant
    aggregate's high_fallback_warning is set, regardless of seed_count.
    """
    from synthetic_socio_wind_tunnel.metrics import build_contest_report
    from synthetic_socio_wind_tunnel.metrics.report import write_markdown
    aggs = {
        "baseline": _agg_with_fb("baseline", max_fb=0.01),
        "phone_friction": _agg_with_fb(
            "phone_friction",
            max_fb=0.22,
            variant_metadata={"name": "phone_friction", "hypothesis": "H_pull"},
        ),
    }
    contest = build_contest_report(aggs, suite_name="t")
    write_markdown(contest, aggs, tmp_path)
    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    # The warning line is emitted exactly once for phone_friction
    assert "high LLM fallback" in text
    assert "22.0%" in text
    assert "fallback-template" in text


def test_contest_row_legacy_aggregate_no_warning() -> None:
    """SuiteAggregate built without the fallback fields (default zero)
    SHALL produce rows with high_fallback_warning=False — no crash, no
    false positive."""
    from synthetic_socio_wind_tunnel.metrics import (
        SuiteAggregate, build_contest_report,
    )
    legacy = SuiteAggregate(
        variant_name="baseline",
        seed_count=30,
        seeds=tuple(range(30)),
        per_metric_stats={
            "encounter.per_day_median": {
                "median": 100.0, "iqr_lo": 97.0, "iqr_hi": 103.0,
                "ci95_lo": 95.0, "ci95_hi": 105.0,
            },
        },
        variant_metadata={"name": "baseline"},
        # NO fallback fields set
    )
    contest = build_contest_report({"baseline": legacy}, suite_name="t")
    row = contest.find("baseline")
    assert row is not None
    assert row.high_fallback_warning is False
    assert row.max_llm_fallback_pct == 0.0
