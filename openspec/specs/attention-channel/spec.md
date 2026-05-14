# attention-channel — 数字注意力通道

## Purpose

把"手机 / 推送 / 算法偏向"从 Policy Hack 的分支机制提升为一级机制，让
thesis 的核心变量（数字注意力位移）有稳定的读写接口。Policy Hack /
conversation / metrics 等 Phase 2 能力都通过此通道注入或观察数字刺激；
不走物理 `audible_range` / `visible_range` 传播。

模块：`synthetic_socio_wind_tunnel/attention/`
引入自：`realign-to-social-thesis`（归档于 2026-04-20）
## Requirements
### Requirement: FeedItem 与 NotificationEvent 数据模型

系统 SHALL 在 `synthetic_socio_wind_tunnel/attention/models.py` 中定义：

- `FeedItem`：字段 `feed_item_id`、`content`、`source`
  （`"global_news" | "local_news" | "commercial_push" | "social_app" | "neighbourhood"`）、
  `hyperlocal_radius: float | None`（米；`None` 表示全局）、
  `category`（自由文本，如 `"event" / "alert" / "discovery"`）、
  `urgency: float`（0–1）、`created_at: datetime`、
  `origin_hack_id: str | None`（若由 Policy Hack 触发则非空）、
  `topic_id: str | None = None`（**新增**；同一逻辑信息的多个 personalized
  实例共享此 ID。conversation 层用它聚合成同一 Information；None 时降级到
  feed_item_id）、
  `target_audience_tags: tuple[str, ...] = ()`（**新增**；这条 push 设计时
  声明的目标受众类型，metadata，metric 层用它计 target_precision）。
- `NotificationEvent`：继承 `core.events.WorldEvent`，
  `event_type=EventType.NOTIFICATION_RECEIVED`，`properties` SHALL 包含
  `{"feed_item_id": ..., "recipient_entity_id": ...}`。
- `FeedItem` SHALL 为不可变（frozen）Pydantic 模型，可哈希。
- 新字段 `topic_id` / `target_audience_tags` 默认值保持向后兼容；旧 callers
  不需要修改。
- `NotificationEvent` 作为 `WorldEvent` 子类 SHALL 保持 dataclass 语义
  （与 `WorldEvent` 一致，不强制 frozen）；其状态仍然是"一经由
  `AttentionService` 构造即事实，后续代码不得修改"——由 Service 保证，
  不由类型系统保证。这是有意与其它 WorldEvent 子类型对齐。

#### Scenario: 构造本地推送（向后兼容）

- **WHEN** 构造 `FeedItem(source="local_news", hyperlocal_radius=300)` 不传
  topic_id / target_audience_tags
- **THEN** 字段 SHALL 完整且不可变；`hyperlocal_radius` 非负；
  `topic_id` SHALL == None；`target_audience_tags` SHALL == ()

#### Scenario: 构造个体化推送

- **WHEN** 构造 `FeedItem(..., topic_id="hp_market_42_0",
  target_audience_tags=("parents", "young_adult"))`
- **THEN** 两字段 SHALL 保留传入值，参与 hash / equality 判定

### Requirement: AttentionState 表达 agent 注意力分配

系统 SHALL 定义 `AttentionState(
  attention_target: Literal["physical_world", "phone_feed", "task", "conversation"],
  screen_time_hours_today: float,
  last_feed_opened_at: datetime | None,
  pending_notifications: tuple[str, ...],
  notification_responsiveness: float)`。

- AttentionState SHALL 挂在 `perception.models.ObserverContext.digital_state`
  作为可选字段（默认 `None`，保持向后兼容）。
- `AttentionState` 本身不可变；每 tick 更新由新实例替换。
- `notification_responsiveness` 字段由 `AgentRuntime.build_observer_context`
  从 `profile.digital.notification_responsiveness` 复制而来；感知管线只能
  访问 ObserverContext.digital_state，无法回看 profile，因此需要这个复制。
  该字段在 `[0.0, 1.0]` 范围内，默认 `0.5`。

#### Scenario: 默认物理注意力
- **WHEN** ObserverContext 构造时未指定 `digital_state`
- **THEN** perception filter 链 SHALL 跳过数字注意力处理，行为与本 change 之前一致

### Requirement: DigitalProfile 作为 AgentProfile 的子字段

系统 SHALL 定义 `DigitalProfile(
  daily_screen_hours: float = 0.0,
  feed_bias: Literal["global", "local", "mixed"] = "global",
  headphones_hours: float = 0.0,
  notification_responsiveness: float = 0.5,
  primary_apps: tuple[str, ...] = ())`。

- 所有字段 SHALL 为可观察事实（不含"媒体素养"、"信息茧房程度"等合成指标）。
- `AgentProfile` 新增字段 `digital: DigitalProfile = DigitalProfile()`
  （见 `agent` spec 的 Requirement）。
- DigitalProfile 默认值 SHALL 使老的 `AgentProfile(...)` 构造无需改动即可工作。

#### Scenario: 旧构造仍可用
- **WHEN** `AgentProfile(agent_id="a", name="Emma", age=30, occupation="x",
  household="single", home_location="h")` 构造
- **THEN** `profile.digital` SHALL 为默认 DigitalProfile 实例

#### Scenario: 数值字段非负
- **WHEN** `DigitalProfile(daily_screen_hours=-1)` 构造
- **THEN** Pydantic SHALL 抛校验错误

### Requirement: 推送注入服务

系统 SHALL 在 `synthetic_socio_wind_tunnel/attention/service.py` 中提供
`AttentionService`，至少包含：

- `inject_feed_item(item: FeedItem, recipients: Iterable[str]) ->
  list[NotificationEvent]`：为每个 recipient 生成一条
  NotificationEvent；事件 SHALL 被追加到 Ledger 的一个新容器（例如
  `Ledger.notifications: list[NotificationEvent]`）。
- `notifications_for(agent_id: str, *, since: datetime | None = None)
  -> list[NotificationEvent]`：按 agent 过滤与时间窗。
- `pending_for(agent_id: str) -> tuple[str, ...]`：返回仍未被 agent
  的下一次 perception 处理的 feed_item_id 列表；排除已调用
  `mark_consumed` 标记的项。
- `mark_consumed(agent_id: str, feed_item_ids: Iterable[str]) -> None`：
  由 `PerceptionPipeline.render` 在完成一次 render 后调用，把本次
  surface 的 feed_item 从 pending 中排除，防止下一次 render 再次注入。
- `reset_consumed(agent_id: str | None = None) -> None`：清空已消费集合
  （单 agent 或全部）；仅用于测试与实验重置，不在生产 tick 路径使用。

- AttentionService MUST NOT 直接修改 `AgentProfile` 或 `ObserverContext`；
  agent 下一次构造 ObserverContext 时 SHALL 通过 `pending_for(...)`
  自行拼装 `AttentionState`。
- AttentionService 的注入 SHALL **不通过** `audible_range` / `visible_range`
  的物理传播；digital 通道独立。

#### Scenario: 按目标注入
- **WHEN** 调用 `inject_feed_item(item, ["emma", "bob"])`
- **THEN** Ledger SHALL 出现两条 NotificationEvent，
  `notifications_for("emma")` SHALL 返回其中一条，
  `notifications_for("chen")` SHALL 为空

#### Scenario: 不触发物理事件传播
- **WHEN** AttentionService 注入一条 FeedItem
- **THEN** `create_movement_event` / `audible_range` 相关代码路径 SHALL 不
  被调用；该 FeedItem SHALL 不出现在非 recipient 的物理 SubjectiveView

#### Scenario: 已消费的推送不再出现在 pending
- **WHEN** 对某 agent 注入 `f_001` 后，先调用 `pending_for(agent_id)`
  读取到 `("f_001",)`，再调用 `mark_consumed(agent_id, ["f_001"])`
- **THEN** 下一次 `pending_for(agent_id)` SHALL 返回 `()`

#### Scenario: 消费范围是 per-agent
- **WHEN** 同一条 `f_001` 被投递给 `emma` 与 `bob`，只对 `emma` 调用
  `mark_consumed(..., ["f_001"])`
- **THEN** `pending_for("emma")` SHALL 不含 `f_001`，
  `pending_for("bob")` SHALL 仍含 `f_001`

### Requirement: 核心事件类型新增

`core.errors.EventType` SHALL 新增：
- `NOTIFICATION_RECEIVED`
- `FEED_VIEWED`（agent 主动刷 feed 时）
- `ATTENTION_TARGET_CHANGED`

这三者 SHALL 与现有 `SOUND_*` / `ENTITY_*` 并列，**不替换或修改**已有类型。
工厂函数 `create_notification_event(item_id, recipient_id)` SHALL 提供
与现有 `create_movement_event` 一致的签名风格。

#### Scenario: 事件类型向后兼容
- **WHEN** 已有代码遍历 `EventType` 枚举
- **THEN** 新加的三种 SHALL 可被枚举到，不与现有值冲突

### Requirement: 算法偏向的最小建模

系统 SHALL 在 `AttentionService.inject_feed_item` 的内部提供一个
**纯函数** `_should_deliver(item: FeedItem, profile: DigitalProfile) -> bool`，
实现最小的"算法偏向"语义：

- 当 `item.source == "local_news"` 且 `profile.feed_bias == "global"`
  时，`_should_deliver` SHALL 以可配置概率（默认 0.2）返回 `False`，
  模拟"算法不推本地"。
- 当 `item.source == "global_news"` 且 `profile.feed_bias == "local"`
  时，对称地以默认 0.2 返回 `False`。
- 其余情况 SHALL 返回 `True`。
- 该概率 SHALL 可通过 `AttentionService(feed_bias_suppression: float = 0.2)` 注入。

#### Scenario: 全球偏向者丢失本地推送
- **WHEN** 某 agent `feed_bias="global"`，连续 100 次注入 `local_news` 推送，
  `feed_bias_suppression=0.5`
- **THEN** 该 agent 实际收到的 NotificationEvent 数量 SHALL 显著少于 100，
  预期均值在 40–60 之间

### Requirement: 推送日志可导出

系统 SHALL 提供 `AttentionService.export_feed_log(since, until) ->
list[FeedDeliveryRecord]`，其中 `FeedDeliveryRecord` 字段：
`feed_item_id`、`recipient_id`、`delivered: bool`、`delivered_at`、
`origin_hack_id`、`suppressed_by_bias: bool`。

- 日志用于 Phase 2 `metrics` capability 计算"干预触达率"与"信息扩散跳数"
  的起点。
- 导出 SHALL 是只读操作；不修改 Ledger。

#### Scenario: 日志包含 suppression 记录
- **WHEN** 10 条 local_news 推送给 1 个 global-biased agent，`feed_bias_suppression=0.5`
- **THEN** `export_feed_log` 返回 10 条记录；其中 `suppressed_by_bias=True`
  的条数 SHALL 在预期范围内（期望值 5）

### Requirement: AttentionService SHALL expose phone_attention state API

`AttentionService` MUST provide three new methods to manage per-agent
phone attention state:

- `get_phone_attention(agent_id: str) -> float`: returns current value
  (or baseline if agent unseen)
- `set_phone_attention_baseline(agent_id: str, baseline: float) -> None`:
  registers an agent's resting-state attention share (typically called
  during simulation setup from `profile.digital.daily_screen_hours / 16`)
- `tick_decay_all() -> None`: applies geometric decay to every tracked agent

Internal state is a dict `_phone_attention: dict[str, float]` + a
companion `_phone_attention_baseline: dict[str, float]`.

#### Scenario: get_phone_attention returns baseline for unseen agent
- **WHEN** `service.set_phone_attention_baseline("a1", 0.2)`, then
  `service.get_phone_attention("a1")`
- **THEN** returns `0.2`

#### Scenario: tick_decay_all reduces all tracked values
- **WHEN** two agents at 0.8 and 1.0, both with baseline 0.1, then `tick_decay_all`
- **THEN** values become `max(0.1, 0.8 × 0.85)` ≈ 0.68 and `max(0.1, 1.0 × 0.85)` = 0.85

### Requirement: AttentionService.deliver_feed_item SHALL accumulate phone_attention

The `deliver_feed_item` method MUST update the recipient's phone_attention.
When a feed item is successfully delivered to an agent, it SHALL accumulate
that agent's `phone_attention` by the delta formula specified in the
`attention-induced-noticing-gate` capability.

Delta MUST be computed using `agent_profile` (passed by caller) for
`digital.notification_responsiveness` and `personality.openness`. When
profile is None, fallback is `responsiveness=0.5, openness=0.5`.

#### Scenario: delivered notification updates attention
- **WHEN** baseline=0.2, current=0.2, `deliver_feed_item(item, agent_id, profile)`
  with `item.urgency=0.6`, `responsiveness=0.7`, `openness=0.5`
- **THEN** attention after delivery > 0.2

#### Scenario: suppressed notification does NOT update attention
- **WHEN** delivery fails (suppressed_by_bias=True)
- **THEN** attention SHALL remain unchanged

### Requirement: compute_notification_delta SHALL apply cumulative-fatigue

The `compute_notification_delta` function SHALL apply exponential per-day
fatigue decay. The signature `compute_notification_delta(urgency,
responsiveness, openness, *, notifications_received_today: int = 0)`
MUST accept the daily count and decay with `FATIGUE_HALFLIFE_N = 8`:

```
delta_n = base_delta × exp(-ln(2) × notifications_received_today / 8)
```

This captures real-world desensitization: the 1st push of the day fires
full attention; the 8th fires half; the 16th fires a quarter.

#### Scenario: first notification full delta
- **WHEN** `compute_notification_delta(0.5, 0.5, 0.5, notifications_received_today=0)`
- **THEN** result SHALL equal `compute_notification_delta(0.5, 0.5, 0.5)`
  (no fatigue at n=0)

#### Scenario: 8th notification half delta
- **WHEN** comparing `compute_notification_delta(0.5, 0.5, 0.5, n=0)` vs
  `compute_notification_delta(0.5, 0.5, 0.5, n=8)`
- **THEN** the n=8 value SHALL be approximately half the n=0 value (±5%)

#### Scenario: 16th notification quarter delta
- **WHEN** comparing n=0 vs n=16
- **THEN** the n=16 value SHALL be approximately one-quarter the n=0 value

### Requirement: AttentionService SHALL track daily notification count per agent

`AttentionService` MUST maintain `_notifications_today: dict[agent_id, int]`
counting notifications delivered to each agent within the current sim day.

The counter MUST:
1. Increment in `_accumulate_phone_attention(agent_id, feed_item)` after the
   delta is added to phone_attention
2. Be readable internally for the fatigue calculation passed to
   `compute_notification_delta(...)`
3. Reset on day boundary via `reset_daily_counters()` (caller invokes at
   day-start hook)

Backward compat: existing callers that don't invoke `reset_daily_counters()`
SHALL see counters accumulate across day boundaries — equivalent to "no day
reset" behavior, slightly different from intended but no exception raised.

#### Scenario: counter increments per delivery
- **WHEN** `deliver_feed_item` succeeds for agent "a1" once
- **THEN** `service._notifications_today["a1"]` SHALL == 1

#### Scenario: reset clears counters
- **WHEN** `reset_daily_counters()` is called after 5 deliveries to "a1"
- **THEN** `service._notifications_today.get("a1", 0)` SHALL == 0

#### Scenario: fatigue applied via service
- **WHEN** the service delivers 10 notifications to agent "a1" in one day,
  with identical urgency/responsiveness/openness for each
- **THEN** the per-notification phone_attention delta SHALL decrease
  monotonically as the count rises

