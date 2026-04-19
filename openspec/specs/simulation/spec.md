# simulation — 物理交互的写操作

## Purpose
`engine.simulation.SimulationService` 是系统中唯一被允许改变物理世界状态的写入路径：
移动、开/关/锁/解锁门、放置/转移/标记物品、清单发现。所有写操作 SHALL 通过统一的
`SimulationResult` 返回结果与副作用事件列表。

## Requirements

### Requirement: 统一返回值与事件副作用
所有 SimulationService 写方法 SHALL 返回 `SimulationResult`，字段：
`success: bool`、`message: str`、`error_code: SimulationErrorCode`、
`data: dict`、`events: list[WorldEvent]`。

- SHALL 提供工厂 `SimulationResult.ok(message, events=None, **data)` 与
  `SimulationResult.fail(message, error_code, **data)`。
- 失败时 SHALL 不修改 Ledger 任何字段（原子性）。

#### Scenario: 失败不留副作用
- **WHEN** 调用 `move_entity` 指向 Atlas 中不存在的位置
- **THEN** 返回 `success=False`、`error_code=LOCATION_NOT_FOUND`，
  Ledger 内该 entity 的 `location_id` SHALL 保持不变

### Requirement: 实体移动
`move_entity(entity_id, to_location, position: Coord | None = None) → SimulationResult`
SHALL：
1. 校验目标位置在 Atlas 中存在；
2. 更新 Ledger 中该 entity 的 `location_id` 与 `arrived_at`；
3. 通过 `create_movement_event` 生成 3 条事件：`ENTITY_LEFT_ROOM`（源）、
   `SOUND_FOOTSTEPS`、`ENTITY_ENTERED_ROOM`（目标）。

#### Scenario: 正常移动
- **WHEN** entity 从 `street_seg_1` 移动到 `cafe_a`
- **THEN** 返回 `success=True`，Ledger 中该 entity `location_id=cafe_a`，
  `events` 至少包含一个 `ENTITY_ENTERED_ROOM(location_id=cafe_a)`

### Requirement: 门操作方法集
SimulationService SHALL 提供：
- `open_door(door_id, entity_id)`
- `close_door(door_id, entity_id)`
- `lock_door(door_id, entity_id, key_id: str | None = None)`
- `unlock_door(door_id, entity_id, key_id: str | None = None)`

规则：
- `open_door` 在门 `DoorState.is_locked=True` 时 SHALL 失败，
  `error_code=SimulationErrorCode.DOOR_LOCKED`。
- `lock_door` / `unlock_door` SHALL 校验：若 `DoorDef.lock_key_id` 指定了钥匙，
  entity 必须持有该钥匙；否则返回 `KEY_NOT_HELD` 或 `KEY_REQUIRED`。
- 成功开门 SHALL 产生 `SOUND_DOOR_OPEN` 事件。

#### Scenario: 无钥匙尝试解锁
- **WHEN** entity 未持有 `key_001` 却调用 `unlock_door(door_id, entity_id, "key_001")`
- **THEN** 返回 `success=False`，`error_code=KEY_NOT_HELD`

### Requirement: 物品位置变更方法集
SimulationService 以若干**粒度化**方法替代"拾取 / 放下"的二元抽象：
- `place_item(item, location_id=None, container_id=None, held_by=None, position=None)`
  —— 把物品放到三选一的位置；
- `move_item_to_location(item_id, location_id)` —— 移到某位置（等价于放下）；
- `move_item_to_container(item_id, container_id)` —— 放入容器（服从容器容量）；
- `give_item_to_entity(item_id, entity_id)` —— 移交给某 entity（等价于拾取 / 交接）；
- `mark_item_examined(item_id, by: str)` —— 记录被检查过；不生成细节。

- 转移操作 SHALL 先清空旧的 `location_id / container_id / held_by`，再写新值，
  保持 `ItemState` 的位置互斥不变量（见 ledger spec）。
- 容器超过 `ContainerDef.item_capacity` 时 SHALL 返回 `CONTAINER_FULL`。

#### Scenario: 放入超载容器被拒
- **WHEN** 目标容器已达 `item_capacity`
- **THEN** `move_item_to_container` SHALL 返回 `success=False, error_code=CONTAINER_FULL`

### Requirement: 线索发现
SimulationService SHALL 提供：
- `inject_clue(clue_id, location_id, ...)` —— 注入线索至场景；
- `discover_clue(clue_id, by: str)` —— 由某 entity 发现线索；
- `process_discoveries(...)` —— 批量处理检查触发的发现。

- `discover_clue` 首次成功时 SHALL 写入 `ClueState.discovered_by`、
  `discovered_at`，并产生 `CLUE_DISCOVERED` 事件。

#### Scenario: 重复发现幂等
- **WHEN** agent 对已发现的 clue 再次调用 `discover_clue`
- **THEN** SHALL 不重复写入；可返回 `CLUE_ALREADY_DISCOVERED` 或 success=True

### Requirement: 时间与天气推进
- `advance_time(minutes: int)` SHALL 把 `Ledger.current_time` 前推指定分钟数。
- `set_weather(weather: str)` SHALL 把 `Ledger.weather` 设置为给定值。
- 两者 SHALL 不产生实体移动事件。

#### Scenario: 跨时段推进
- **WHEN** 于 06:30 调用 `advance_time(60)`
- **THEN** `current_time=07:30`，`time_of_day` 由 `DAWN` 过渡到 `MORNING`

### Requirement: 事件与观察者感知的解耦
SimulationService SHALL 只生成事件，不直接通知任何 agent；
事件的传播与听觉/视觉判定由 perception 层按 `audible_range` / `visible_range` 计算。

#### Scenario: 隔房间的脚步声
- **WHEN** entity 在相邻房间移动产生 `SOUND_FOOTSTEPS`
- **THEN** perception 层 SHALL 根据距离与 `audible_range` 决定是否出现在
  当前观察者的 `SubjectiveView`

### Requirement: 错误码完整覆盖
失败时 `error_code` SHALL 属于 `SimulationErrorCode` 枚举，至少覆盖：
`SUCCESS`、`LOCATION_NOT_FOUND`、`LOCATION_UNREACHABLE`、`ALREADY_AT_LOCATION`、
`DOOR_NOT_FOUND`、`DOOR_LOCKED`、`DOOR_ALREADY_OPEN`、`DOOR_ALREADY_CLOSED`、
`DOOR_CANNOT_LOCK`、`KEY_REQUIRED`、`KEY_NOT_HELD`、
`ENTITY_NOT_FOUND`、`ENTITY_CANNOT_ACT`、
`ITEM_NOT_FOUND`、`ITEM_NOT_ACCESSIBLE`、`ITEM_ALREADY_HELD`、
`CONTAINER_FULL`、`CONTAINER_LOCKED`、
`CLUE_NOT_FOUND`、`CLUE_ALREADY_DISCOVERED`、`SKILL_INSUFFICIENT`、
`INVALID_OPERATION`、`PRECONDITION_FAILED`、`UNKNOWN_ERROR`。

#### Scenario: 容器已满
- **WHEN** 尝试把物品放入已满容器
- **THEN** SHALL 返回 `CONTAINER_FULL` 错误码

### Requirement: 已知未实现事件（待补）
`EventType.SOUND_ITEM_PICKUP` / `SOUND_ITEM_DROP` 已在 `core.errors.EventType`
中定义，但当前 SimulationService 的物品方法 **尚未**产生这些事件。

- 本条 SHOULD 在 Phase 2 的 `conversation` / 感知打磨阶段补齐。
- 任何新增方法 SHALL 在 `give_item_to_entity` / `move_item_to_location` 中
  叠加对应的 `SOUND_ITEM_*` 事件，不得绕过事件机制直接修改 Ledger。

#### Scenario: 未来合规拾取
- **WHEN** 补齐后，`give_item_to_entity` 成功返回
- **THEN** `events` SHALL 包含一条 `SOUND_ITEM_PICKUP`
