## ADDED Requirements

### Requirement: MemoryEvent.kind 加 "reflection" 类型

MemoryEvent.kind Literal SHALL 加入 `"reflection"` 选项：

```
MemoryKind = Literal["action", "encounter", "notification", "observation",
                     "speech", "daily_summary", "task_received", "reflection"]
```

reflection events 由 reflect op 生成；含 `related_memory_ids: tuple[str, ...]`
（在 tags 字段中以 `mref:<event_id>` 形式编码，或扩展 MemoryEvent 加专门字段）。

#### Scenario: reflection event 入库

- **WHEN** reflect op 生成 3 条 insight；调 memory.record(agent_id, event) 写入
- **THEN** memory.by_kind("reflection") SHALL 含 3 条；retrieval 可按 kind 查到

### Requirement: ImportanceScorer 子模块

`synthetic_socio_wind_tunnel/memory/importance.py` SHALL 定义 `ImportanceScorer` 类：

```
async score(event: MemoryEvent, *, llm_client) -> float
async score_batch(events: list[MemoryEvent], *, llm_client, batch_size=5) -> list[float]
```

- 调 LLM：prompt = "On scale 0-9, rate poignancy of: {event.content}"；返回 int → 归一化 [0,1]
- 失败 fallback：返回 event.importance（默认 0.5）；warning log
- 仅 protagonist agent 的 events 走此打分；scripted 仍用默认 0.5
- 用 nano tier LLM（gemini flash 或等价）控制成本

#### Scenario: score 返回 [0, 1] 范围

- **WHEN** llm_client.generate 返回 "7"；调 score(event, ...)
- **THEN** 返回值 SHALL == 0.7（7/10）；event.importance 保留旧值（caller 决定写不写）

#### Scenario: 失败 fallback

- **WHEN** llm_client 抛异常
- **THEN** 返回 event.importance（不抛）；warning log

### Requirement: ReflectionService 子模块

`synthetic_socio_wind_tunnel/memory/reflection.py` SHALL 定义 `ReflectionService` 类：

```
should_reflect(agent_id, recent_events, last_reflection_tick) -> bool
async reflect(agent_id, recent_events, *, llm_client, current_tick, day_index) -> list[MemoryEvent]
```

- `should_reflect` 触发条件：
  - 累积 importance（自上次 reflection 起）≥ `IMPORTANCE_THRESHOLD = 30.0`，**或**
  - day_index 跨日（即每天日末强制至少触发 1 次）
- `reflect` 调 LLM：
  - prompt 含最近 100 条 events（`related_memory_ids` 候选池）
  - 要求返回 3 条 insight + 每条对应的 source_event_ids
  - parse JSON → 3 条 MemoryEvent[kind="reflection"]，importance 默认 0.8，related_memory_ids 填充
- 失败 fallback：返回空 list；不阻塞主流程

#### Scenario: 阈值未到不触发

- **WHEN** 累积 importance = 20.0 且 day_index 不变
- **THEN** should_reflect SHALL 返回 False

#### Scenario: 阈值到触发

- **WHEN** 累积 importance ≥ 30.0
- **THEN** should_reflect SHALL 返回 True；reflect SHALL 返回 ~3 条 reflection events

#### Scenario: 日末强制触发

- **WHEN** day_index 从 0 → 1，无论 importance 累积多少
- **THEN** should_reflect SHALL 返回 True 一次（per agent per day）

#### Scenario: LLM 解析失败 fallback

- **WHEN** LLM 返回非法 JSON
- **THEN** reflect 返回空 list；warning log；不阻塞

### Requirement: EmbeddingsCache 子模块

`synthetic_socio_wind_tunnel/memory/embeddings_cache.py` SHALL 定义
`EmbeddingsCache` 类：

```
async fetch(text: str, *, embedding_provider) -> tuple[float, ...]
async fetch_batch(texts: list[str], *, embedding_provider) -> list[tuple[float, ...]]
hit_rate() -> float
clear() -> None
size() -> int
```

- 内部存储：`dict[sha256(text), tuple[float, ...]]`
- fetch 流程：sha256(text) → cache lookup → 命中返回 / 未命中调 embedding_provider → 写缓存
- fetch_batch：先 lookup 全部，未命中 batch 一次 embedding call
- hit rate 用于 dev metric（cache 击中比）

#### Scenario: 命中

- **WHEN** fetch("foo") 第一次（cache 空）；fetch("foo") 第二次
- **THEN** 第一次 SHALL 调 embedding_provider 一次；第二次 SHALL 不调，直接返回缓存

#### Scenario: hit_rate 反映命中比

- **WHEN** fetch 5 次（3 个独特 text，重复 2 次）
- **THEN** hit_rate() SHALL == 2/5 = 0.4

## MODIFIED Requirements

### Requirement: MemoryRetriever 4-way 打分

`MemoryRetriever` SHALL 提供 `retrieve(store: MemoryStore, query: MemoryQuery,
top_k: int = 10) -> list[MemoryEvent]`：

打分公式（**ai-town port 版本，重平衡**）：
```
score = 0.30 × structural + 0.30 × importance + 0.30 × recency + 0.10 × embedding
```

各维度：
- **structural**：(actor_id 命中 + location_id 命中 + kind 命中 + tags 交集非空) / 查询字段总数；范围 [0, 1]
- **importance**：直接读 event.importance（[0, 1]）
- **recency**：`exp(-(query.reference_time - event.simulated_time).minutes / query.recency_half_life_minutes)`
- **embedding**：cosine_similarity(query.embedding_query, event.embedding)；event.embedding 为 None 时此项为 0

弃用 keyword 维度（embedding 路径已覆盖；keyword 字符串硬匹配过脆）。**注**：MemoryQuery.keyword
仍接收，但不参与权重；保留只为兼容 caller。

候选池：query 的 structural 字段全部命中的事件 ∪ recent(200)。

#### Scenario: importance 维度生效

- **WHEN** 两个 event 完全一致（kind / actor / location / tags / time）但 importance
  分别 0.2 和 0.9；query 不带 importance 过滤
- **THEN** retrieve top-1 SHALL 是 importance=0.9 那条

#### Scenario: keyword 不再影响打分

- **WHEN** query.keyword="urgent"；event.content="urgent message"；其它字段都不命中
- **THEN** 打分 SHALL 不因 keyword 命中而升高（structural 维度计 0）

#### Scenario: 同 seed reproducible

- **WHEN** 同 store 同 query 跑两次
- **THEN** 返回的 top_k 顺序 SHALL 完全一致

#### Scenario: top_k 排序按总分降序

- **WHEN** retrieve(store, query, top_k=5)
- **THEN** 返回的 5 条按 score 降序；同 score 时按 tick 降序（recent 优先）
