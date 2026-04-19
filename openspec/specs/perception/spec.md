# perception — 主观感知与认知可见性

## Purpose
`perception` 模块是"剧组模型"中的摄影机：把 Atlas + Ledger 的客观状态，
经由观察者上下文（技能、情绪、知识、秘密）过滤成主观的 `SubjectiveView`。
perception 只读，不修改世界；同一场景对不同观察者产生不同视角（罗生门效应）。

## Requirements

### Requirement: 感知主入口
`perception.pipeline.PerceptionPipeline.render(observer_context) → SubjectiveView`
SHALL 按以下顺序执行：
1. 采集：从 Atlas + Ledger 取观察者当前位置的客观数据；
2. 可见性过滤：lighting、墙体、距离、信息边界；
3. 解释：基于观察者 `skills` 与 `emotional_state` 应用 filter；
4. 渲染：产出 `SubjectiveView`（实体/物品/线索/声音/气味快照）；
5. 可选叙事：若提供 callback，将快照转写为自然语言描述。

#### Scenario: 管线不产生副作用
- **WHEN** `render` 运行完毕
- **THEN** Ledger 内状态 SHALL 与调用前完全一致

### Requirement: ObserverContext 携带主观要素
`ObserverContext` SHALL 至少包含：`entity_id`、`position`、`location_id`、
`skills: dict[str, float]`（含 perception、investigation）、
`knowledge`（已知事实列表）、`suspicions`、`secrets`、
`emotional_state: dict[str, float]`（含 guilt、curiosity、anxiety 等）、
`looking_for`、`attention`、`vision_impaired`、`hearing_impaired`。

- 便捷访问器 `get_skill(name, default=0.5)` 与 `get_emotion(name, default=0.0)`
  提供带默认值的读取；SHALL 同时暴露 `investigation_skill`、`perception_skill`、
  `guilt_level`、`anxiety_level` 四个 property。
- skills 未提供时按默认 0.5（中性）；emotional_state 未提供时按默认 0.0（无情绪）。

#### Scenario: 两个观察者不同视角
- **WHEN** A（`guilt=0.8`）与 B（`guilt=0.0`）看同一屋子的血渍
- **THEN** A 的 `SubjectiveView.observations` 中该血渍的 `interpreted`
  SHALL 体现更强的不安 / 指向性；B 的描述 SHALL 更中性

### Requirement: SubjectiveView 数据结构
`SubjectiveView` SHALL 包含：`observer_id`、`location_id`、`location_name`、
`observations: list[Observation]`、以及两套并列的可见数据：
- 兼容字段：`entities_seen: list[str]`、`items_noticed: list[str]`、
  `clues_found: list[str]`（仅 ID）；
- 快照字段：`entity_snapshots: list[EntitySnapshot]`、
  `item_snapshots: list[ItemSnapshot]`、
  `container_snapshots: list[ContainerSnapshot]`、
  `clue_snapshots: list[ClueSnapshot]`；

以及环境：`lighting`、`ambient_sounds`、`ambient_smells`、`narrative`、
`timestamp`、`weather`。

- `Observation` 字段：`sense: SenseType`、`source_id`、`source_type`、
  `source_location`、`confidence`、`distance`、`raw`、`interpreted`、
  `is_notable`、`tags: list[str]`。
- `ItemSnapshot.location_type` SHALL 标注 `floor` / `surface` / `container` / `held`。

#### Scenario: 显著观察过滤
- **WHEN** 调用 `SubjectiveView.get_notable_observations()`
- **THEN** SHALL 返回 `is_notable=True` 的观察子集

### Requirement: 多模态滤镜
`perception.filters` SHALL 提供至少以下类别：
- `physical`（视线、墙体、距离）
- `environmental`（光线、天气、时段）
- `audio`（声音半径、穿墙衰减）
- `olfactory`（气味扩散与持续时间）
- `skill`（perception / investigation 阈值决定是否揭示隐藏物）

- 滤镜实现 SHALL 继承自 `filters.base` 的统一接口，可组合成管线。

#### Scenario: 黑夜中减少可见细节
- **WHEN** `time_of_day=NIGHT` 且房间光线暗
- **THEN** environmental 滤镜 SHALL 降低远距离物品的 visible 细节，
  `ItemSnapshot.visible_state` 只给出粗略描述

### Requirement: 信息边界
观察者 SHALL 仅看到：当前位置 + 通过门窗直接可见的相邻位置 +
自身 `AgentKnowledgeMap` 中已有的记忆位置。未知位置 SHALL 不出现在
`SubjectiveView` 或任何子字段中，避免剧透。

#### Scenario: 未知建筑不泄露
- **WHEN** agent 尚未听说过某图书馆
- **THEN** 即使该图书馆在街对面可见，其名字也 SHALL 以"一栋不认识的建筑"
  这类描述出现，而非直接给出 `location_name`

### Requirement: 容器的"首查塌缩"
当观察者首次检查容器时，perception SHALL 触发 collapse 生成容器内细节，
并在 `ContainerSnapshot.is_collapsed=True` 中标记该事实。

- 后续观察者看到的 `visible_contents` / `surface_items` SHALL 与首次生成一致。

#### Scenario: 抽屉首次打开
- **WHEN** agent 首次打开一个抽屉
- **THEN** 该 `ContainerSnapshot.is_collapsed` SHALL 为 `True`，且后续访问一致

### Requirement: 认知地图浏览（Exploration）
`perception.exploration.ExplorationService` SHALL 提供：
- `get_visible_layout(observer_id, location_id) → VisibleLayout` — 返回当前房间 +
  可视相邻位置 + 记忆中已知位置。`observer_id` 用于查询其个人认知地图。
- `get_location_visibility(...) → LocationVisibility` — 将可见性分级为
  `"full"`（已访问）/`"partial"`（见过外观）/`"name_only"`（听说过）/
  `"unknown"`（完全未知），以小写字符串返回。

- 结果 SHALL 不揭示 agent 未达到相应 familiarity 的任何内部信息。

#### Scenario: 仅听说过的咖啡馆
- **WHEN** agent 的认知地图中该咖啡馆为 `HEARD_OF`
- **THEN** `LocationVisibility.visibility_level` SHALL 为 `"name_only"`，
  返回对象不包含内部 affordance
