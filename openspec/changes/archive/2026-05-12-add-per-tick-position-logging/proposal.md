## Why

Per-tick agent positions 未存储是已知限制——每个 `seed_X.json` 只记录
`end_of_day_location_by_agent`（每天 1 个位置点）+ `location_dwell_ticks`
（聚合，不分 agent）。

后果：

- 3D dashboard 看 14 天 agent 活动只能看 14 个晚上点 → 无法 review 白天行为
- debug 不直观——agent 中午去了哪家咖啡馆 / 哪条路通勤都不知道
- thesis 论证"看到附近邻居"的可视化无法做（不知道两 agent 何时同 location）

## What Changes

- 新增 `PositionTraceRecorder`：订阅 `Orchestrator.on_tick_end`，**稀疏**记录
  agent 位置 CHANGE 事件（不是每 tick 都记，只记位置变化）
- 扩 `TickResult.entity_locations: tuple[(str, str), ...]` 字段供
  recorder 消费（end-of-tick 每个 agent 的 location_id 快照）
- Suite 写独立 `seed_<N>_positions.json` 文件（不嵌入主 metrics JSON 保持
  主文件 lean）
- 文件 schema: `{schema: "position_trace_v1", n_changes, changes: [{tick, day, agent_id, location_id}]}`

存储估算：100 agent × 14 day × ~20 moves/agent/day ≈ 28k entries ≈ 1-2MB JSON。
1000 agent × 15 seed publishable run 估 ~150MB total，独立文件可按需懒加载。

### Non-goals

- 不改 RunMetrics（新数据写独立文件，不污染主 metrics）
- 不改 dashboard（下一个 change 单独做"3D dashboard 接入 position trace"）
- 不改 1000-agent publishable 协议

## Capabilities

### Modified Capabilities

- `orchestrator`: `TickResult` 增 `entity_locations` 字段
- `metrics`: 新增 `PositionTraceRecorder` + `PositionChange` 模型

## Impact

- 代码：
  - `orchestrator/models.py`（TickResult.entity_locations）
  - `orchestrator/service.py`（_run_tick 填入 entity_locations）
  - `metrics/position_trace.py`（new file - 76 行）
  - `metrics/__init__.py`（re-export）
  - `tools/run_variant_suite.py`（注册 recorder + 写文件）
- 测试：`tests/test_position_trace.py`（5 scenarios）
- 数据：每个 seed 新增一个 `seed_<N>_positions.json` 文件
