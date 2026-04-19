# map-service — agent 面向的统一地图查询接口

## Purpose
`map_service` 是 agent 与世界之间的"窄门"：它把 Atlas（静态）+ Ledger
（动态、认知地图）合成为适合 LLM 决策的结构化信息，并**只暴露 agent 已知的内容**。
所有面向 agent prompt 的地图/场景查询 SHALL 经过此服务，保证信息边界一致。

## Requirements

### Requirement: 已知目的地列表
`get_known_destinations(agent_id) → list[KnownDestination]` SHALL 只返回
该 agent 的 `AgentKnowledgeMap` 中 `familiarity >= HEARD_OF` 的位置。

- `KnownDestination` SHALL 含：`loc_id`、`known_name`、`familiarity`、
  `loc_type`、`subtype`、`known_affordances`、`subjective_impression`、
  `last_visit`、`visit_count`、`learned_from`、`center(x, y)`。

#### Scenario: 陌生位置不返回
- **WHEN** agent 的认知地图中某地为 `UNKNOWN`
- **THEN** 返回列表 SHALL 不含该地点，即使其他 agent 都知道

### Requirement: 当前场景快照
`get_current_scene(agent_id) → CurrentScene` SHALL 返回 agent 当前位置的：
`location_id`、`location_name`、`present_entities`、`present_items`、
`active_affordances`、`ambient_description`。

- `active_affordances` 中 SHALL 按 `time_range` 与 `current_time` 过滤出当前可用项。

#### Scenario: 咖啡馆打烊后
- **WHEN** 当前时间 23:30，某咖啡馆 `time_range=07:00-22:00`
- **THEN** `active_affordances` SHALL 不包含"点咖啡"这条 affordance

### Requirement: 位置细节分级
`get_location_detail(agent_id, location_id) → LocationDetail` SHALL 按
`AgentLocationKnowledge.familiarity` 分级返回信息：
- `UNKNOWN` → 抛错或返回空；
- `HEARD_OF` → 仅 `known_name`、粗略类型；
- `SEEN_EXTERIOR` → 以上 + `entry_signals`；
- `VISITED` 以上 → 以上 + 完整 `affordances` + `typical_sounds/smells`。

#### Scenario: 未进入过的图书馆
- **WHEN** agent 对一个 `SEEN_EXTERIOR` 的图书馆调用此接口
- **THEN** 返回的 `LocationDetail.affordances` SHALL 为空或仅给出门口标识

### Requirement: 路径带感知
`plan_route(agent_id, from_id, to_id) → RouteWithPerception` SHALL：
- 委托 `navigation.NavigationService` 规划路径；
- 为每一步返回 `RouteStep`（`loc_id`、`loc_name`、`loc_type`、`path_type`、
  `distance_m`、`cumulative_distance_m`）；
- 收集 `locations_passed`，供上层在移动时更新认知地图。

- 若 agent 目的地 `familiarity=UNKNOWN`，SHALL 拒绝规划并返回错误。

#### Scenario: 路过一个新位置
- **WHEN** agent 沿路径走过一个此前 `UNKNOWN` 的商店
- **THEN** map_service SHALL（由调用方触发）将其 familiarity 升至
  `SEEN_EXTERIOR`，并在 `learned_from` 填入"途经"

### Requirement: 附近实体（现通过 CurrentScene 暴露）
当前 MapService **未单独提供** `get_nearby_entities` 方法；
同一位置的其它 entity 信息 SHALL 通过 `get_current_scene.present_entities`
（`list[EntitySnapshot]`）暴露。

- `NearbyEntity` 模型在 `map_service.models` 中已定义，预留给 Phase 2
  `orchestrator` 引入"路径相遇"检测时使用；届时另开 change 新增
  `get_nearby_entities`。

#### Scenario: 当前场景含同房间实体
- **WHEN** agent 在咖啡馆，另有 2 位 entity 也在咖啡馆
- **THEN** `get_current_scene(agent_id, "cafe_a").present_entities` SHALL 包含
  这 2 位对应的 EntitySnapshot

### Requirement: 描述而非评分
所有返回给 agent 的字段 SHALL 以自然语言 / 枚举描述，MUST NOT 使用
数值打分（如 `comfort_score=0.7`、`safety=0.3`）。

- 判断交给 agent 的 LLM，基于描述与人格推理。

#### Scenario: 拒绝评分字段
- **WHEN** 向 `AffordanceInfo` 新增字段的 PR
- **THEN** 评审 SHALL 拒绝带分数评价字段，仅允许描述类字段通过

### Requirement: 熟悉度单调提升
通过 map_service 的副作用（如路过、进入、被告知）更新
`AgentLocationKnowledge.familiarity` 时 SHALL 只升不降，除非上层显式请求降级。

#### Scenario: 多次访问
- **WHEN** 同一地点被同 agent 访问多次
- **THEN** `visit_count` SHALL 递增；`familiarity` 从 `VISITED` 升为 `REGULAR`
  的阈值由实现决定（例如 `visit_count >= 5`）
