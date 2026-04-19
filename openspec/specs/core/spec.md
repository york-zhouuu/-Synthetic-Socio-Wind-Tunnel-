# core — 共享类型与事件

## Purpose
定义被所有上层模块（atlas / ledger / engine / perception / agent）共用的基础类型、
事件模型与错误代码，避免跨层耦合。core 只定义数据与枚举，不含业务逻辑。

## Requirements

### Requirement: 欧氏坐标与多边形
系统 SHALL 在 `core.types` 中提供 `Coord(x, y)` 与 `Polygon(vertices)` 作为所有模块共享的几何基元。
- Coord 的单位 SHALL 为"米"，且 `distance_to` 使用欧氏距离。
- Polygon SHALL 至少包含 3 个顶点，顺时针排列；`contains(point)` 使用射线法判定。
- 两者 SHALL 为不可变（frozen）且可哈希，可作为字典键。

#### Scenario: 同一坐标用于多模块
- **WHEN** atlas 用 `Coord` 表示建筑中心、ledger 用 `Coord` 表示 entity 位置
- **THEN** 两处 SHALL 使用同一类型，且能通过 `a.distance_to(b)` 直接计算距离

#### Scenario: 多边形包含判定
- **WHEN** 调用 `Polygon(vertices).contains(point)`
- **THEN** SHALL 对位于多边形内部的 `Coord` 返回 `True`，对外部返回 `False`

### Requirement: WorldEvent 作为不可变事实
系统 SHALL 在 `core.events` 中提供 `WorldEvent`，承载引擎动作产生的事实：
字段包括 `event_type`、`location_id`、`actor_id`、`target_id`、
`audible_range`、`visible_range`、`properties`、`timestamp`。

- WorldEvent 一经构造 SHALL 不可修改。
- 系统 SHALL 提供工厂函数 `create_movement_event`、`create_door_event`、
  `create_discovery_event` 等，为不同事件类型设定一致的感知传播半径。

#### Scenario: 门开启事件传播
- **WHEN** SimulationService 成功开门
- **THEN** SHALL 生成一条 `EventType.SOUND_DOOR_OPEN` 的 WorldEvent，
  `audible_range` SHALL 大于 0，供 perception 听觉滤镜消费

### Requirement: 结构化错误代码
系统 SHALL 定义 `SimulationErrorCode` 枚举，覆盖 location / door / entity /
item / container / clue / precondition 等全部可失败路径。

- 引擎返回的失败 SHALL 使用枚举值而非错误字符串，便于 agent 做确定性响应。

#### Scenario: agent 基于错误代码决策
- **WHEN** `SimulationService.move_entity` 因目标不可达失败
- **THEN** 返回的 `SimulationResult.error_code` SHALL 为
  `SimulationErrorCode.LOCATION_UNREACHABLE`，agent 据此走重规划分支

### Requirement: EventType 覆盖多模态感知
`EventType` SHALL 至少覆盖以下类别以支撑多模态感知：
- 移动类（`ENTITY_MOVED`、`ENTITY_ENTERED_ROOM`、`ENTITY_LEFT_ROOM`）
- 听觉类（`SOUND_FOOTSTEPS`、`SOUND_DOOR_OPEN`、`SOUND_ITEM_PICKUP`）
- 交互类（门、容器、物品）
- 发现类（线索、细节）
- NPC 提醒类

#### Scenario: 拾取物品产生声响
- **WHEN** 某 entity 在房间内拾取物品
- **THEN** SHALL 产生 `SOUND_ITEM_PICKUP` 事件，可被同房间其它观察者听到
