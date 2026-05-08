## MODIFIED Requirements

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

若 `social_graph` 在 recorder 构造时注入（social-graph-capability），
`TickMetricsRecorder` SHALL 在 day 结束时额外快照 5 个 social-graph 指标
（详见 social-graph spec）。

若 `conversation` 在 recorder 构造时注入（conversation-capability），
`TickMetricsRecorder` SHALL 在 day 结束时额外快照以下 conversation 指标：

- `info_origins_today`
- `info_shares_today`
- `info_reaching_2plus_today`
- `avg_hops_today`
- `info_target_reach_today`（**新增**，push-content-individualization）：
  当天 first-learned 事件中，learner 的 audience_tag ∈ info.target_audience_tags
  的数量。conversation 注入时填；audience_tag_provider 未注入时为 0。

若 `conversation` 未注入，以上字段保持 None；不影响 baseline 行为。

#### Scenario: 每 tick 采样所有 agents
- **WHEN** 100 agents × 288 tick 的一天跑完
- **THEN** recorder 内部 SHALL 累计 28,800 个 per-agent-tick records

#### Scenario: 无 attention_service 时跳过 AttentionState
- **WHEN** `orchestrator.attention_service is None`
- **THEN** recorder SHALL 继续采集 location_id / encounter / commit 数据；
  AttentionState 字段留 None；不抛异常

#### Scenario: 无 social_graph 时 tie 字段保持默认

- **WHEN** recorder 构造时 social_graph=None
- **THEN** day rollup 中 `tie_count_total` / `tie_count_weak` /
  `tie_count_strong` / `new_ties_today` / `avg_ties_per_agent` SHALL
  全为 None，不抛异常

#### Scenario: social_graph 注入时 day rollup 含 tie 指标

- **WHEN** recorder 构造时注入 social_graph，跑完一天后该 graph 中含 5
  weak ties 和 2 strong ties
- **THEN** 该 day 的 DayMetricsSummary 中 `tie_count_weak == 5`，
  `tie_count_strong == 2`，`tie_count_total == 7`

#### Scenario: 无 conversation 时 info 字段保持默认

- **WHEN** recorder 构造时 conversation=None
- **THEN** day rollup 中 `info_origins_today` / `info_shares_today` /
  `info_reaching_2plus_today` / `avg_hops_today` /
  `info_target_reach_today` SHALL 全为 None

#### Scenario: conversation 注入时 day rollup 含 info 指标

- **WHEN** recorder 构造时注入 conversation；当天 record 了 3 条 origin，
  其中 1 条传播到 hops=2，且其中 2 个 learner 是 target audience
- **THEN** 该 day 的 DayMetricsSummary 中 `info_origins_today == 3`，
  `info_reaching_2plus_today == 1`，`info_target_reach_today == 2`（视
  audience_tag_provider 是否注入；未注入时为 0）

#### Scenario: 采样不影响 tick 性能超过 10%
- **WHEN** 100 agents × 288 tick × 14 day × 1 seed，与无 recorder baseline 比较
- **THEN** wall time 增量 SHALL ≤ 10%（baseline ~10s → 带 recorder ≤ 11s）

### Requirement: 未来 social-graph / conversation 挂载接口

`RunMetrics` SHALL 通过 `weak_tie_formation_count` / `info_propagation_hops`
/ `extensions` 三个字段为 social-graph / conversation 提供挂载点。

`weak_tie_formation_count` SHALL 由 `RunMetrics.from_recorder` 工厂在
recorder 持有 social_graph 时填充：值 = run 末时刻 graph 中 strength ∈
[0.1, 0.5] 的 tie 总数。未注入 social_graph 时保持 None。

`info_propagation_hops` SHALL 由 `RunMetrics.from_recorder` 工厂在
recorder 持有 conversation 时填充为 dict：
```
{
  "info_count_total": int,                      # 一共多少条 info origin
  "max_hop_observed": int,                      # 任一 info 实际最长跳了几跳
  "info_reaching_2plus_hops": int,              # 至少跳到 hops≥2 的 info 数
  "avg_reach_per_info": int,                    # 平均每条 info 到达多少 agent
  "info_within_target_reach": int,              # 新增：触达目标受众内 agents 总数
  "info_outside_target_reach": int,             # 新增：触达目标受众外 agents 总数
  "target_precision": float,                    # 新增：within / (within + outside)
}
```
未注入 conversation 时 `info_propagation_hops` SHALL 保持 None。

新增字段在 `audience_tag_provider` 未注入时取 0 / 0.0；不抛异常。

`RunMetrics.with_extensions(**kwargs) -> RunMetrics` SHALL 保留为
`pydantic .model_copy(update=...)` 简化 wrapper。

#### Scenario: 扩展字段写入

- **WHEN** 调用 `run_metrics.with_extensions(weak_tie_formation_count=12)`
- **THEN** 返回新 RunMetrics 实例，原实例不变

#### Scenario: from_recorder 填充 weak_tie_formation_count

- **WHEN** recorder 持有 social_graph，跑完后 graph 中含 8 weak ties
- **THEN** `RunMetrics.from_recorder(recorder).weak_tie_formation_count == 8`

#### Scenario: from_recorder 填充 info_propagation_hops 含 target_precision

- **WHEN** recorder 持有 conversation + audience_tag_provider；跑完后
  conversation 含 10 条 info，其中 7 条触达内含 30 个 within-target agents
  和 10 个 outside-target agents
- **THEN** `RunMetrics.from_recorder(recorder).info_propagation_hops` SHALL
  含：
  - `info_within_target_reach == 30`
  - `info_outside_target_reach == 10`
  - `target_precision == 0.75`（30/40）

#### Scenario: 未注入 audience_tag_provider 时 target 字段为 0

- **WHEN** conversation 注入但 audience_tag_provider=None
- **THEN** `info_propagation_hops["target_precision"] == 0.0`，
  `info_within_target_reach == 0`，`info_outside_target_reach == 0`；
  其它 4 keys 正常填充

#### Scenario: 未注入 conversation 时整个字段为 None

- **WHEN** recorder 构造时 conversation=None
- **THEN** `RunMetrics.from_recorder(recorder).info_propagation_hops` SHALL
  为 None
