## MODIFIED Requirements

### Requirement: SuiteAggregate 跨 seed 统计

`synthetic_socio_wind_tunnel/metrics/aggregator.py` SHALL 提供
`SuiteAggregate.from_run_metrics(list[RunMetrics]) -> SuiteAggregate`，
产出 per-metric 的 median / IQR [25, 75] / 95% CI。

至少覆盖以下指标（若 RunMetrics 字段非 None）：
- `trajectory_deviation_m`
- `encounter_stats`（每 stat 独立统计）
- `feed_stats`（每 source 独立统计）
- `attention_allocation_ratio.physical_world`
- `weak_tie_formation_count`（thesis-downstream outcome；social-graph 注入时才非 None）
- `tie_count_total_eod` / `tie_count_weak_eod` / `tie_count_strong_eod`
  （per_day 最后一日的 cumulative，从 `DayMetricsSummary.tie_count_*` 取）

输出的 SuiteAggregate SHALL 含：
- `variant_name: str`
- `seed_count: int`
- `per_metric_stats: dict[str, dict[str, float]]`（metric → {median, iqr_lo,
  iqr_hi, ci95_lo, ci95_hi}）
- `per_day_time_series: dict[str, tuple[float, ...]]`（per-day median）

#### Scenario: 30 seed 聚合
- **WHEN** 30 个 RunMetrics 传入 `SuiteAggregate.from_run_metrics`
- **THEN** `seed_count` SHALL == 30；`per_metric_stats` 每 metric 的
  dict 含 5 键（median / iqr_lo / iqr_hi / ci95_lo / ci95_hi）

#### Scenario: 不足 30 seed 时 report degraded
- **WHEN** 5 个 RunMetrics 传入
- **THEN** aggregate SHALL 仍可构造；但产出的 SuiteAggregate.metadata 字段
  SHALL 含 `"degraded_preliminary_not_publishable": true` 标记

#### Scenario: social-graph 注入时聚合暴露 weak-tie outcome
- **WHEN** 7 个 RunMetrics 传入，每个 RunMetrics.weak_tie_formation_count 非 None
- **THEN** SuiteAggregate.per_metric_stats SHALL 含 key `"weak_tie_formation_count"`，
  该 dict 含 5 键（median / iqr_lo / iqr_hi / ci95_lo / ci95_hi）；缺失会使 B3
  sensitivity sweep 无法用聚合数据验证 thesis 方向稳健性

#### Scenario: 无 social-graph 注入时保持向后兼容
- **WHEN** 7 个 RunMetrics 传入，每个 RunMetrics.weak_tie_formation_count 为 None
- **THEN** SuiteAggregate.per_metric_stats SHALL NOT 含 `"weak_tie_formation_count"` key，
  与旧聚合输出保持等价
