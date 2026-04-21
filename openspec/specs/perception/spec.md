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

---

<!-- Added by realign-to-social-thesis (archived 2026-04-20) -->

### Requirement: ObserverContext 扩展数字注意力状态

`perception.models.ObserverContext` SHALL 新增可选字段
`digital_state: AttentionState | None = None`（`AttentionState` 定义在
`attention-channel` spec）。

- 默认 `None` SHALL 使所有已有构造调用兼容；
- 字段 SHALL 不可变；新数据通过构造新 ObserverContext 替换；
- 现有 `skills` / `emotional_state` / `knowledge` / `suspicions` / `secrets`
  等字段 SHALL 保持不变。

#### Scenario: 现有 ObserverContext 构造不受影响
- **WHEN** 代码 `ObserverContext(entity_id=..., position=..., location_id=...)`
- **THEN** 构造 SHALL 成功，`digital_state` SHALL 为 `None`

### Requirement: SenseType 扩展数字感知

`perception.models.SenseType` 枚举 SHALL 新增 `DIGITAL`，表示通过手机 / 推送
/ feed 获得的感知。

- `Observation.sense=SenseType.DIGITAL` 的观察 SHALL 具备非空 `source_id`
  （指向 FeedItem.feed_item_id）；
- 新值 SHALL 与现有值（视觉 / 听觉 / 嗅觉 / ...）并列，不替换任何已有值；
- `SubjectiveView.get_observations_by_sense(SenseType.DIGITAL)`
  SHALL 返回当前 view 中所有数字感知条目。

#### Scenario: 数字感知独立过滤
- **WHEN** SubjectiveView 含 2 条物理 observation 与 1 条数字 observation
- **THEN** `get_observations_by_sense(DIGITAL)` SHALL 恰好返回 1 条，
  其 `source_id` SHALL 为对应 FeedItem.feed_item_id

### Requirement: digital_attention filter

`perception.filters.digital_attention.DigitalAttentionFilter` SHALL 作为
`filters.base.Filter` 的子类存在。由于 `Filter.apply` 接口是 per-observation
（不能注入新 observation），数字感知的职责按以下分工：

- **注入**：`PerceptionPipeline` 在 `render` 的 gather 阶段调用
  `_gather_digital_observations(context)`，从注入的 `AttentionService`
  读取 `digital_state.pending_notifications` 对应的 FeedItem，构造
  `Observation(sense=DIGITAL, source_id=feed_item_id, ...)`。
  - `confidence` 初值 SHALL 取自 `digital_state.notification_responsiveness`
    （该字段由 AgentRuntime 从 profile 复制得来，见 attention-channel spec）。
  - `is_notable` 初值 SHALL 为 `True`；`tags` 含 `"feed_source:<source>"`。
- **调整（filter）**：在 filter 链中应用时，DigitalAttentionFilter SHALL：
  1. **未启用**：若 `ObserverContext.digital_state is None`，直接透传 observation，
     不改动任何字段。
  2. **物理 notable 漏损**：若 `digital_state.attention_target == "phone_feed"`，
     对 `sense in {VISUAL, AUDITORY, OLFACTORY}` 且 `is_notable=True`
     的 observation，SHALL 以概率 `(1 - attention_leakage)` 把 `is_notable`
     降为 `False`；`attention_leakage` 默认 `0.3`（刷手机时仍注意到 30% 物理事件）。
  3. **DIGITAL observation missed tag**：若 observation.sense==DIGITAL 且
     `attention_target != "phone_feed"` 且 `observation.confidence < 0.5`
     （等价于底层 `notification_responsiveness < 0.5`）且 observation 尚未
     带 `missed` tag，filter SHALL 追加 `"missed"` 到 `tags`。
- **消费**：`PerceptionPipeline.render` 在返回前 SHALL 调用
  `AttentionService.mark_consumed(entity_id, feed_item_ids)`，使下一次
  render 不再重复注入同一 feed_item_id。
- filter MUST NOT 修改 Ledger；MUST NOT 直接修改 AttentionService 内部
  pending/consumed 状态（仅 pipeline.render 在统一位置调 mark_consumed）。

#### Scenario: 未注入数字状态时透传
- **WHEN** `ObserverContext.digital_state is None`，且 SubjectiveView 含 5
  条物理 notable observation
- **THEN** filter 作用后 SubjectiveView 的 notable observation 数量 SHALL
  仍为 5，数字 observation 数量 SHALL 为 0

#### Scenario: 刷手机时物理 notable 下降
- **WHEN** `digital_state.attention_target="phone_feed"`，原本有 10 条物理
  notable observation，`attention_leakage=0.3`
- **THEN** filter 作用后 notable observation 数量的期望值 SHALL 为 3（±1）

#### Scenario: 推送进入 SubjectiveView
- **WHEN** `pending_notifications=("f_001",)`，对应 FeedItem 存在
- **THEN** filter 作用后 SubjectiveView 的 observations SHALL 增加 1 条
  `sense=DIGITAL, source_id="f_001"` 的 Observation

### Requirement: digital_attention 作为正式滤镜类别

`perception.filters` SHALL 提供 `digital_attention` 滤镜作为新类别，
与现有 `physical` / `environmental` / `audio` / `olfactory` / `skill` 并列，
继承自 `filters.base` 的统一接口。此条对已有 "多模态滤镜" Requirement
的 "SHALL 提供至少以下类别" 集合做正式追加，不修改其他已列类别。

`PerceptionPipeline` 构造器 SHALL 暴露可选参数
`include_digital_filter: bool = False` 与
`attention_service: AttentionService | None = None`，共同决定数字通道是否启用。

- 默认 `include_digital_filter=False`：filter 不入链，保持 Phase 1 行为。
- 当 `include_digital_filter=True` 时，`attention_service` MUST 非 None
  （否则 DIGITAL observation 无来源）；构造器 SHALL 在此条件违反时抛
  `ValueError`，不允许"静默失效"状态。
- 启用时 DigitalAttentionFilter SHALL 被追加到 filter 链末尾，
  位于物理 / 环境 / 技能 filter 之后、叙事渲染之前。

#### Scenario: 数字滤镜按需启用
- **WHEN** 构造 `PerceptionPipeline(include_digital_filter=True,
  attention_service=service)`
- **THEN** 管线 SHALL 在 filter 链中包含 `DigitalAttentionFilter`；
  审计与实验代码 SHALL 显式传入该参数对

#### Scenario: 启用数字滤镜缺 attention_service 被拒
- **WHEN** 构造 `PerceptionPipeline(include_digital_filter=True)` 而不提供
  `attention_service`
- **THEN** 构造 SHALL 抛 `ValueError`，错误消息指向需提供 attention_service

#### Scenario: 不启用时性能不退化
- **WHEN** 构造默认 `PerceptionPipeline()` 对 100 个 agent 跑 72 tick
- **THEN** 相比本 change 之前的实现，wall time 回归 SHALL 在 ±5% 之内

---

<!-- Added by typed-personality (archived 2026-04-21) -->
<!-- MODIFY 了 "ObserverContext 携带主观要素"：skills / emotional_state
     从 dict[str, float] 变为 typed Skills / EmotionalState；
     get_skill / get_emotion 方法被移除。运行时以下列新 Requirement 为准。 -->

### Requirement: ObserverContext 使用 typed Skills / EmotionalState

`perception.models.ObserverContext` SHALL：

- 移除字段 `skills: dict[str, float]`
- 移除字段 `emotional_state: dict[str, float]`
- 新增字段 `skills: Skills = Field(default_factory=Skills)`
- 新增字段 `emotional_state: EmotionalState = Field(default_factory=EmotionalState)`

`Skills` / `EmotionalState` 从 `synthetic_socio_wind_tunnel.agent.personality`
导入。

- 便利 property `investigation_skill` / `perception_skill` / `guilt_level`
  / `anxiety_level` 保留，内部改为从 typed 字段读
  （`self.skills.investigation` / `self.emotional_state.guilt` 等）。
- 现有 `get_skill(name, default)` / `get_emotion(name, default)` 方法
  SHALL 移除（同属于 dict 反模式的接口）。所有调用点改为 typed 访问。

#### Scenario: 默认构造
- **WHEN** `ObserverContext(entity_id=..., position=..., location_id=...)`
- **THEN** `ctx.skills` SHALL 是默认 Skills（全 0.5）；`ctx.emotional_state`
  是默认 EmotionalState（全 0.0）

#### Scenario: 便利 property 从 typed 字段读
- **WHEN** 构造 `ObserverContext(..., skills=Skills(investigation=0.8))`
- **THEN** `ctx.investigation_skill` SHALL 返回 `0.8`

#### Scenario: 旧 dict 接口移除
- **WHEN** 调用 `ctx.get_skill("investigation")` 或 `ctx.skills["investigation"]`
- **THEN** SHALL 分别抛 AttributeError / TypeError（dict 方法在 Skills 模型上不可用）

### Requirement: perception.filters 读 typed 字段

`perception/filters/*` SHALL 通过 typed 字段访问 observer state：

- skill filter 从 `ctx.skills.investigation` / `.perception` 读
- 任何需要情绪值的过滤 / 解释代码从 `ctx.emotional_state.guilt` /
  `.anxiety` 等读
- MUST NOT 保留 `ctx.skills.get(...)` 或 `ctx.emotional_state.get(...)`
  这类 dict-style 调用

#### Scenario: skill filter 仍按阈值工作
- **WHEN** 构造 agent 的 `Skills(investigation=0.3)`，查一个
  `discovery_skill=0.6` 的隐藏 item
- **THEN** 行为与本 change 之前一致（不发现）；底层代码路径使用
  typed 访问
