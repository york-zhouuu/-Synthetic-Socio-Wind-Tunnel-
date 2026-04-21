# perception — 能力增量

## ADDED Requirements

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
