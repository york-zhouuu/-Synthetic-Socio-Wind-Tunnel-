## Why

`Chain-Position: spatial-output`

`docs/agent_system/20-realism-roadmap.md` Stage 5：当前 cafe / park / 任何
location 容量无限。hp variant 推 10 / 100 / 1000 个 agent 都去同一 cafe，
全部"成功到达"，没人被挤走。

后果：
- hp 的最强声明（"把 N 个 agent 拉到同一 location"）当前是 trivial 的：
  无论 N 多大都成立
- 真实城市 cafe 满员时会有溢出：3 个进去、3 个排队、4 个看到挤就走开
- 我们不知道 hp 的"拉力"在多大规模下会失效（carrying capacity / saturation point）
- 答辩问"如果 push 给 100 个 agent 同一 cafe 会发生什么"，当前回答"100 个全去"

本 change = 拟真度 Stage 5，让 hp 的 carrying capacity 可被研究。

## What Changes

- **MODIFIED**：`atlas::OutdoorArea` / `building::Building` —— 增加 `capacity:
  int | None` 字段（None = 无限制；数字 = 上限）
- **MODIFIED**：`engine::SimulationService.move_entity` —— 抵达 location 时
  检查 capacity；如已满：
  - 30% 概率"等待"（waiting MoveIntent，下 tick 重试）
  - 30% 概率"溢出到附近"（重路由到 1000m 内同 area_type 的 alternative）
  - 40% 概率"放弃"（生成 abandon_attempt MemoryEvent，cancel current step）
- **ADDED**：`atlas::POIHeatModel` —— 每 location 每 tick 当前 occupancy 计数；
  hp variant 在 push 选 target 时可考虑当前 heat
- **ADDED**：`metrics::poi_overflow_count` extension field —— 跟踪有多少
  arrival attempts 被 overflow / waited / abandoned
- **NON-GOAL**：不改 atlas data structure（不重抓 OSM 加 capacity 字段）；
  capacity 用 area_type-based default（cafe=15 / park=∞ / street=∞ / shop=8）
- **NON-GOAL**：不实现复杂排队 mechanics（先简单概率）

## Capabilities

### New Capabilities
无。

### Modified Capabilities

- `atlas`: OutdoorArea / Building 加 capacity 字段
- `simulation`: move_entity 抵达时检查 capacity + 三种 overflow 行为
- `metrics`: extensions 加 poi_overflow_count

## Impact

**代码**：
- `atlas/models.py::OutdoorArea` + `Building`：加 `capacity: int | None = None`
- `cartography/lanecove.py`：load 时按 area_type 注 default capacity
  （cafe / restaurant / shop = 8-15；park / street / square = None）
- `engine/simulation.py::move_entity`：抵达时调 `_check_capacity_and_overflow`
- 新建 `atlas/heat.py::POIHeatModel`：sim-level service，跟踪
  `current_occupancy[location_id]`
- `metrics/factory.py`：extensions 加 `poi_overflow_count`
- `policy_hack/variants/hyperlocal_push.py`：push 选 target 时**可选**考虑
  当前 heat（避免推到已满 cafe）

**测试**：
- `tests/test_poi_capacity_overflow.py`：cafe 装满后第 N+1 个 arrival 触发
  overflow 三分支之一
- `tests/test_poi_heat_tracking.py`：每 tick occupancy 准确追踪
- `tests/test_metrics_poi_overflow_count.py`：metric 字段填充

**API / 契约**：
- `OutdoorArea.capacity` 默认 None，向后兼容
- `move_entity` 行为变化：已满 location 时不直接 return success

**外部影响**：
- hp / gd / pf variant 的 encounter density 会下降（部分 arrival overflow）
- realism test 阈值大概率需要再次校准（家人 + capacity 双重影响）
- 工作量：~10-14 天 implement + 2 天 smoke 验证
