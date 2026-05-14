## MODIFIED Requirements

### Requirement: RunMetrics 数据模型

`synthetic_socio_wind_tunnel/metrics/models.py` SHALL 定义
`RunMetrics` Pydantic frozen 模型，至少含：

- `seed: int`
- `variant_name: str`（"baseline" 为默认）
- `num_days: int`
- `per_day: tuple[DayMetricsSummary, ...]`
- `trajectory_deviation_m: float | None = None`（**push-target subset median**：仅对 `variant_metadata["target_agent_ids"]` 中 agent 计算到 target_location 的 median 距离；缺省时为 None）
- `trajectory_deviation_m_all: float | None = None`（**all-agent median**，sanity 对照；hp/gd 计算，其它 variant 为 None）
- `encounter_stats: dict[str, float]`（total / per_day_median / diversity）
- `space_activation: dict[str, float]`（location → cumulative dwell_tick_count）
- `feed_stats: dict[str, int]`（per FeedSource delivered / suppressed）
- `attention_allocation_ratio: dict[str, float] | None = None`
  （`physical_world / phone_feed / task / conversation`；avg across run）
- `weak_tie_formation_count: int | None = None`（`social-graph` 填）
- `info_propagation_hops: dict[str, int] | None = None`（`conversation` 填）
- `extensions: dict[str, Any] = {}`（未来 recorder 挂载用）

**语义变更说明**：原 `trajectory_deviation_m` 在 100 个 agent 上取 median 会被 90 个 scripted agent 稀释（参见 `docs/audit/2026-05-09-bug-hunt.md` B1）。本 change 收紧为"push 真实作用对象的子集"，让 thesis 信号在 metric 上可见。

#### Scenario: 构造完整 RunMetrics 并 JSON dump
- **WHEN** 14 天 run 结束，构造 RunMetrics；调 `.model_dump_json()`
- **THEN** 输出 SHALL 是 JSON-safe 字符串；可往返 parse 回等价 model

#### Scenario: 未填字段默认 None
- **WHEN** 现阶段（social-graph / conversation 未归档）构造 RunMetrics
- **THEN** `weak_tie_formation_count` SHALL 为 None；`info_propagation_hops`
  SHALL 为 None

#### Scenario: traj_dev_m 与 traj_dev_m_all 的 baseline 行为
- **WHEN** variant_name == "baseline"，构造 RunMetrics
- **THEN** `trajectory_deviation_m` SHALL 为 None；`trajectory_deviation_m_all` SHALL 为 None

#### Scenario: traj_dev_m 与 traj_dev_m_all 的 hyperlocal_push 行为
- **WHEN** variant_name == "hyperlocal_push"，variant_metadata 提供 target_location 与 target_agent_ids（10 个 protag）
- **THEN** `trajectory_deviation_m` SHALL 是 10 个 protag 到 target 的 median；`trajectory_deviation_m_all` SHALL 是 100 个 agent 的 median；两者通常显著不同


### Requirement: RunMetrics.from_recorder 工厂

`RunMetrics.from_recorder(recorder, multi_day_result, variant_metadata)` SHALL
把 TickMetricsRecorder 的累积数据 + MultiDayResult + variant metadata 合并
为 RunMetrics 实例。

trajectory_deviation_m 计算 SHALL：

```
1. 对每 agent：
    intervention_end_loc = location_id at end of intervention phase
2. 若 variant 是 hyperlocal_push / global_distraction：
    target_ids = variant_metadata.get("target_agent_ids") or set()
    target_loc = variant_metadata.get("target_location")
    distances_target = [
        euclidean(intervention_end_loc_center, target_loc_center)
        for agent_id in target_ids if agent_id in end_locations
    ]
    distances_all = [...same calc on all agents in end_locations...]
    trajectory_deviation_m     = median(distances_target) if distances_target else None
    trajectory_deviation_m_all = median(distances_all) if distances_all else None
3. 其它 variant：两值都留 None
```

**注意**：当 `target_agent_ids` 缺省（如 hyperlocal_push 的早期实例没注入这个字段），factory SHALL fallback 到 `[rt.profile.agent_id for rt in runtimes if rt.profile.is_protagonist]`，与 ai-town port 后的 protag set 对齐。

#### Scenario: 从 recorder + result 组装
- **WHEN** `RunMetrics.from_recorder(recorder=rec, multi_day_result=result,
  variant_metadata=v.metadata_dict())`
- **THEN** 返回实例的 `seed` / `variant_name` / `num_days` SHALL 与输入一致；
  `per_day` SHALL 有 num_days 条

#### Scenario: target_agent_ids 缺省时 fallback 到 protag
- **WHEN** variant_metadata 不含 target_agent_ids；runtimes 中有 10 个 is_protagonist=True 的 agent
- **THEN** trajectory_deviation_m SHALL 在这 10 个 agent 上计算 median；不应退回到 100 个 agent 的全集
