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
`TickMetricsRecorder` SHALL 在 day 结束时额外快照以下 social-graph 指标：

- `tie_count_total`（service 中 ties 总数）
- `tie_count_weak`（strength ∈ [0.1, 0.5] 的 tie 数）
- `tie_count_strong`（strength > 0.5 的 tie 数）
- `new_ties_today`（first_seen_day == current day_index 的 tie 数）
- `avg_ties_per_agent`（`sum(len(ties_for(a)) for a in agents) / num_agents`）

若 `social_graph` 未注入，以上字段保持 None / 0；不影响 baseline 行为。

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
  全为 None（或省略），不抛异常

#### Scenario: social_graph 注入时 day rollup 含 tie 指标

- **WHEN** recorder 构造时注入 social_graph，跑完一天后该 graph 中含 5
  weak ties 和 2 strong ties
- **THEN** 该 day 的 DayMetricsSummary 中 `tie_count_weak == 5`，
  `tie_count_strong == 2`，`tie_count_total == 7`

#### Scenario: 采样不影响 tick 性能超过 10%
- **WHEN** 100 agents × 288 tick × 14 day × 1 seed，与无 recorder baseline 比较
- **THEN** wall time 增量 SHALL ≤ 10%（baseline ~10s → 带 recorder ≤ 11s）

### Requirement: 未来 social-graph / conversation 挂载接口

`RunMetrics` SHALL 通过 `weak_tie_formation_count` / `info_propagation_hops`
/ `extensions` 三个字段为未来 social-graph / conversation change 提供
挂载点。

`weak_tie_formation_count` SHALL 由 `RunMetrics.from_recorder` 工厂在
recorder 持有 social_graph 时填充：值 = run 末时刻 graph 中 strength ∈
[0.1, 0.5] 的 tie 总数（即"已建立的弱关系"数量）。未注入 social_graph
时保持 None。

`info_propagation_hops` 仍为未来 conversation-capability 预留，本 change
保持 None / 空 dict。

`RunMetrics.with_extensions(**kwargs) -> RunMetrics` SHALL 保留为
`pydantic .model_copy(update=...)` 简化 wrapper，便于其它 capability
追加自定义字段而不破坏 metrics spec。

#### Scenario: 扩展字段写入
- **WHEN** 调用 `run_metrics.with_extensions(weak_tie_formation_count=12)`
- **THEN** 返回新 RunMetrics 实例，原实例不变；新实例的
  `weak_tie_formation_count` 为 12

#### Scenario: from_recorder 填充 weak_tie_formation_count

- **WHEN** recorder 持有 social_graph，跑完后 graph 中含 8 weak ties 和
  3 strong ties
- **THEN** `RunMetrics.from_recorder(recorder)` 返回的 metrics 中
  `weak_tie_formation_count == 8`（不含 strong ties）

#### Scenario: 未注入时保持 None

- **WHEN** recorder 构造时 social_graph=None
- **THEN** `RunMetrics.from_recorder(recorder).weak_tie_formation_count`
  SHALL 为 None
