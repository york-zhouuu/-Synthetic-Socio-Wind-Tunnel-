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

    return SuiteAggregate(
        variant_name=variant_name,
        variant_metadata=variant_metadata or {"name": variant_name},
        seed_count=len(runs),
        seeds=seeds,
        per_metric_stats=per_metric_stats,
        per_day_time_series=ts_medians,
        degraded_preliminary_not_publishable=(len(runs) < _PUBLISHABLE_MIN_SEEDS),
    )


__all__ = ["build_suite_aggregate"]
