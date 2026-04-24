"""
Metrics — 观察报告层

职责（见 openspec/specs/metrics/spec.md）：
- 采集：`TickMetricsRecorder` 订阅 orchestrator.on_tick_end，per-day rollup
- 组装：`build_run_metrics(recorder, multi_day_result, atlas, variant_*)`
        → `RunMetrics`
- 聚合：`build_suite_aggregate(list[RunMetrics])` → `SuiteAggregate`
- 对比：`build_contest_report(dict[variant, SuiteAggregate])` → `ContestReport`
- 报告：`write_markdown(contest, aggregates, suite_dir)` → report.md

零 numpy/pandas 依赖；所有 median/IQR/CI 复用
`orchestrator.multi_day._series_stats`。

措辞门禁：`experimental-design` spec 要求实验报告仅用
"evidence consistent with / not consistent with"；禁用
"proved / falsified / confirmed / refuted"。contest + report 在生成
notes / 文本时 assert 无禁用词。
"""

from synthetic_socio_wind_tunnel.metrics.aggregator import build_suite_aggregate
from synthetic_socio_wind_tunnel.metrics.contest import build_contest_report
from synthetic_socio_wind_tunnel.metrics.factory import build_run_metrics
from synthetic_socio_wind_tunnel.metrics.models import (
    ContestReport,
    ContestRow,
    DayMetricsSummary,
    EvidenceAlignment,
    RunMetrics,
    SuiteAggregate,
)
from synthetic_socio_wind_tunnel.metrics.recorder import TickMetricsRecorder
from synthetic_socio_wind_tunnel.metrics.report import write_markdown


__all__ = [
    # Data models
    "ContestReport",
    "ContestRow",
    "DayMetricsSummary",
    "EvidenceAlignment",
    "RunMetrics",
    "SuiteAggregate",
    # Services
    "TickMetricsRecorder",
    "build_run_metrics",
    "build_suite_aggregate",
    "build_contest_report",
    "write_markdown",
]
