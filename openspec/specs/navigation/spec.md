# navigation — 路径规划

## Purpose
`engine.navigation.NavigationService` 在 Atlas 静态连接图与 Ledger 动态门锁状态
之上，为 agent 提供门感知、策略可选的路径规划，输出逐步的 NavigationStep，
使 simulation / agent 能按步推进移动。

## Requirements

### Requirement: 路径规划主入口
`find_route(from_id, to_id, strategy=PathStrategy.SHORTEST) → NavigationResult`
SHALL 返回：
- `success: bool`
- `from_location`、`to_location`
- `steps: list[NavigationStep]`
- `total_distance: float`
- `doors_to_pass: list[str]`
- `locked_doors: list[str]`
- `error: str | None`

#### Scenario: 拓扑不连通
- **WHEN** 源与目标在 Atlas 连接图上不连通
- **THEN** 返回 `success=False`，`error` 简要说明原因

### Requirement: 策略（PathStrategy）
`PathStrategy` SHALL 至少提供三种：
- `SHORTEST` — 最小化总距离；
- `FEWEST_DOORS` — 最小化途经门数量；
- `AVOID_LOCKED` — 绕开所有 `is_locked=True` 的门，若无法绕开则 `success=False`。

#### Scenario: 避开锁门
- **WHEN** 使用 `AVOID_LOCKED` 规划至后院
- **THEN** `steps` SHALL 不包含任何锁门，`locked_doors` SHALL 为空

### Requirement: NavigationStep 的最小可执行性
`NavigationStep` SHALL 包含 `from_location`、`to_location`、`action`
（`walk` / `enter_building` / `exit_building` / `open_door` / `unlock_door`）、
`distance`、`door_id`、`description`。

- 每个 step SHALL 可独立映射到 SimulationService 的一次调用（移动或开门）。

#### Scenario: 路径可逐步执行
- **WHEN** agent 按顺序对每个 NavigationStep 的 `action` 调用对应的 simulation 方法
- **THEN** 最终 entity `location_id` SHALL 等于 `to_location`

### Requirement: 街道段感知
Navigation 在遍历 Atlas 时 SHALL 把街道段（`OutdoorArea(area_type="street")`）
视为正常位置参与 A*，不得把同一道路的多段压缩为单一"街道"节点。

- 相邻 segment 间的 `Connection(path_type="road"/"intersection")`
  SHALL 被计入 `total_distance`。

#### Scenario: 同路多段
- **WHEN** 规划从 `street_main_01` 到 `street_main_05`
- **THEN** `steps` SHALL 为 4 个逐段 walk，而非跳跃

### Requirement: 路径可人读
`NavigationResult.describe()` SHALL 返回面向 LLM / 日志的自然语言路径描述，
用于 agent 推理与调试日志。

#### Scenario: 描述字符串
- **WHEN** 对一条含 2 条街道 + 1 扇门的路径调用 `describe()`
- **THEN** 返回字符串 SHALL 提及两段街道名与门的动作（"open the wooden door"）

### Requirement: 动态状态一致性
Navigation SHALL 每次调用时读取 Ledger 的最新门锁/容器状态，
不得缓存跨调用的门锁快照。

#### Scenario: 门状态变化
- **WHEN** 一次调用中 door_123 为 locked；下一次调用前被 simulation 解锁
- **THEN** 第二次 `find_route(..., SHORTEST)` SHALL 能把该门作为普通 `open_door` step

### Requirement: Atlas 的静态 find_path 与 navigation 的区分
`atlas.service.Atlas.find_path` 存在并返回纯静态拓扑路径（不考虑门锁 / 动态阻塞）。
agent 决策 SHOULD 使用 `navigation.find_route`；`Atlas.find_path` 仅供低层工具 / 诊断使用。

#### Scenario: 两个 find_* 同名不冲突
- **WHEN** 同一代码同时持有 Atlas 和 NavigationService
- **THEN** `atlas.find_path(a, b)` 给纯拓扑结果；
  `navigation_service.find_route(a, b)` 给带门锁的可执行步骤
