"""
SuiteAggregate — 跨 seed 聚合 RunMetrics 为 per-variant 统计。

重用 orchestrator.multi_day._series_stats（已有的 median / IQR / 95% CI
helper）；不引入 numpy。
"""

from __future__ import annotations

from typing import Any

from synthetic_socio_wind_tunnel.metrics.models import (
    RunMetrics,
    SuiteAggregate,
)
from synthetic_socio_wind_tunnel.orchestrator.multi_day import _series_stats


_PUBLISHABLE_MIN_SEEDS = 30


def _extract_scalar_metrics(run: RunMetrics) -> dict[str, float]:
    """把一个 RunMetrics 压平成 {metric_name: float} 字典（忽略 None）。"""
    out: dict[str, float] = {}

    if run.trajectory_deviation_m is not None:
        out["trajectory_deviation_m"] = run.trajectory_deviation_m

    for k, v in run.encounter_stats.items():
        out[f"encounter.{k}"] = v

    for k, v in run.feed_stats.items():
        out[f"feed.{k}"] = float(v)

    if run.attention_allocation_ratio is not None:
        for k, v in run.attention_allocation_ratio.items():
            out[f"attention.{k}"] = v

    # thesis-downstream outcomes: tie counts. Captured per-seed in factory but
    # previously absent from aggregate.mean_metrics → invisible in contest /
    # B3 sensitivity checks. Add here so social-graph injection surfaces.
    if run.weak_tie_formation_count is not None:
        out["weak_tie_formation_count"] = float(run.weak_tie_formation_count)
    if run.per_day:
        last_day = run.per_day[-1]
        if last_day.tie_count_total is not None:
            out["tie_count_total_eod"] = float(last_day.tie_count_total)
        if last_day.tie_count_weak is not None:
            out["tie_count_weak_eod"] = float(last_day.tie_count_weak)
        if last_day.tie_count_strong is not None:
            out["tie_count_strong_eod"] = float(last_day.tie_count_strong)

    return out


def _collect_time_series(runs: list[RunMetrics]) -> dict[str, list[list[float]]]:
    """
    把 per-day 的标量指标（encounter_count_total）堆成 metric → list-of-list
    形式（外层 day_index、内层 seed）。后续再 reduce 成 day-wise median。
    """
    if not runs:
        return {}
    num_days = max(len(r.per_day) for r in runs)

    series: dict[str, list[list[float]]] = {
        "encounter_count_per_day": [[] for _ in range(num_days)],
        "move_success_per_day": [[] for _ in range(num_days)],
    }
    for r in runs:
        for day_i in range(num_days):
            if day_i < len(r.per_day):
                day = r.per_day[day_i]
                series["encounter_count_per_day"][day_i].append(
                    float(day.encounter_count_total))
                series["move_success_per_day"][day_i].append(
                    float(day.move_success_count))
    return series


def _reduce_series_to_medians(
    series: dict[str, list[list[float]]],
) -> dict[str, tuple[float, ...]]:
    from statistics import median as _median
    out: dict[str, tuple[float, ...]] = {}
    for metric, day_series in series.items():
        out[metric] = tuple(
            float(_median(vals)) if vals else 0.0
            for vals in day_series
        )
    return out


def build_suite_aggregate(
    runs: list[RunMetrics],
    *,
    variant_metadata: dict[str, Any] | None = None,
) -> SuiteAggregate:
    """
    把 N 个 RunMetrics（同 variant_name，不同 seed）聚合为 SuiteAggregate。

    计算 per-metric median / IQR / 95% CI；per-day time series 用 day-wise
    median。seed_count < 30 → degraded 标记。
    """
    if not runs:
        raise ValueError("build_suite_aggregate requires at least one RunMetrics")

    variant_name = runs[0].variant_name
    for r in runs:
        if r.variant_name != variant_name:
            raise ValueError(
                f"All RunMetrics must share variant_name; got {variant_name!r} "
                f"and {r.variant_name!r}",
            )

    # ---- scalar per-metric aggregate ----
    per_metric_series: dict[str, list[float]] = {}
    for r in runs:
        for k, v in _extract_scalar_metrics(r).items():
            per_metric_series.setdefault(k, []).append(v)

    per_metric_stats: dict[str, dict[str, float]] = {
        k: _series_stats(vals)
        for k, vals in per_metric_series.items()
    }

    # ---- per-day time series ----
    ts_raw = _collect_time_series(runs)
    ts_medians = _reduce_series_to_medians(ts_raw)

    seeds = tuple(r.seed for r in runs)

    # publishable-finalize: lift reproducibility_lock from first run into
    # variant_metadata so report writer can find it. Also accumulate seeds
    # across runs (rep_lock.seed_pool is per-run; suite-level needs union).
    final_meta = dict(variant_metadata or {"name": variant_name})
    rep_locks = [r.extensions.get("reproducibility_lock") for r in runs
                 if r.extensions.get("reproducibility_lock")]
    if rep_locks:
        merged = dict(rep_locks[0])
        # Union the seed pool across all runs in this suite-aggregate
        merged["seed_pool"] = sorted({s for lock in rep_locks
                                      for s in lock.get("seed_pool", [])})
        final_meta["reproducibility_lock"] = merged

    # backlog 1.13 第二阶段: roll up LLM fallback% across seeds.
    # max = the worst seed/day; if > 5% → warning so downstream report
    # flags "data may be fallback-template, not real LLM decisions".
    max_fbs = [r.extensions.get("max_llm_fallback_pct", 0.0) or 0.0 for r in runs]
    avg_fbs = [r.extensions.get("avg_llm_fallback_pct", 0.0) or 0.0 for r in runs]
    _max_fb = max(max_fbs) if max_fbs else 0.0
    _avg_fb = sum(avg_fbs) / len(avg_fbs) if avg_fbs else 0.0
    _high_warn = _max_fb > 0.05

    return SuiteAggregate(
        variant_name=variant_name,
        variant_metadata=final_meta,
        seed_count=len(runs),
        seeds=seeds,
        per_metric_stats=per_metric_stats,
        per_day_time_series=ts_medians,
        degraded_preliminary_not_publishable=(len(runs) < _PUBLISHABLE_MIN_SEEDS),
        max_llm_fallback_pct=_max_fb,
        avg_llm_fallback_pct=_avg_fb,
        high_fallback_warning=_high_warn,
    )


__all__ = ["build_suite_aggregate"]
