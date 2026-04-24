## ADDED Requirements

### Requirement: TickMetricsRecorder 采样 per-tick 数据

`synthetic_socio_wind_tunnel/metrics/recorder.py` SHALL 定义
`TickMetricsRecorder` 类，作为 `Orchestrator.register_on_tick_end`
订阅者。每 tick 它 SHALL 采集以下 per-agent 数据：

- `location_id`（从 `ledger.get_entity(agent_id).location_id`）
- `AttentionState` snapshot（若 `attention_service` 非 None，用
  `get_attention_state(agent_id)`；否则跳过）
- 本 tick 参与的 encounter 对数（从 `tick_result.encounter_candidates`）
- 本 tick 的 commit 成功/失败计数（从 `tick_result.commits`）

采样结果缓存到 per-day collector（`DayMetricsCollector`）；day 结束（由
`multi-day-run` 的 `on_day_end` hook 或 recorder 自检 day_index 变化）时
rollup 为 `DayMetricsSummary`。

#### Scenario: 每 tick 采样所有 agents
- **WHEN** 100 agents × 288 tick 的一天跑完
- **THEN** recorder 内部 SHALL 累计 28,800 个 per-agent-tick records

#### Scenario: 无 attention_service 时跳过 AttentionState
- **WHEN** `orchestrator.attention_service is None`
- **THEN** recorder SHALL 继续采集 location_id / encounter / commit 数据；
  AttentionState 字段留 None；不抛异常

#### Scenario: 采样不影响 tick 性能超过 10%
- **WHEN** 100 agents × 288 tick × 14 day × 1 seed，与无 recorder baseline 比较
- **THEN** wall time 增量 SHALL ≤ 10%（baseline ~10s → 带 recorder ≤ 11s）


### Requirement: RunMetrics 数据模型

`synthetic_socio_wind_tunnel/metrics/models.py` SHALL 定义
`RunMetrics` Pydantic frozen 模型，至少含：

- `seed: int`
- `variant_name: str`（"baseline" 为默认）
- `num_days: int`
- `per_day: tuple[DayMetricsSummary, ...]`
- `trajectory_deviation_m: float | None = None`（baseline→intervention 差）
- `encounter_stats: dict[str, float]`（total / per_day_median / diversity）
- `space_activation: dict[str, float]`（location → cumulative dwell_tick_count）
- `feed_stats: dict[str, int]`（per FeedSource delivered / suppressed）
- `attention_allocation_ratio: dict[str, float] | None = None`
  （`physical_world / phone_feed / task / conversation`；avg across run）
- `weak_tie_formation_count: int | None = None`（`social-graph` 填）
- `info_propagation_hops: dict[str, int] | None = None`（`conversation` 填）
- `extensions: dict[str, Any] = {}`（未来 recorder 挂载用）

#### Scenario: 构造完整 RunMetrics 并 JSON dump
- **WHEN** 14 天 run 结束，构造 RunMetrics；调 `.model_dump_json()`
- **THEN** 输出 SHALL 是 JSON-safe 字符串；可往返 parse 回等价 model

#### Scenario: 未填字段默认 None
- **WHEN** 现阶段（social-graph / conversation 未归档）构造 RunMetrics
- **THEN** `weak_tie_formation_count` SHALL 为 None；`info_propagation_hops`
  SHALL 为 None


### Requirement: RunMetrics.from_recorder 工厂

`RunMetrics.from_recorder(recorder, multi_day_result, variant_metadata)` SHALL
把 TickMetricsRecorder 的累积数据 + MultiDayResult + variant metadata 合并
为 RunMetrics 实例。

trajectory_deviation_m 的第一版计算 SHALL 是：
```
1. 对每 agent：
    baseline_end_loc = location_id at end of baseline phase
    intervention_end_loc = location_id at end of intervention phase
    post_end_loc = location_id at end of post phase
2. 若 variant 是 hyperlocal_push / global_distraction：
    trajectory_deviation_m = median(
        euclidean_distance(intervention_end_loc_center, target_location_center)
        for agent in target_agents
    )
3. 其它 variant：留 None（由 D4 Risk 处理，未来 variant-specific 计算）
```

#### Scenario: 从 recorder + result 组装
- **WHEN** `RunMetrics.from_recorder(recorder=rec, multi_day_result=result,
  variant_metadata=v.metadata_dict())`
- **THEN** 返回实例的 `seed` / `variant_name` / `num_days` SHALL 与输入一致；
  `per_day` SHALL 有 num_days 条


### Requirement: SuiteAggregate 跨 seed 统计

`synthetic_socio_wind_tunnel/metrics/aggregator.py` SHALL 提供
`SuiteAggregate.from_run_metrics(list[RunMetrics]) -> SuiteAggregate`，
产出 per-metric 的 median / IQR [25, 75] / 95% CI。

至少覆盖以下指标（若 RunMetrics 字段非 None）：
- `trajectory_deviation_m`
- `encounter_stats.total`
- `encounter_stats.per_day_median`
- `feed_stats`（每 source 独立统计）
- `attention_allocation_ratio.physical_world`

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


### Requirement: ContestReport rival hypothesis 打分

`synthetic_socio_wind_tunnel/metrics/contest.py` SHALL 提供
`ContestReport.from_suite(aggregates: dict[str, SuiteAggregate])` 产出
跨 variant 的 contest 表。

每行 SHALL 含：
- `variant_name: str`
- `hypothesis: str | None`（baseline 为 None）
- `primary_effect_size: float | None`
- `primary_effect_ci: tuple[float, float] | None`
- `baseline_reference: float | None`
- `evidence_alignment: Literal["consistent", "not_consistent", "inconclusive"]`
- `mirror_delta: float | None`（若 variant 有 paired mirror 且在 suite 内）
- `notes: str`

判据（spec D4）：
- `consistent`：variant CI 的 lower 边界 > baseline CI 的 upper 边界，且方向
  匹配 variant 的 success_criterion；
- `not_consistent`：variant CI 的 upper 边界 < baseline CI 的 lower 边界；
- `inconclusive`：CI 重叠（CI 重叠 → 统计上不决定性）

**措辞门禁**（与 `experimental-design` spec 对齐）：`notes` 字段的任何
生成文本 SHALL 使用 "evidence consistent with / not consistent with"；
MUST NOT 包含 "proved / falsified / confirmed / refuted" 关键词。

#### Scenario: baseline + 4 variant 的 contest
- **WHEN** 传入 5 个 SuiteAggregate（baseline + 4 variant），每个 30 seed
- **THEN** ContestReport SHALL 有 5 行；每行含必填字段；baseline 行
  hypothesis 为 None

#### Scenario: 禁用词检测
- **WHEN** ContestReport.notes 生成
- **THEN** 无 note 含 "proved" / "falsified" / "confirmed" / "refuted"
  （可用大小写不敏感 substring 检查）

#### Scenario: Paired mirror delta
- **WHEN** suite 含 A + A'（配对）
- **THEN** A 的行 SHALL 有 `mirror_delta = A_effect - A'_effect`；A' 的行
  SHALL 有 `mirror_delta = A'_effect - A_effect`（对称）


### Requirement: ReportWriter 五幕 Markdown

`synthetic_socio_wind_tunnel/metrics/report.py` SHALL 提供
`ReportWriter.write_markdown(contest: ContestReport, suite_dir: Path)
-> Path`，产出五幕结构 + 每 variant 四段（Diagnosis-Cure-Outcome-Interpretation）
的 markdown 文件。

输出 SHALL 至少包含以下区段：
- `# <suite_name> Rival Hypothesis Contest Report`
- `## Act 1 — Baseline`（Outcome 段自动填 baseline 的 SuiteAggregate
  核心数字；Interpretation 留待作者）
- `## Act 2 — Four Doctors`（每 variant 一个 subsection，Outcome 段自动
  填；Diagnosis 从 variant_metadata 的 `theoretical_lineage` 读）
- `## Act 3 — The Contest`（ContestReport 的表格 + 每行的 evidence_alignment）
- `## Act 4 — Decay`（per-day time series 的 post phase 衰减分析；Outcome
  自动；Interpretation 留待）
- `## Act 5 — The Mirror`（若有 paired mirror：A vs A' 对比；无则标注 N/A）

每个自动填数字的段 SHALL 带 HTML 注释 trace：
`<!-- auto-generated from variant_<name>/aggregate.json; seeds=N -->`

#### Scenario: Baseline + A + A' suite 产出有效 markdown
- **WHEN** 调用 write_markdown 于 3-aggregate suite
- **THEN** 输出 file SHALL 存在且非空；包含全部 5 个 Act 区段；A' 的 Act 5
  含 "mirror_delta" 数字

#### Scenario: Suite 缺 baseline 时警告
- **WHEN** suite 只含 variants（无 baseline）
- **THEN** Act 1 Baseline 区段 SHALL 标注 "⚠️ no baseline run in suite;
  Act 3 contest uses first variant as reference"


### Requirement: Suite CLI

`tools/run_variant_suite.py` SHALL 提供 Suite 级别的命令行入口，支持：

```
--variants baseline,hyperlocal_push,global_distraction,phone_friction,
           shared_anchor,catalyst_seeding
--seeds 30
--num-days 14
--agents 100
--mode publishable
--phase-days 4,6,4
--output-dir data/experiments
--suite-name digital_lure_suite_v1
```

执行流程（spec D6）：
1. 对每 variant 跑 N seed × 14 天
2. 每 run 构造 `TickMetricsRecorder`、组装 RunMetrics、dump JSON
3. Per-variant 跑完后 aggregate
4. 全 variant 跑完后：生成 ContestReport + 写 Markdown 报告
5. 所有产物 dump 到 `<output_dir>/<timestamp>_<suite_name>/`

#### Scenario: 最小 smoke 运行
- **WHEN** `python tools/run_variant_suite.py --variants baseline,hyperlocal_push
  --seeds 2 --num-days 3 --agents 10 --mode dev --phase-days 1,1,1`
- **THEN** 成功退出；产 `data/experiments/<timestamp>_*/`
  含 `variant_baseline/seed_*.json` / `variant_hyperlocal_push/seed_*.json`
  / `contest.json` / `report.md`

#### Scenario: 未知 variant 退出报错
- **WHEN** `--variants unknown_foo`
- **THEN** CLI SHALL exit code ≠ 0；stderr 列出合法 variant 名


### Requirement: build_single_seed_run 接受可选 recorder

`tools/run_multi_day_experiment.py::build_single_seed_run` SHALL 接受
`recorder: TickMetricsRecorder | None = None` kwarg；若非 None，函数
SHALL 把它注册为 orchestrator 的 `on_tick_end` 订阅者。

本 kwarg 默认 None → 与 multi-day-simulation archive 时 signature 等价
（向后兼容 single-day-smoke 与已有 CLI 无变更）。

#### Scenario: 向后兼容
- **WHEN** `build_single_seed_run(seed=42, n_agents=100, ..., recorder=None)`
- **THEN** 行为 SHALL 与不传 recorder 完全一致


### Requirement: 零依赖 numpy / pandas

`metrics` 模块 SHALL 仅使用 Python stdlib + pydantic 已引入的依赖，
**不**引入 numpy / pandas / scipy。所有 median / IQR / CI 用
`statistics` + 手写 percentile（同 `multi-day-run/_series_stats`）。

#### Scenario: 模块 import 不引入 numpy
- **WHEN** `import synthetic_socio_wind_tunnel.metrics` 执行
- **THEN** `sys.modules` 不新增 `numpy` / `pandas` / `scipy` 项


### Requirement: 未来 social-graph / conversation 挂载接口

`RunMetrics` SHALL 通过 `weak_tie_formation_count` / `info_propagation_hops`
/ `extensions` 三个字段为未来 social-graph / conversation change 提供
挂载点；本 change 保持它们 None / 空 dict 默认值。

metrics 模块 SHALL 提供 `RunMetrics.with_extensions(**kwargs) -> RunMetrics`
辅助方法（pydantic `.model_copy(update=...)` 的简化 wrapper），便于未来
capability 以**不破坏 metrics spec** 的方式追加数据。

#### Scenario: 扩展字段写入
- **WHEN** 假想 social-graph change 调 `run_metrics.with_extensions(
  weak_tie_formation_count=12)`
- **THEN** 返回新 RunMetrics 实例，原实例不变；新实例的字段值为 12


### Requirement: 审计翻绿

`synthetic_socio_wind_tunnel.metrics` 模块 SHALL importable；
`fitness-audit` 的 `phase2-gaps.metrics` 探针 SHALL 自动 PASS。

#### Scenario: metrics audit
- **WHEN** 运行 `make fitness-audit`
- **THEN** `phase2-gaps.metrics` AuditResult 的 `status` SHALL 为 `pass`
