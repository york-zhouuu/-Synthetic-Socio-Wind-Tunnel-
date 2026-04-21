## MODIFIED Requirements

### Requirement: MemoryEvent 数据模型

系统 SHALL 在 `synthetic_socio_wind_tunnel/memory/models.py` 中定义
`MemoryEvent` frozen dataclass，字段：

- `event_id: str`（uuid 或 monotonic seq，去重用）
- `agent_id: str`（归属 agent）
- `tick: int`
- `day_index: int = 0`（相对 multi-day run 起始日的偏移；单日场景默认 0）
- `simulated_time: datetime`
- `kind: Literal["action", "encounter", "notification", "observation",
  "speech", "daily_summary", "task_received"]`
- `content: str`（人类可读）
- `actor_id: str | None`（对方 agent / 推送源）
- `location_id: str | None`
- `urgency: float`（范围 [0, 1]，显式字段；不藏于 tags 内）
- `importance: float`（范围 [0, 1]）
- `participants: tuple[str, ...]`（显式参与者）
- `tags: tuple[str, ...]`（仅承载描述性标签，非数值）
- `embedding: tuple[float, ...] | None`

- MemoryEvent SHALL 为 frozen 且可哈希。
- `tags` 与 `embedding` 为 tuple 而非 list，保持不可变。
- `day_index` 默认 0 以向后兼容旧调用方；`MultiDayRunner` 在 process_tick
  时 SHALL 覆盖为当前天的 day_index。

#### Scenario: 构造一条 encounter 事件
- **WHEN** 构造 `MemoryEvent(kind="encounter", agent_id="emma",
  actor_id="linda", location_id="cafe_a", ...)`
- **THEN** 字段完整；可作为 dict key；可参与集合去重；day_index 默认 0

#### Scenario: 多日 run 写入 day_index 被保留
- **WHEN** 在 day 3 写入一条 encounter
- **THEN** 产出的 MemoryEvent.day_index SHALL = 3；后续按 day_index 查询
  SHALL 可定位该条


## ADDED Requirements

### Requirement: DailySummary 可按天检索

`MemoryService` SHALL 提供：
- `get_daily_summary(agent_id, day_index) -> DailySummary | None`：返回
  该 agent 在指定 day 的 DailySummary；缺失返回 None
- `get_recent_daily_summaries(agent_id, *, last_n_days: int = 3,
  ref_day_index: int | None = None) -> tuple[DailySummary, ...]`：返回
  从 ref_day_index-last_n_days+1 到 ref_day_index-1（含端）的历史摘要，
  按 day_index 升序；ref_day_index=None 时取 store 中最大 day_index 作参考

实现可依赖 `MemoryStore.by_kind("daily_summary")` + day_index 过滤；不引入
新存储。

#### Scenario: 取昨日摘要
- **WHEN** agent emma 在 day 0-4 各有 daily_summary 写入；调用
  `get_daily_summary("emma", day_index=3)`
- **THEN** 返回 day 3 的 DailySummary 对象

#### Scenario: 取最近 3 日摘要
- **WHEN** 调用 `get_recent_daily_summaries("emma", last_n_days=3,
  ref_day_index=5)`
- **THEN** 返回 (day 2, day 3, day 4) 三条 DailySummary；day 5 本身不含
  （因为是"昨日之前"语义）


### Requirement: CarryoverContext 聚合接口

`MemoryService` SHALL 提供 `get_carryover_context(agent_id, *,
current_day_index: int) -> CarryoverContext`，组装次日 planner 所需的
历史上下文：

- `yesterday_summary: DailySummary | None`（day_index = current-1 的摘要；
  current=0 时为 None）
- `recent_reflections: tuple[DailySummary, ...]`（last 3 days 摘要，不含
  yesterday）
- `pending_task_anchors: tuple[MemoryEvent, ...]`（kind="task_received" 且
  无对应 "action" 指示 completed 的 events；按 importance 降序，限 5 条）

`CarryoverContext` SHALL 为 frozen Pydantic 模型。

#### Scenario: Day 0 无历史
- **WHEN** `get_carryover_context("emma", current_day_index=0)`
- **THEN** 返回的 CarryoverContext.yesterday_summary SHALL 为 None；
  recent_reflections SHALL 为空 tuple

#### Scenario: Day 5 有完整历史
- **WHEN** Emma 有 day 0-4 完整 daily_summary，3 条未完成 task_received；
  调用 `get_carryover_context("emma", current_day_index=5)`
- **THEN** 返回的 yesterday_summary.day_index SHALL = 4；
  recent_reflections SHALL 包含 day 1, 2, 3 的 summaries（day 0 被 3-day
  窗口排除）；pending_task_anchors SHALL 长度 ≤ 5


### Requirement: Memory 自动写入 day_index

`MemoryService.process_tick` SHALL 从 `tick_result.day_index` 读取当天
day_index，并把该值填入该 tick 派生的所有 MemoryEvent（action / encounter /
notification / task_received）。单日路径下 tick_result.day_index 默认 0，
因此 MemoryEvent.day_index 亦为 0（向后兼容）。

#### Scenario: 多日 tick_result 的 day_index 传递
- **WHEN** tick_result.day_index = 7 且含 5 个 commits
- **THEN** memory.process_tick 派生的所有 MemoryEvent.day_index SHALL = 7
