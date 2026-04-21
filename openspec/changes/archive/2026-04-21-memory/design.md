## Context

Phase 2 已交付 orchestrator（tick 循环 + Intent 抽象 + 子 tick 轨迹 + hook 系统）。
memory 是 orchestrator 之后第一块真正让 agent "活起来"的能力——让每个
agent 有"昨天发生的事"的记忆，让 Planner 能基于此重规划。

已对齐的关键决策（来自 user Q&A）：

- **Scope**：存储 + 检索 + replan 触发（不做 reflection）
- **存储层**：独立 MemoryStore（per-agent 内存 dict，不进 Ledger）
- **写入粒度**：tick 概览 + 显著事件（不是每条 SubjectiveView observation）
- **Retrieval**：4-way 混合（结构化 + 关键词 + recency + embedding）
- **Replan 触发**：agent 自决（规则式纯代码，不调 LLM）
- **Replan 执行**：新增 Planner.replan（1 LLM call/replan）

## Goals / Non-Goals

**Goals:**
- 让 agent 的"昨天发生的事"能被 Planner prompt 拼装 / 未来 metrics 消费。
- 建立 replan 闭环：事件发生 → 记入 memory → agent 规则判断 → Planner.replan → 新 plan 写回。
- 4-way 检索可同时工作，但 LLM 成本严格有界。

**Non-Goals:**
- Reflection（多条 memory → 合成叙述）
- 跨 session / 多天持久化
- 每条 memory 写入的 LLM 打标（成本禁区）
- 每 tick 每 agent 的 LLM should_replan 判断（同上）
- shared task 状态机（policy-hack 的职责）
- conversation 产出的 speech 事件消费细节（conversation change 自己定）

## Decisions

### D1: LLM 成本控制为第一公民

一条红线：**memory 的单 tick 代价 MUST 不含每 agent 的 LLM 调用**。

违反成本（1000 agent × 288 tick = 288K calls/day/type，单价 Haiku $0.003/call 也是 $864/day/type），任何 "per-tick LLM" 设计都被此约束否决。

可接受的 LLM 频率：
- `Planner.replan`：**事件触发**，期望 0-50 次/天（allowlist + should_replan 过滤后）
- `MemoryService.run_daily_summary`：**1 次 / agent / 天** = 1000 次
- `MemoryRetriever` 的查询：零 LLM
- `AgentRuntime.should_replan`：**零 LLM**（纯规则）

总预算：~1050 calls/day/sim，与 `cost.daily-upper-bound` 上限相容。

### D2: MemoryEvent 结构

```python
@dataclass(frozen=True)
class MemoryEvent:
    event_id: str                    # uuid / seq; stable for dedup
    agent_id: str                    # 哪个 agent 的 memory
    tick: int                        # orchestrator tick_index
    simulated_time: datetime         # 事件的世界时间戳
    kind: Literal[
        "action", "encounter", "notification",
        "observation", "speech", "daily_summary",
        "task_received",
    ]
    actor_id: str | None             # 对方（若有）：被相遇的 agent / 推送来源
    location_id: str | None
    content: str                     # 人类可读；LLM prompt 直接用
    tags: tuple[str, ...]            # 初写时可空；daily summary 回填
    importance: float                # 0-1；初写规则计算，daily summary 校准
    embedding: tuple[float, ...] | None  # 可选；lazy 生成或 daily summary 批量
```

frozen 以便跨 tick 比较 / 哈希 / dict-key；tuple 避免可变侧门。

### D3: MemoryStore 索引策略

per-agent 一个 MemoryStore 实例；内存 dict-based。

```
events: list[MemoryEvent]                              # append-only
by_actor: dict[str, list[int]]     # actor_id → event 索引
by_location: dict[str, list[int]]
by_tag: dict[str, list[int]]
by_kind: dict[str, list[int]]
```

写入 O(1)（append + 更新 4 个倒排索引）；查询 O(匹配数 + top_k log top_k)。

**不**做持久化（不进 Ledger、不写磁盘）；重启即清。memory 是"当日工作内存"，
跨日持久化由未来的多日 change 设计。

### D4: MemoryRetriever 打分公式

输入：`MemoryQuery(agent_id, actor_id?, location_id?, kind?, tags?,
keyword?, embedding_query?, recency_half_life_minutes=60)`。

候选集：取 4 路索引（by_actor / by_location / by_tag / by_kind）的**并集**，
若全部为空则回退到"最近 N 条"（N=200）作为候选池上限。

评分：每条候选 MemoryEvent 打 4 个子分（0-1），加权合。

```
score = w_struct * structural_match     # query 字段命中数 / 非空字段数
      + w_keyword * keyword_score        # substring 存在 = 1，否则 0
      + w_recency * recency_score        # exp(-Δt / half_life)
      + w_embed  * cosine(query_vec, event_vec) if both available else 0
```

默认权重：`w_struct=0.4, w_keyword=0.15, w_recency=0.35, w_embed=0.10`。

权重可在 `MemoryRetriever(weights=...)` 构造时覆盖，便于实验调优。

importance 作为独立的**预过滤**（`min_importance` 可选），不进打分公式——
避免"高重要性但无关"的事件总是浮到顶。

### D5: EmbeddingProvider 解耦

```python
class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> tuple[float, ...]: ...
```

本 change 提供：
- `NullEmbedding`：hash-based 伪向量（确定性，测试用）。维度固定 32。
- **不**内置 OpenAI / Anthropic embeddings。用户若需真 embedding，自己注入。

Embedding 的填入时机：
- 写入时若 provider 非 Null，立即 embed（per-event 一次；若 provider 是
  Anthropic/OpenAI 则产生 I/O，需由调用方自行控制批处理）。
- 写入时若 provider 是 Null，embedding 字段置 None；MemoryRetriever 的
  embed 子分自动退化为 0。

### D6: process_tick 的算法

MemoryService.process_tick 是 on_tick_end 的核心入口：

```python
def process_tick(self, tick_result: TickResult,
                  agents: Mapping[str, AgentRuntime],
                  planner: Planner | None) -> None:
    # 1. 从 TickResult 派生 per-agent MemoryEvent
    for commit in tick_result.commits:
        self._record_action(agent_id=commit.agent_id, commit=commit,
                             tick=tick_result.tick_index,
                             sim_time=tick_result.simulated_time)
    for enc in tick_result.encounter_candidates:
        # 对 (a, b) 两侧都写一条 encounter（彼此视角）
        self._record_encounter(enc, tick_result)

    # 2. 从 AttentionService 抽取本 tick 的新 notifications（digital 通道）
    if self._attention_service is not None:
        for agent_id in agents:
            new_notifs = self._recent_notifications(agent_id,
                                                     since=tick_result.simulated_time)
            for notif in new_notifs:
                self._record_notification(agent_id, notif, tick_result)

    # 3. replan 检查（纯规则，无 LLM）
    if planner is None:
        return
    for agent_id, agent in agents.items():
        recent = self.retrieve_recent(agent_id, last_ticks=1)
        for candidate in recent:
            if agent.should_replan(recent, candidate):
                interrupt_ctx = self._build_interrupt_ctx(candidate, recent)
                new_plan = asyncio.run(planner.replan(
                    agent.profile, agent.plan, interrupt_ctx))
                agent.set_plan(new_plan)
                break  # 一 tick 内至多一次 replan/agent
```

关键：`break` 保证一 tick 内一个 agent 最多 replan 一次，即使多条候选都
通过 should_replan——避免"一个 tick 连环替换 plan"。

### D7: should_replan 默认规则

**更新（typed-personality archive 后）**：改为读 typed
`profile.personality.routine_adherence` / `profile.personality.curiosity`
字段；MemoryEvent.urgency 也改为显式字段（见 D10 说明）。close_ties 归
social-graph change（memory 不管）。

`AgentRuntime.should_replan(memory_view: Sequence[MemoryEvent],
candidate: MemoryEvent) -> bool`：

```python
def should_replan(self, memory_view, candidate) -> bool:
    adherence = self.profile.personality.routine_adherence
    curiosity = self.profile.personality.curiosity

    if candidate.kind == "notification":
        # MemoryEvent.urgency 是显式字段（不再解析 tag）
        urgency = candidate.urgency
        # 高好奇 + 低坚持 + 高紧迫 → 替换计划
        threshold = 0.4 + 0.3 * adherence - 0.3 * curiosity
        return urgency > threshold

    if candidate.kind == "task_received":
        return curiosity > 0.3

    # encounter 规则留给 social-graph change（需要"谁是熟人"的关系数据）
    return False
```

上面是**默认实现**。子类或策略对象可覆盖；future change 可让
`should_replan_policy` 作为 profile 字段注入。

### D8: Planner.replan 的 prompt 约定

`Planner.replan(profile, current_plan, interrupt_ctx) -> DailyPlan` 异步。

- `interrupt_ctx: dict` 含 `trigger_event`（MemoryEvent）、
  `recent_memories`（list[MemoryEvent]，top_k=10）、`current_time`。
- Prompt 模板：告诉 LLM "当前 plan 已走到 step N；因为发生了 {event}，
  请基于 {memories} 产出后续步骤（第 N 步之后替换）"。
- 返回的 DailyPlan：`current_step_index` 保留为原值，`steps` 列表
  `steps[:N]` 不变、`steps[N:]` 替换为 LLM 新产。
- 解析失败：fallback 到 `plan.insert_interrupt(wait_step)` 不中断整个
  simulation。
- 异步是因为 Planner 的 LLMClient 本身是 async（复用 Phase 1 约定）。

### D9: DailySummary 的时机

单天 simulation 的"end of day"是 orchestrator 跑完 288 tick 后。
`MemoryService.run_daily_summary(agents, llm_client)` 手动调用（不通过
on_simulation_end hook 自动触发——避免 orchestrator 构造时强制要求 LLM）。

每个 agent 1 次 LLM 调用：
- 输入：当日所有 MemoryEvent 的 content + kind + actor。
- 输出：
  - `summary_text`：人类可读的当日概要
  - `event_tags`：dict[event_id, list[str]]，回填每条 event 的 tags
  - `event_importance`：dict[event_id, float]，回填 importance

LLM 失败时 fallback：summary_text="(unavailable)"，tags/importance 不变。

### D10: `e3.shared-task-memory-seam` 能否翻绿

audit 条目检查"任务在 tick 之间持久化"。本 change 增加
`kind="task_received"` 的 MemoryEvent：当 agent 通过 attention-channel
收到 task（FeedItem.category=="task" 或 notification 带 task payload）
时自动记入。

- 写入即持久——跨 tick 可查。
- 但"task 状态机"（完成/放弃/更新）**不在 memory 做**。因此 audit 条目
  若严格要求 task 状态持久化，仍是 SKIP / mitigation=policy-hack。

本 change 的目标：把 seam **大部分**翻绿（task 接收事件可持久化），留
"task 状态"给 policy-hack。在 audit 更新时调整 scenario 措辞。

## Risks / Trade-offs

**[R1] MemoryStore 不进 Ledger → snapshot 不一致**
→ Mitigation：确定性测试只验 Ledger（已有）。Memory 的确定性由
  `process_tick` 输入一致性保证（TickResult 确定 → record 确定 →
  MemoryStore 状态确定）。

**[R2] 4-way retrieval 权重调优是个黑箱**
→ Mitigation：权重暴露为构造参数；fitness-audit 可新增"retrieval 覆盖率"
  诊断条目（未来 change）。本 change 默认权重基于直觉，不做实证校准。

**[R3] should_replan 规则在复杂场景可能过/欠触发**
→ Mitigation：规则是**默认**实现，profile / agent 子类可覆盖。thesis 第
  一波实验用默认规则，观察 replan 分布是否合理，再迭代。

**[R4] Planner.replan 失败时 agent 保留旧 plan 可能行为不一致**
→ Mitigation：fallback 到原 plan 比崩溃更安全。可在 MemoryService 里记
  "replan_failures"，future metrics 消费。

**[R5] 1000 agent 每 tick 遍历 memory 做 replan 检查的 CPU 成本**
→ 估算：1000 agent × 288 tick × O(recent) ~ O(10) 事件 = 2.88M 比较/天。
  should_replan 纯 Python 规则，约 1μs/调用 → 总计 3 秒。可接受。

**[R6] Embedding 懒/批处理造成"新事件检索召回差"**
→ Mitigation：默认 NullEmbedding 下，embed 子分权重仅 10%，不影响检索主干；
  真实 embedding 走 per-event 立即 embed（用户承担 I/O）。

## Migration Plan

1. 建 `synthetic_socio_wind_tunnel/memory/` 目录与 6 个文件。
2. `agent/runtime.py` 加 `should_replan`；`agent/planner.py` 加 `replan`。
3. `__init__.py` re-export 新公共 API。
4. 写 memory 单元测试（store / retriever / service）。
5. 写 agent 层单元测试（should_replan 规则表）。
6. 写 Planner.replan 测试（MockLLM）。
7. 写 orchestrator + memory 集成测试：
   - 单天 smoke demo 有 replan 产生
   - 跨 tick memory 可查
8. 跑 `make fitness-audit`：确认 phase2-gaps.memory PASS。
9. 更新 e3 audit 的 scenario（task_received 事件翻绿时）。

### 回滚
- 删除 `memory/` + 撤 `__init__.py` re-export + 撤 agent/runtime/planner 新方法即可。
  Orchestrator / AttentionService / Phase 1.5 不受影响。

## Open Questions

- **Q1**：orchestrator 跑完后 MemoryService 生命周期？
  → 建议：MemoryService 由外部 script / experiment runner 持有（跟 orchestrator
  同级），不内置到 orchestrator。`attach_to(orchestrator)` 是注册 hook 的
  语法糖。

- **Q2**：DailySummary 的 prompt 是否复用 Planner 的？
  → 建议：独立 prompt template（放在 `memory/prompts.py`），避免与 Planner
  互相耦合。DailySummary 聚焦"发生了什么 / 重要性"；Planner 聚焦"明天做什么"。

- **Q3**：should_replan 被调用频率？
  → 每 tick 每 agent 每条候选 = 288 × 1000 × 10 = 约 3M 次。纯代码 OK。
  若 agent_id 数量扩大 10x 需要 profile 剪枝（subsample）。本 change 不做。

- **Q4**：是否要做"Memory size 上限 + LRU 驱逐"？
  → 不做。1000 agents × 300K events/day = 3e8 events 峰值，Python dict 占用
  ~30GB——**这是真实问题**。但 Phase 2 单天场景下 1000 agent 数量可减小到
  100 跑 Experiment 1，足以验证功能。memory 的 scale 优化留给后续 change。
