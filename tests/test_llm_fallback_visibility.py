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
