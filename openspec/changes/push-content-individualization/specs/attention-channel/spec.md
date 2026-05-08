## MODIFIED Requirements

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
