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
    # social-graph snapshots at end-of-day (None when graph not injected)
    tie_count_total: int | None = None
    tie_count_weak: int | None = None
    tie_count_strong: int | None = None
    new_ties_today: int | None = None
    avg_ties_per_agent: float | None = None
    # conversation snapshots at end-of-day (None when service not injected)
    info_origins_today: int | None = None
    info_shares_today: int | None = None
    info_reaching_2plus_today: int | None = None
    avg_hops_today: float | None = None
    # push-content-individualization snapshot (None when audience_tag_provider absent)
    info_target_reach_today: int | None = None


class RunMetrics(BaseModel):
    """单 seed × 单 variant × N 天的完整指标。"""

    model_config = ConfigDict(frozen=True)

    seed: int
    variant_name: str  # "baseline" / "hyperlocal_push" / ...
    num_days: int
    per_day: tuple[DayMetricsSummary, ...]

    # 派生指标
    trajectory_deviation_m: float | None = None
    """**Push-target subset** median 距离（intervention-end 位置到 target_location）；
    只对 `variant_metadata["target_agent_ids"]`（缺省时 fallback 到 protag）
    的 agent 计算。仅 A / A' 填，其它 variant 留 None.

    语义在 fix-variant-measurement-and-friction change 中收紧：原版本对全部
    100 agent 取 median，10 protag 信号被 90 scripted agent 稀释（B1）。"""

    trajectory_deviation_m_all: float | None = None
    """**All-agent** median 距离（sanity 对照）；用于和 `trajectory_deviation_m`
    对比看 spillover。仅 A / A' 填。"""

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
    info_propagation_hops: dict[str, float] | None = None

    # ai-town port (agent-stack-aitown-port Phase E task 21)
    # All Optional; None when agent-operations capability not wired.
    reflection_count: int | None = None
    """Total reflection MemoryEvents created during this run (across all
    protagonists)."""
    dialogue_count: int | None = None
    """Total dialogues that ENDED during this run (started + ended)."""
    dialogue_avg_length: float | None = None
    """Average dialogue length in messages (excludes pure-reject zero-msg)."""
    op_timeout_count: int | None = None
    """OperationPool ops that timed out before handler returned."""
    cost_breakdown: dict[str, float] | None = None
    """Per-tier cost telemetry: {"sonnet": $X, "haiku": $Y, "nano": $Z, "total": $S}."""

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

    # backlog 1.13 第二阶段 (2026-05-19): "silent disaster" defense.
    # 高 fallback% 的 variant 是 fallback-template data 不是真 LLM 决策，
    # 必须在 aggregate 暴露否则下游"看似跑完了"漏检。
    max_llm_fallback_pct: float = 0.0
    """variant 内所有 seed × 所有 day 的最高 fallback rate；> 0.05 警告。"""
    avg_llm_fallback_pct: float = 0.0
    """variant 整体平均 fallback rate。"""
    high_fallback_warning: bool = False
    """max_llm_fallback_pct > 0.05 时为 True。aggregate 用，可读不一定阻断。"""


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

    # backlog 1.13 第二阶段 (2026-05-20): surface SuiteAggregate's
    # high_fallback_warning per row in contest.json so downstream
    # readers (humans, audits) don't miss "data may be fallback-template
    # not real LLM" silently. Default False for backward compat.
    high_fallback_warning: bool = False
    """True iff SuiteAggregate.max_llm_fallback_pct > 5%. When set,
    notes also includes a warning string for human readers."""
    max_llm_fallback_pct: float = 0.0
    """SuiteAggregate.max_llm_fallback_pct passthrough so contest.json
    consumers can see the exact rate, not just the threshold flag."""


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
