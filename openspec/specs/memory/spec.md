# memory — per-agent 事件流 + 检索 + replan 触发

## Purpose

让每个 agent 拥有"昨天发生的事"的记忆——Phase 2 实验赖此做社交判断、
再规划、叙事质量评估。

职责（三件事，刻意窄）：
- **存**：MemoryEvent + per-agent MemoryStore（in-memory, 不进 Ledger）
- **查**：MemoryRetriever 4-way 打分（结构化 / 关键词 / recency / embedding）
- **触发**：MemoryService.process_tick 订阅 orchestrator.on_tick_end，
  写入 tick 派生事件 + 对每 agent 调 should_replan → planner.replan

不做：reflection、跨 session 持久化、每事件 LLM 打标、shared-task 状态机。

模块：`synthetic_socio_wind_tunnel/memory/`
引入自：`memory`（归档于 2026-04-21）

## Requirements

### Requirement: MemoryEvent 数据模型

系统 SHALL 在 `synthetic_socio_wind_tunnel/memory/models.py` 中定义
`MemoryEvent` frozen dataclass，字段：

- `event_id: str`（uuid 或 monotonic seq，去重用）
- `agent_id: str`（归属 agent）
- `tick: int`
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

#### Scenario: 构造一条 encounter 事件
- **WHEN** 构造 `MemoryEvent(kind="encounter", agent_id="emma",
  actor_id="linda", location_id="cafe_a", ...)`
- **THEN** 字段完整；可作为 dict key；可参与集合去重

### Requirement: MemoryStore per-agent 索引

系统 SHALL 在 `memory/store.py` 提供 `MemoryStore`：

- 内部维护 `events: list[MemoryEvent]` 追加日志 + 4 路倒排索引
  （`by_actor / by_location / by_tag / by_kind`）。
- `append(event)` SHALL O(1) 写入并更新 4 路索引。
- 不持久化；不进 Ledger；构造时即清空。
- `recent(n)` / `by_actor(actor_id)` / `by_location(loc_id)` /
  `by_tag(tag)` / `by_kind(kind)` 为查询入口，返回 MemoryEvent tuple。

#### Scenario: 按 actor 查
- **WHEN** 向 Emma 的 MemoryStore append 3 条 actor="linda" 的 events
- **THEN** `store.by_actor("linda")` SHALL 返回全部 3 条，顺序为写入顺序

#### Scenario: 重启即清
- **WHEN** 新建 MemoryStore 实例
- **THEN** `store.events` SHALL 为空；不读任何持久化文件

### Requirement: MemoryRetriever 4-way 打分

系统 SHALL 在 `memory/retrieval.py` 提供 `MemoryRetriever`：
`retrieve(store, query, top_k) -> list[MemoryEvent]`。

`MemoryQuery` 字段：
`actor_id | None`、`location_id | None`、`kind | None`、
`tags: tuple[str, ...]`（任一匹配即命中）、`keyword: str | None`、
`embedding_query: tuple[float, ...] | None`、
`recency_half_life_minutes: float = 60.0`、
`min_importance: float = 0.0`、
`reference_time: datetime | None = None`。

- 候选池：4 路索引的并集；若 query 所有结构化字段均空则回退为
  `store.recent(200)`。
- 预过滤：`importance >= min_importance`。
- 打分为 4 子分加权和：
  - structural: 非空 query 字段中命中的比例
  - keyword: `1.0 if keyword.lower() in event.content.lower() else 0.0`
  - recency: `exp(-Δt_minutes / recency_half_life_minutes)`，
    `Δt` = `reference_time - event.simulated_time`
  - embedding: 两者都非 None 时，余弦相似度；否则 0
- 权重 SHALL 可通过 `MemoryRetriever(weights=...)` 覆盖；默认
  `{struct:0.4, keyword:0.15, recency:0.35, embed:0.10}`。
- 返回排序后的前 `top_k` 条；得分相等时按 tick 降序（新的靠前）。

#### Scenario: 按 actor + recency 检索
- **WHEN** 对一个含 100 条 events 的 store 查
  `MemoryQuery(actor_id="linda")`，当前时间 = 10:00，half_life=60min
- **THEN** 返回的 top 10 条 SHALL 都含 actor_id="linda"，且越新的分数越高

#### Scenario: Null embedding 下 embedding 子分为 0
- **WHEN** event.embedding is None 且 query.embedding_query is None
- **THEN** 该条 event 的 embedding 子分 SHALL 为 0.0；总分由其它 3 项决定

### Requirement: EmbeddingProvider 协议与 NullEmbedding

系统 SHALL 定义 `EmbeddingProvider` Protocol：
`embed(text: str) -> tuple[float, ...]`。

系统 SHALL 提供 `NullEmbedding` 实现：hash-based 伪向量，维度固定 32，
确定性（同 text → 同 embedding）。

- `NullEmbedding.embed("foo")` SHALL 返回 `tuple[float, ...]` 长度 32。
- MemoryService 构造时若未注入 embedding_provider，SHALL 使用
  `NullEmbedding`。

#### Scenario: 默认无 embedding 依赖
- **WHEN** 构造 `MemoryService(...)` 不传 `embedding_provider`
- **THEN** 服务 SHALL 用 NullEmbedding；不需要任何外部 model / I/O

#### Scenario: 同文本确定性
- **WHEN** `NullEmbedding().embed("hello")` 被调两次
- **THEN** 两次返回的 tuple SHALL 逐元素相等

### Requirement: MemoryService 主入口

系统 SHALL 在 `memory/service.py` 提供 `MemoryService`：

- 构造：`MemoryService(*, embedding_provider=None, retriever_weights=None,
  attention_service=None)`。
- `record(agent_id: str, event: MemoryEvent)`：写入 per-agent 的 MemoryStore；
  若 embedding_provider 非 Null 且 event.embedding 为 None，SHALL 生成
  embedding 并写入（通过构造新的 MemoryEvent 替换）。
- `retrieve(agent_id: str, query: MemoryQuery, top_k: int = 10)
  -> list[MemoryEvent]`：per-agent 检索。
- `recent(agent_id: str, last_ticks: int = 1) -> list[MemoryEvent]`：
  返回最近 `last_ticks` 个 tick 的事件。
- `all_for(agent_id: str) -> list[MemoryEvent]`：全量快照，metrics 消费。

MemoryService MUST NOT 修改 Ledger；不调用 LLM 除非 `run_daily_summary`
方法被显式调用（见另一 Requirement）。

#### Scenario: 写入与立即检索
- **WHEN** `service.record("emma", evt)`，然后
  `service.retrieve("emma", MemoryQuery(kind="encounter"), top_k=5)`
- **THEN** 若 evt.kind == "encounter"，返回列表 SHALL 含 evt

#### Scenario: agent 隔离
- **WHEN** 向 emma 写入一条 evt，然后查 linda
- **THEN** `service.all_for("linda")` SHALL 不含该 evt

### Requirement: Orchestrator 集成（process_tick）

MemoryService SHALL 提供 `process_tick(tick_result: TickResult,
agents: Mapping[str, AgentRuntime], planner: Planner | None)
-> list[tuple[str, MemoryEvent]]`：

- 从 `tick_result.commits` 派生 per-agent `action` MemoryEvent。
- 从 `tick_result.encounter_candidates` 派生 `encounter` MemoryEvent
  （两侧各写一条）。
- 若 `attention_service` 在 MemoryService 构造时注入，
  SHALL 从它查询本 tick 新交付的 NotificationEvent，派生 `notification`
  MemoryEvent；`task_received` kind 在 notification 的 feed_item 的
  category == "task" 时派生。
- 若 `planner` 非 None，对每个 agent 调用
  `runtime.should_replan(recent, candidate)`；返回 True 时调
  `planner.replan(profile, current_plan, interrupt_ctx)`，用结果替换
  plan。每 tick 每 agent SHALL 最多 replan 一次。

#### Scenario: tick 后 action 事件被记录
- **WHEN** orchestrator 完成一个 tick，其中 emma 有一次 MoveIntent
- **THEN** `memory.all_for("emma")` SHALL 含一条 kind=="action" 的 event

#### Scenario: encounter 双向记录
- **WHEN** TickResult 含 EncounterCandidate(a="emma", b="linda",
  shared_locations=("street_1",))
- **THEN** emma 与 linda 的 memory SHALL 各含一条 kind=="encounter"，
  彼此 actor_id 互指

#### Scenario: replan 一 tick 最多一次
- **WHEN** emma 本 tick 接到 3 条通知，全部触发 should_replan=True
- **THEN** `planner.replan` SHALL 被调用**恰好一次**；第一个 match 后
  break

### Requirement: DailySummary 批量 LLM 调用

MemoryService SHALL 提供 `async run_daily_summary(agents, llm_client)
-> dict[agent_id, DailySummary]`：

- 对每个 agent：构造 prompt（当日所有 MemoryEvent 的 content / kind /
  actor），调用 llm_client.generate 一次。
- 解析产出 `summary_text`、`event_tags: dict[event_id, tuple[str, ...]]`、
  `event_importance: dict[event_id, float]`。
- 同时写入一条 `kind="daily_summary"` 的 MemoryEvent 作为索引入口。
- LLM 失败时 SHALL 使用 fallback：summary_text="(unavailable)"；
  tags/importance 保持不变；不抛异常。

每个 agent 恰好 1 次 LLM 调用——1000 agent 的 simulation 对应 1000 次
调用 / day。

#### Scenario: 成本边界
- **WHEN** 100 个 agent 跑完单天后调 `run_daily_summary`
- **THEN** llm_client.generate SHALL 被调用**恰好 100 次**

#### Scenario: LLM 失败不抛
- **WHEN** llm_client.generate 对某 agent 抛异常
- **THEN** 该 agent 的 DailySummary.summary_text SHALL 为 "(unavailable)"；
  其它 agents 的 summary 不受影响

### Requirement: fitness-audit 的 phase2-gaps 探针自动翻绿

`synthetic_socio_wind_tunnel.memory` 模块 SHALL importable；因此
`phase2-gaps.memory` AuditResult SHALL 为 `pass`（经 `_module_exists` 探针）。

#### Scenario: 审计自动翻绿
- **WHEN** 运行 `make fitness-audit`
- **THEN** `phase2-gaps.memory` AuditResult.status SHALL 为 `pass`
