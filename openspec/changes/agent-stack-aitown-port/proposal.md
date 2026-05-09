## Why

我们 24 个 changes 已经把**世界层**（atlas / ledger / orchestrator / multi-day / metrics）和**社会装置**（social-graph / conversation propagation / attention-channel / policy-hack）做得很扎实，但 **agent 内涵层始终很浅**：

- 990/1000 agent 走 scripted_plan（无 LLM）；只有 10 个 protag 用 Planner
- 那 10 个 protag 也只有"一次 LLM 出日计划 + replan 时 LLM 修计划"——**没有反思 / 没有内心叙事 / 没有真正的双向对话**
- 我们的 conversation/ 是**信息扩散**（ABC 概率传给 D），不是**两 agent 之间真聊一段**
- Memory 是 event log + 4-way 检索，**没有反思层**（高重要性记忆抽象成 insight）
- Importance 是默认 0.5 hardcoded，没有**LLM 评分 0-9** 的真实语义权重

这导致一个产品角度的硬伤：**14 天 sim 跑完，看 demo 的人看不到 agent 的"内心生活"和"邻居关系深度"**——只有轨迹偏离 +172m、weak ties +N 这种客观数字。

ai-town（a16z infra，Stanford Park 论文血脉）正是定义"agent 像活的"范式的项目，它有的我们没有：

| 维度 | ai-town 有 | SSWT 有 |
|---|---|---|
| Reflection（高 importance 簇 → LLM 抽象成 insight）| ✅ | ❌ |
| Importance LLM 评分（0-9）| ✅ | ❌（默认 0.5） |
| 3-way memory ranking（relevance + importance + recency）| ✅ | 4-way 但 importance 维度未启用 |
| 双向对话 state machine（invited → walking_over → participating）| ✅ | ❌ |
| LLM-driven dialogue 消息生成（含 memory 检索 context）| ✅ | ❌ |
| 对话总结 → memory 管线 | ✅ | ❌ |
| Async LLM operation 池（agent 触发不阻塞 tick）| ✅ | ❌（sync replan）|
| Embeddings cache（hash dedupe）| ✅ | ❌ |

**完整 1:1 复刻 ai-town 的 agent 内涵层**——不是借鉴 pattern，是**移植到 Python**——同时保住 SSWT 的世界层、实验装置、metric 管线、reproducibility lock 等所有已 ship 的能力。

跑完之后，protagonist agent 在 Lane Cove 14 天里能：
- 收 push → 反思（"这条市集消息让我想到上周跟 Linda 的对话") → replan
- 在街角遇到熟邻居 → 走过去 → LLM 生成具体对话 → 散场后总结进 memory
- 14 天累计：不仅有 weak tie 数字，**每个 agent 有可读的内心叙事**

## What Changes

### 新增 capability：`agent-operations`

- `synthetic_socio_wind_tunnel/agent/operations/` 新模块
- `OperationKind`：`do_something` / `generate_message` / `remember_conversation` / `reflect`
- `OperationPool`：async 操作调度，每 agent 单 op 队列、超时机制、result 写回 input queue
- 与现有 sync `Planner.replan` 并存——sync 路径作 fallback

### 新增子模块：`memory/reflection`

- `synthetic_socio_wind_tunnel/memory/reflection.py`：高 importance 簇 → LLM 抽象 insight
- 触发条件：单 agent 累积 importance > 阈值（默认 50.0，非 ai-town 的 500，因为我们 importance 在 [0,1] 不是 [0,9]）
- Insight 作为 MemoryEvent[kind="reflection"] 入库，含 `related_memory_ids` 字段
- 默认 in protagonist 的 daily summary 之前触发；scripted agents 不触发（无生成式记忆源）

### 新增子模块：`memory/importance`

- `synthetic_socio_wind_tunnel/memory/importance.py`：LLM 评分 0-9 → 归一化到 [0, 1]
- 触发：MemoryEvent 写入时；可关闭（用 default 0.5 fallback）
- 仅给 protagonist 用（990 scripted 不评分，节约成本）

### 新增子模块：`memory/embeddings_cache`

- `synthetic_socio_wind_tunnel/memory/embeddings_cache.py`：sha256(text) → embedding 缓存
- 用 `EmbeddingProvider` 协议封装；首次 fetch → embedding API → 写缓存
- 命中率监控（dev tool）

### 修改：`memory/retrieval.py` ranking 重平衡

- 旧 4-way (struct 0.40 / keyword 0.15 / recency 0.35 / embed 0.10)
- 新 4-way (struct 0.30 / **importance 0.30** / recency 0.30 / embed 0.10)
- 弃用 keyword（embed 路径覆盖；keyword 留 fallback 但不参与权重）
- 新增 `top_k_with_explanations()`：返回 (score, breakdown) 用于 inspector

### 新增子模块：`conversation/dialogue`

- `synthetic_socio_wind_tunnel/conversation/dialogue.py`：双向对话子系统
  - `Dialogue` 数据模型（dialogue_id, participants, messages[], status, started_tick, ended_tick）
  - `DialogueStatus`: `invited` / `walking_over` / `participating` / `leaving` / `ended`
  - `DialogueService`：state machine 推进 + LLM 消息生成
- 与现有 `conversation/service.py`（信息扩散）并存——dialogue 是 protag 间真对话；propagation 是 990 scripted 间概率扩散

### 修改：`agent/runtime.py` 决策树嵌入

- `AgentRuntime.step()` 新增 ai-town 风格决策树（仅 protagonist，否则走老路径）：
  ```
  if pending_operation and not timed_out: → WaitIntent
  if to_remember (just ended dialogue): → emit remember op → WaitIntent
  if in dialogue and walking_over: → MoveIntent toward partner
  if in dialogue and participating: → emit message op → WaitIntent
  if no plan progress in N ticks: → emit do_something op → WaitIntent
  else: → 既有 plan-driven Intent
  ```
- `AgentProfile` 增 `identity_text: str | None` / `plan_text: str | None`（生成式描述，用于对话 prompt）
- `AgentRuntime` 增 `pending_operation: PendingOp | None` / `current_dialogue_id: str | None` / `to_remember: str | None`

### 修改：`MemoryService` 与 `Orchestrator` 集成

- Orchestrator 新增 `register_on_tick_end_async`：让 async ops 在 tick 结束后并发跑（asyncio.gather）
- MemoryService.process_tick 改为驱动 ops：
  - 入库 notification → 触发 should_reflect
  - 收到 dialogue 结束信号 → 触发 remember_conversation op
  - 日末（on_day_end hook）→ 触发 reflect op for each protagonist

### Non-goals（明确不做）

- ❌ 990 scripted agent 不接 ai-town 栈（成本爆炸 + 无意义）
- ❌ 不取代 atlas / ledger（ai-town 的 World/Player 不实例化为类）
- ❌ 不取代 NavigationService（ai-town 内嵌的 A* 不引入）
- ❌ 不取代 ConversationService propagation（dialogue 是新增不是替换）
- ❌ 不接管 push 投递路径（仍走 AttentionService）
- ❌ 不破坏 reproducibility lock（所有新 RNG 走 seeded random.Random）
- ❌ 不破坏 metric 管线（新 reflect / dialogue / op 计数加 RunMetrics 但不替换）

## Capabilities

### New Capabilities

- `agent-operations`：async LLM 操作池（do_something / generate_message / remember_conversation / reflect）。这是 ai-town 的核心异步范式。

### Modified Capabilities

- `agent`：`AgentProfile` 加 identity_text / plan_text；`AgentRuntime` 加 ai-town 决策树 + pending_operation / current_dialogue_id / to_remember 状态字段
- `memory`：新增 reflection / importance / embeddings_cache 三个子模块；retrieval ranking 重平衡（弃 keyword、加 importance）；新 MemoryEvent kind = `"reflection"`
- `conversation`：新增 dialogue 子系统（双向对话 state machine + LLM 消息生成 + 总结管线）；现有 propagation 不动
- `orchestrator`：新增 async tick hook（让 ops 在 tick 间隙并发跑）

### Untouched

- `atlas` / `ledger` / `engine` / `cartography` / `perception`（除 PerceptionPipeline 不变）
- `social-graph` / `attention-channel` / `policy-hack` / `multi-day-run` / `metrics` / `suite-wiring`

## Impact

**代码新增**（~3000 行）：
- `synthetic_socio_wind_tunnel/agent/operations/` （4 个 op handlers + Pool）
- `synthetic_socio_wind_tunnel/memory/reflection.py`
- `synthetic_socio_wind_tunnel/memory/importance.py`
- `synthetic_socio_wind_tunnel/memory/embeddings_cache.py`
- `synthetic_socio_wind_tunnel/conversation/dialogue.py` + `dialogue_state.py`
- `synthetic_socio_wind_tunnel/agent/decision_tree.py`（ai-town 决策树）

**代码修改**：
- `synthetic_socio_wind_tunnel/agent/profile.py`（加字段）
- `synthetic_socio_wind_tunnel/agent/runtime.py`（决策树嵌入）
- `synthetic_socio_wind_tunnel/agent/planner.py`（dialogue prompt + reflection prompt）
- `synthetic_socio_wind_tunnel/memory/service.py`（接 reflection / importance / embeddings_cache）
- `synthetic_socio_wind_tunnel/memory/retrieval.py`（ranking 重平衡）
- `synthetic_socio_wind_tunnel/memory/models.py`（MemoryKind 加 `"reflection"`）
- `synthetic_socio_wind_tunnel/orchestrator/service.py`（async hook）
- `tools/` 内 `run_variant_suite.py` / `replan_trace.py` / `export_inspector_payload.py`（注入 OpenAIEmbedding / 暴露 dialogue 数据 / inspector 加 reflection_log + dialogue_log）

**测试新增**（~2000 行）：
- `tests/test_agent_operations.py`（async op pool + timeout + result write-back）
- `tests/test_memory_reflection.py`（trigger / clustering / insight insert）
- `tests/test_memory_importance.py`（LLM scoring + cache）
- `tests/test_memory_embeddings_cache.py`（hash dedupe / hit rate）
- `tests/test_memory_retrieval_rebalanced.py`（new 4-way 公式）
- `tests/test_conversation_dialogue.py`（state machine / message gen / summary）
- `tests/test_agent_decision_tree.py`（5 个分支各覆盖一个）
- `tests/test_aitown_port_e2e.py`（10 protag × 3 day mini sim：可观察 dialogue 出现 + reflection 出现）

**Suite / 数据影响**：
- 跑下次 publishable suite 自动产出新 metric：`reflection_count`, `dialogue_count`, `dialogue_avg_length`, `op_timeout_count`
- 预期：protagonist agents 14 天 dialogue ~10-50 次（对应 weak ties 数级）；reflection ~5-15 次

**性能**：
- async op pool 让 LLM 调用并发跑，不阻塞 tick；预计 14d × 100 protag × ~30 LLM ops = 几千 calls / seed
- LLM 成本：~$30-50 / publishable seed（hp protagonist 全 stack）；Tier routing 后可降到 $15-25

**风险**：
- **冲突 1**：ai-town 的 World 单 doc 模型 vs SSWT per-entity Pydantic → 解决：不引入 World 类，状态散在 AgentRuntime / DialogueService
- **冲突 2**：ai-town 实时 16ms tick vs SSWT 5min tick → 解决：所有 timing 常数走 simulated_time，不走 wallclock
- **冲突 3**：scale ai-town 验证 ≤ 50 → SSWT 保留 990/10 split，只 protagonist 走完整栈
- **回归风险**：所有现有 thesis-direct metric（trajectory_deviation_m / encounter / weak_ties / info_propagation_hops / target_precision）必须不受影响，benchmark 严格对照

**工时**：~9 周，分 6 phase（详见 design.md + tasks.md）。
