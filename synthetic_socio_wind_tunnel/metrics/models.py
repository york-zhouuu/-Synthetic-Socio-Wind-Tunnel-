"""
Metrics 数据模型 — 观察报告层。

- `DayMetricsSummary`  per-day rollup（TickMetricsRecorder 产出）
- `RunMetrics`          per-seed per-variant 全 run 指标
- `SuiteAggregate`      per-variant × N seed 跨 seed 聚合（median / IQR / 95% CI）
- `ContestRow`          单 variant 在 rival contest 里的一行
- `ContestReport`       跨 variant 的 contest 汇总
- `EvidenceAlignment`   Literal 措辞 evidence_alignment

承诺：零 numpy / pandas 依赖；所有 percentile 用 stdlib + 本地 helper。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


EvidenceAlignment = Literal["consistent", "not_consistent", "inconclusive"]


class DayMetricsSummary(BaseModel):
    """单 day 的跨 agent rollup。TickMetricsRecorder 每天产出 1 个。"""

    model_config = ConfigDict(frozen=True)

    day_index: int
    # per-agent aggregates
    encounter_count_total: int = 0
    distinct_encounter_pairs: int = 0
    move_success_count: int = 0
    move_fail_count: int = 0
    notifications_delivered: int = 0  # 当天 attention-channel 投递给所有 agent 的总数
    notifications_suppressed: int = 0
    # per-location → tick count（agent 在该 location 累计停留的 tick 数）
    location_dwell_ticks: dict[str, int] = Field(default_factory=dict)
    # per-agent 的当天末尾 location（供 trajectory_deviation 计算）
    end_of_day_location_by_agent: dict[str, str] = Field(default_factory=dict)


class RunMetrics(BaseModel):
    """单 seed × 单 variant × N 天的完整指标。"""

    model_config = ConfigDict(frozen=True)

    seed: int
    variant_name: str  # "baseline" / "hyperlocal_push" / ...
    num_days: int
    per_day: tuple[DayMetricsSummary, ...]

    # 派生指标
    trajectory_deviation_m: float | None = None
    """baseline-end vs intervention-end median 距离（向 target_location）；
    仅 A / A' 填，其它 variant 留 None。"""

    encounter_stats: dict[str, float] = Field(default_factory=dict)
    """{"total": X, "per_day_median": Y, "diversity_pairs_total": Z, ...}"""

    space_activation: dict[str, float] = Field(default_factory=dict)
    """location_id → 全 run 累计 dwell tick"""

    feed_stats: dict[str, int] = Field(default_factory=dict)
    """{"local_news.delivered": n, "global_news.delivered": n, ...}"""

    attention_allocation_ratio: dict[str, float] | None = None
    """physical / phone_feed / task / conversation 全 run 平均占比。
    本 change 暂以"notifications per agent-day"作 phone_feed proxy；
    其它三项留 None（需 perception 层扩展）。"""

    # 未来挂载点（social-graph / conversation）
    weak_tie_formation_count: int | None = None
    info_propagation_hops: dict[str, int] | None = None

    extensions: dict[str, Any] = Field(default_factory=dict)

    def with_extensions(self, **kwargs: Any) -> "RunMetrics":
        """非破坏性追加字段（social-graph / conversation 用）。"""
        new_ext = dict(self.extensions)
        # 已定义字段优先用 model_copy；未定义走 extensions
        known = set(self.__class__.model_fields.keys())
        model_kwargs: dict[str, Any] = {}
        for k, v in kwargs.items():
            if k in known:
                model_kwargs[k] = v
            else:
                new_ext[k] = v
        model_kwargs["extensions"] = new_ext
        return self.model_copy(update=model_kwargs)


class SuiteAggregate(BaseModel):
    """单 variant × N seed 聚合。"""

    model_config = ConfigDict(frozen=True)

    variant_name: str
    variant_metadata: dict[str, Any] = Field(default_factory=dict)
    """来自 policy-hack 的 variant.metadata_dict()；baseline 时 name='baseline'。"""
    seed_count: int
    seeds: tuple[int, ...]

    per_metric_stats: dict[str, dict[str, float]] = Field(default_factory=dict)
    """metric_name → {median, iqr_lo, iqr_hi, ci95_lo, ci95_hi}"""
    per_day_time_series: dict[str, tuple[float, ...]] = Field(default_factory=dict)
    """metric_name → 14 天 median（对齐 post-phase decay 分析）"""

    degraded_preliminary_not_publishable: bool = False
    """seed_count < 30 时为 True。"""


class ContestRow(BaseModel):
    """Contest 表里的一行（single variant × single primary_effect_size）。"""

    model_config = ConfigDict(frozen=True)

    variant_name: str
    hypothesis: str | None = None  # baseline 为 None
    primary_metric: str | None = None  # 哪个 RunMetrics 字段作 effect size
    primary_effect_size: float | None = None
    primary_effect_ci: tuple[float, float] | None = None  # (ci95_lo, ci95_hi)
    baseline_reference: float | None = None
    evidence_alignment: EvidenceAlignment = "inconclusive"
    mirror_delta: float | None = None
    paired_variant: str | None = None
    notes: str = ""


class ContestReport(BaseModel):
    """跨 variant 的 rival hypothesis contest 汇总。"""

    model_config = ConfigDict(frozen=True)

    suite_name: str
    rows: tuple[ContestRow, ...]
    baseline_row: ContestRow | None = None

    def find(self, variant_name: str) -> ContestRow | None:
        for r in self.rows:
            if r.variant_name == variant_name:
                return r
        return None


__all__ = [
    "ContestReport",
    "ContestRow",
    "DayMetricsSummary",
    "EvidenceAlignment",
    "RunMetrics",
    "SuiteAggregate",
]
