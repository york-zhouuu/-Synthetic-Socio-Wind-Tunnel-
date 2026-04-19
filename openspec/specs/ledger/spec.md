# ledger — 动态世界状态

## Purpose
Ledger 是 CQRS 架构中的"命令侧读写层"，保存 Atlas 之外的所有可变事实：
entity 位置、物品归属、容器/门的开闭锁状态、已生成的薛定谔细节、
时间/天气、每个 agent 的认知地图（AgentKnowledgeMap）。
Ledger 是系统内唯一的可变事实来源（single source of truth）。

## Requirements

### Requirement: Entity 状态
系统 SHALL 在 `ledger.models.EntityState` 中维护：
`entity_id`、`location_id`、`position: Coord`、`activity`、`facing`、
`arrived_at: datetime`。

- `Ledger.set_entity`、`get_entity`、`entities_at(location_id)`、`delete_entity`
  SHALL 提供完整 CRUD 与按位置索引的查询。

#### Scenario: 按位置聚合
- **WHEN** 三个 entity 的 `location_id` 都是 `cafe_a`
- **THEN** `Ledger.entities_at("cafe_a")` SHALL 返回这三个 EntityState

### Requirement: 物品位置的互斥保证
`ItemState` SHALL 包含 `item_id`、`name`、`location_id`、`container_id`、
`held_by`、`position`、`is_visible`、`is_hidden`、`discovery_skill`、
`examined_by`、`state`。

- 任意时刻 `location_id` / `container_id` / `held_by` 中 SHALL 恰有一个为非空，
  其它为 `None`，以保证物品不会"分身"。
- 从容器 / 持有者取出物品并放入场地时，Ledger SHALL 一次性完成切换，
  不允许出现中间态。

#### Scenario: 物品位置互斥
- **WHEN** entity 从容器中取出一把钥匙
- **THEN** 该 ItemState 的 `container_id` SHALL 被清空，`held_by` SHALL 设置为该
  entity，且两者不同时存在

### Requirement: 门 / 容器状态机
`DoorState` SHALL 包含 `door_id`、`is_open`、`is_locked`、`last_opened_by`、
`last_opened_at`。
`ContainerState` SHALL 包含 `container_id`、`is_open`、`is_locked`、
`examined_by`、`examination_depth`、`contents_collapsed`、
`collapsed_at`、`collapsed_by`。容器内物品 **不** 存在 `ContainerState.contents`
里；物品通过 `ItemState.container_id` 反向引用容器。

- 锁定的门/容器 SHALL 在 `is_locked=True` 时拒绝被直接打开；
  `open_door` / `open_container` SHALL 先检查 `is_locked` 再改 `is_open`。
- 上锁 / 解锁 SHALL 需要匹配 `required_key_id`；由调用方（simulation）保证持钥方身份。

#### Scenario: 锁门拒开
- **WHEN** 对 `is_locked=True` 的门调用 `Ledger.open_door(door_id)`
- **THEN** 该调用 SHALL 失败或不改变状态，由上层返回锁门错误

### Requirement: 薛定谔细节（GeneratedDetail）
`GeneratedDetail` SHALL 包含 `detail_id`、`target_id`、`content`、
`generated_by`、`generated_at`、`is_permanent`。

- `Ledger.set_detail` / `get_detail` / `details_for(target_id)` SHALL 允许按目标查询。
- 细节一旦生成且 `is_permanent=True`，SHALL 不再被 collapse 重新覆盖，
  以保证同一对象在多次观察间内容一致。

#### Scenario: 重复观察返回同一细节
- **WHEN** 两个不同 entity 依次检查同一抽屉
- **THEN** 第二次检查 SHALL 拿到首次生成并已永久化的 GeneratedDetail，而非新内容

### Requirement: 线索（Clue）与发现
`ClueState` SHALL 包含 `clue_id`、`location_id`、`reveals`、`min_skill`、
`discovered_by: str | None`、`discovered_at: datetime | None`。

- 当前模型 SHALL 以**首位发现者**覆盖 `discovered_by`（非列表累积）。
  若未来需要记录多个发现者，另开 change 改为 list。
- 未发现的线索 SHALL 不向感知层泄露内容，仅暴露存在位置。

#### Scenario: 线索首次发现
- **WHEN** agent 在技能满足 `min_skill` 的前提下发现线索
- **THEN** `ClueState.discovered_by` SHALL 被设为该 agent_id，`discovered_at` 被填充

### Requirement: 时间与天气
Ledger SHALL 暴露 `current_time`（datetime）和 `weather: Weather` 两个
时间/天气状态；`time_of_day: TimeOfDay` SHALL 由 `current_time.hour` 派生
（DAWN / MORNING / AFTERNOON / EVENING / NIGHT），不单独维护。

- `Weather` SHALL 至少覆盖 `CLEAR`、`CLOUDY`、`RAIN`、`HEAVY_RAIN`、`FOG`、`SNOW`。

#### Scenario: time_of_day 随时间推进
- **WHEN** `current_time` 从 06:59 推进到 07:00
- **THEN** `time_of_day` SHALL 从 `DAWN` 变为 `MORNING`

### Requirement: Agent 认知地图
`AgentKnowledgeMap` SHALL 为每个 agent 记录其已知位置的 `AgentLocationKnowledge`，
后者字段为 `loc_id`、`known_name`、`familiarity: LocationFamiliarity`、
`known_affordances`、`subjective_impression`、`last_visit`、`visit_count`、
`learned_from`。

- `LocationFamiliarity` SHALL 至少覆盖
  `UNKNOWN` → `HEARD_OF` → `SEEN_EXTERIOR` → `VISITED` → `REGULAR` 五级。
- `AgentKnowledgeMap.update(loc_id, familiarity, ...)` SHALL 只允许单调提升
  （`order.index(new) > order.index(existing)` 才替换），不回退。

#### Scenario: 听闻一个新地点
- **WHEN** agent 从另一 agent 对话中听说一个从未去过的咖啡馆
- **THEN** 相应的 `AgentLocationKnowledge.familiarity` SHALL 变为 `HEARD_OF`，
  `learned_from` SHALL 记录信息来源 entity id

### Requirement: 跨模块读写契约
Ledger SHALL 只接受经 simulation / collapse / map_service 等上层服务的
显式写入；perception / agent SHOULD 仅通过只读方法读取。

- Ledger 内部 MUST NOT 直接调用 LLM 或其它外部副作用。
- 所有 mutation 函数 SHALL 对关键不变量（物品互斥、门锁状态）做断言式校验。

#### Scenario: 感知层不修改状态
- **WHEN** PerceptionPipeline 在渲染过程中
- **THEN** SHALL 不调用任何 Ledger 的写方法，仅读取当前快照
