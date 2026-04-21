## Why

`phase-2-roadmap` 把 memory 列为 7 块 Phase 2 能力之首。fitness-audit 里
两条锚点直接指向本 change：

- `phase2-gaps.memory` → **FAIL**（mitigation=memory）：
  `synthetic_socio_wind_tunnel.memory` 模块不存在。
- `e3.shared-task-memory-seam` → **SKIP**（mitigation=memory）：
  Phase 1 没有 per-agent 任务 / 互动历史存储，agent 无法基于"昨天 Linda
  拒绝过我"来决定今天的行为；shared task（共享猫线索）也无法跨 tick
  持久化。

没有 memory，orchestrator 跑完一天后每个 agent 除了"到了哪"什么都不记得。
整个 thesis 假设——"agent 基于社交历史做判断、被干预后改变行为"——
在数据层就没有依据。

同时本 change **把 replan 机制补齐**：orchestrator archive 时显式把
replan 作为 Non-goal 推到了 memory change。memory 负责"存+查+触发"，
Planner 负责"执行"。

## What Changes

### 1. 新增 `memory` capability（NEW）

`synthetic_socio_wind_tunnel/memory/` 模块，包含：

- **`MemoryEvent`**：frozen dataclass，含 `event_id`、`agent_id`、`tick`、
  `simulated_time`、`kind`（`action` / `observation` / `encounter` /
  `notification` / `speech`）、`actor_id`（对方 / 目标 agent）、
  `location_id`、`content`（自由文本）、`tags`（结构化标签元组）、
  `importance`（0-1，由写入方或 daily summary 填）、`embedding`（可选
  向量，初次写入时可为 None；懒生成或 daily summary 时批量生成）。

- **`MemoryStore`**：per-agent 的 in-memory 容器。不进 Ledger，不参与
  save/load；orchestrator 重启即清。内部维护四种索引：
  - `by_actor: dict[actor_id → list[event_id]]`
  - `by_location: dict[location_id → list[event_id]]`
  - `by_tag: dict[tag → list[event_id]]`
  - 按时间顺序的 `events: list[MemoryEvent]`（append-only）

- **`MemoryRetriever`**：组合 4 个信号打分：
  - 结构化匹配（query 指定 actor / location / tag / kind 时）
  - 关键词 substring（query.keyword 非空时）
  - 时新度（recency_half_life 默认 1 小时 simulated time）
  - 可选向量相似度（若 embedding 可用）
  - 最终分数 = weighted sum；`retrieve(agent_id, query, top_k)` 返回排序后的
    `list[MemoryEvent]`。

- **`EmbeddingProvider` 协议 + `NullEmbedding` stub**：
  真实 embedding 在构造 MemoryService 时注入（任何实现
  `embed(text) -> list[float]` 的对象）。测试与无 LLM 环境默认
  `NullEmbedding`（hash-based 伪 embedding，确定性但"语义"无意义），
  让其它三路检索继续工作。

- **`MemoryService`**：对外主入口。
  - `record(agent_id, event)`：写入并更新索引。
  - `retrieve(agent_id, query, top_k)`：MemoryRetriever 的门面。
  - `process_tick(tick_result, agents, planner)`：供 orchestrator
    on_tick_end 订阅。做三件事：① 从 TickResult + AttentionService
    抽取 per-agent 事件并 `record`；② 对每个 agent 调
    `runtime.should_replan(memory_view)`；③ 返回 True 时调用
    `planner.replan(profile, current_plan, interrupt_ctx)` → 替换 plan。
  - `run_daily_summary(agents, llm_client)`：遍历所有 agent 产
    `DailySummary`（1 LLM call/agent，同时填补当天 event 的 `tags` 与
    `importance`）；结果写到 memory（作为一条 kind="daily_summary"
    的特殊 event）。

### 2. 修订 `agent` capability（MODIFIED）

- **`AgentRuntime.should_replan(memory_view, candidate) -> bool`**
  新增方法。**纯代码规则**（不调 LLM，避免每 tick × 每 agent 的 LLM 负担）。
  默认实现：基于 personality trait `routine_adherence`（未定义则 0.5）
  + event kind：
  - `notification` 且 `urgency >= 0.5 * (1 - routine_adherence)`：返回 True
  - `encounter` 且对方在 suspicions / long-known friends：返回 True
  - 其余：False
  - 子类或注入策略可覆盖此默认。

- **`Planner.replan(profile, current_plan, interrupt_ctx) -> DailyPlan`**
  新增异步方法。1 次 LLM 调用，产出保留"已走过 step"的新 plan
  （从 `current_step_index` 开始的未来 step 被替换）。失败时返回原 plan
  并记日志（不抛，避免中断 simulation）。

### 3. 与 orchestrator 的集成

MemoryService 主要通过 **orchestrator 的 on_tick_end hook** 订阅。构造
MemoryService 时传入 orchestrator 自动注册：

```python
memory_service = MemoryService(agents=agents, planner=planner,
                                attention_service=attention_service,
                                llm_client=llm_client or NullLLMClient())
memory_service.attach_to(orchestrator)
```

本 change **不**修改 orchestrator capability 的任何已冻结 Requirement
（Phase 2 零破坏原则）。

### 4. Non-goals

- **不**做 reflection（跨多条 memory 的 LLM 合成叙述）。Phase 2 单天场景下
  价值有限；多天 change 再做。
- **不**跨 session 持久化。memory 重启即清；需要长期记忆的实验另开 change。
- **不**对每条 memory 写入调 LLM 打标。LLM 打标集中在 daily summary（约
  1 次 / agent / 天）而非每次 write。这是刻意的成本控制。
- **不**扩展 orchestrator 的 TickResult 结构。MemoryService 消费 TickResult
  现有字段 + AttentionService 查询；不需要 orchestrator 暴露 SubjectiveView。
- **不**修改 Ledger 的任何已冻结 Requirement。MemoryStore 是独立服务。
- **不**做"多 agent 共同对话"——那是 `conversation` change 的职责。
  memory 只消费 `speech` 事件（由未来 conversation change 产生）。
- **不**把"shared task 状态"作为头等公民。task 状态更接近 `policy-hack` 的
  职责；memory 只记"接到了某 task"这一事件；task 的具体状态机后续 change 建。
  （`e3.shared-task-memory-seam` 能否翻绿取决于是否把 task 接收视为
  一类 MemoryEvent——见 design）

## Capabilities

### New Capabilities
- `memory`: per-agent 事件流存储、4-way 检索、daily summary、replan 触发与
  协调

### Modified Capabilities
- `agent`: `AgentRuntime.should_replan(memory_view, candidate)` 纯代码方法；
  `Planner.replan(profile, current_plan, interrupt_ctx)` 异步 LLM 方法

## Impact

### 受影响代码
- `synthetic_socio_wind_tunnel/memory/`（新）—
  `models.py` / `store.py` / `retrieval.py` / `embedding.py` / `service.py` /
  `__init__.py`
- `synthetic_socio_wind_tunnel/agent/runtime.py` — 新增 `should_replan`
- `synthetic_socio_wind_tunnel/agent/planner.py` — 新增 `replan`
- `synthetic_socio_wind_tunnel/__init__.py` — re-export MemoryService / MemoryEvent / MemoryQuery
- `synthetic_socio_wind_tunnel/fitness/audits/phase2_gaps.py` — `memory` probe 由 FAIL 自动翻绿
- `synthetic_socio_wind_tunnel/fitness/audits/e3.py` — `shared-task-memory-seam` 的 skip → pass 判定可能需更新
- `tests/test_memory_*.py`（新）— store、retrieval、embedding 协议、service、
  should_replan、replan、orchestrator 集成

### 不受影响（保持兼容）
- Atlas / Ledger / Simulation / Navigation / Collapse / Perception /
  Cartography / MapService / AttentionChannel / FitnessAudit / Orchestrator
  的已冻结 Requirement
- 已归档 change 与 Phase 1 所有测试

### 依赖变化
- 无强制新依赖。`EmbeddingProvider` 可接 `openai` / `anthropic` / 本地模型，
  但默认 `NullEmbedding` 不需要。
- `anthropic` SDK 已在 `[full]` optional extra，Planner.replan 复用。

### 预期成果
- `phase2-gaps.memory` FAIL → PASS（自动探针）。
- `e3.shared-task-memory-seam` SKIP → PASS（task 接收作为 MemoryEvent 被
  持久化后，审计断言变绿；若未实现 task 事件类型则保持 SKIP，作为后续
  policy-hack change 的锚点）。
- Orchestrator 跑单天后，每个 agent 的 MemoryStore 含 300K-1M 量级
  events；可被 planner / 未来 metrics change 消费。
- 预期 LLM 成本：1 daily summary call/agent + 约 0-50 replans/day
  ≈ 1000 + 50 calls/day（Haiku 档），与 `cost.daily-upper-bound` 估算
  上限相容。
