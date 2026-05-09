## Context

详细的 audit + 1:1 映射在 `_reference/` audit 报告里完成。本 design 只承担"具体怎么落到代码"的决策。

ai-town 的 agent stack（TS/Convex）核心 7 件套：
1. `Agent` 决策树（tick 顺序：pending → conversation → do_something）
2. `Memory` 3-way ranking + reflection 阈值触发
3. `Conversation` 双方 state machine（invited → walking_over → participating）
4. `Operation` 池（async LLM 调度，agent.startOperation()）
5. `EmbeddingsCache`（hash dedupe）
6. `Importance` LLM 评分（0-9 一次评一次缓存）
7. `Game.tick()` 驱动 + `inputs` 队列（async 结果回写）

SSWT 已有的"地基"足够撑住 1-7 全部移植——但移植成本主要在**冲突解决**和**和谐共存**。

## Goals / Non-Goals

**Goals**

1. **行为完整性**：10 protagonist agent 在 14 天 sim 里能展现 ai-town 论文级行为（双向对话、反思、内心叙事、关系深度）
2. **与 SSWT 兼容**：CQRS 不破、reproducibility lock 不破、metric 管线不破、990 scripted 不动
3. **可观测**：inspector payload 暴露每个 protagonist 的 reflection log + dialogue log + op log，方便产品 demo 看
4. **scale 可控**：tier LLM routing 让 14d × 10 protag 全 stack 跑成本 ≤ $50/seed
5. **回归零**：所有现有 e2e test 不破；publishable suite 跑出来 trajectory_deviation_m / weak_tie / info_propagation_hops 等指标方向不变

**Non-Goals**

- ❌ 990 scripted agent 接 ai-town 栈
- ❌ 引入 ai-town 的 Convex / TS 任何代码
- ❌ 取代 atlas / ledger / NavigationService / AttentionService
- ❌ 取代 ConversationService propagation（dialogue 是新增）
- ❌ 取代 Planner.replan（dialogue / reflection 是补充）
- ❌ 实时 60Hz tick（保留 5min/tick）

## Decisions

### D1：World class 不实例化，状态散在 AgentRuntime + DialogueService

**做什么**：ai-town 的 `World` / `Game` 类不引入。Agent 状态全部加在 `AgentRuntime` 上：
- `pending_operation: PendingOp | None`
- `current_dialogue_id: str | None`
- `to_remember: str | None`（dialogue end → next tick 触发 remember op）
- `last_dialogue_ended_tick: int | None`（cooldown）

Conversation 状态全部加在新 `DialogueService` 上（per-dialogue dict）。

**理由**：CQRS 第一原则——ledger 是单一 mutable truth。引入 World 类会创造第二个状态主体，破坏架构。Per-entity Pydantic 已经能装下所有 ai-town 的 player/agent state。

**Alternatives considered**：

- **A. 引入 World 类做 ai-town 状态容器** —— 拒绝。两个 mutable state 主体会让 reproducibility / save-replay / 测试都更难
- **B. 选 D1（散到 AgentRuntime + DialogueService）** —— ✓

### D2：Async op pool — asyncio.gather 在 on_tick_end 之后跑

**做什么**：
- Orchestrator 增 `register_on_tick_end_async(coro_factory)`
- on_tick_end_sync 跑完后，把所有 pending async ops 用 `asyncio.gather(*ops)` 并发跑
- 每个 op 完成后写结果到 `tick_inputs` 队列（per-agent dict）
- 下一 tick 开头 agent.step() 先消费这个队列

**Op 类型 + tier routing**：

| Operation | LLM tier | 触发时机 | 平均耗时 |
|---|---|---|---|
| `do_something` | sonnet | agent 长时间无 plan 进展 | 2-3s |
| `generate_message` | sonnet | dialogue.participating + agent 该说话 | 2-3s |
| `remember_conversation` | haiku | dialogue end → to_remember 设置 | 1-2s |
| `reflect` | haiku（或 nano）| daily summary 之前 + importance 累积阈值 | 1-2s |
| `score_importance` | nano | MemoryEvent 入库时（仅 protagonist）| 0.5s |

**理由**：14d × 100 protag × 多 op 同步跑会让 wall time 爆炸。async + tier routing 是 ai-town 没明确强调但 AgentSociety 已证可行的 scale infra。

### D3：Dialogue state machine — 4 状态 + 单 tick 推进

**做什么**：
```
DialogueStatus = "invited" | "walking_over" | "participating" | "ended"

Lifecycle:
  Agent A do_something → invite Agent B (B nearby + tie strength > threshold or random)
  → Dialogue created with [A: walking_over, B: invited]
  → next tick: A receives input "B invited"
  → if B accept (rule: strength × extraversion + rng): A.walk + B.walk
  → enter walking_over (both)
  → when both at same location_id: → participating
  → message turn loop (max 8 messages or 30 simulated minutes)
  → end → archived → both agent.to_remember = dialogue_id
```

简化版 vs ai-town：
- ai-town 用连续坐标 + euclidean distance；SSWT 用 location_id + adjacency
- ai-town tick 16ms 让 walking_over 跨多 tick；SSWT 5min/tick 通常 walking_over → participating 单 tick 内完成（除非要走多 location segment）
- ai-town 用 typing indicator + message_cooldown；SSWT 不需要（5min/tick 不分 typing）

**理由**：simulated_time 节奏跟 ai-town 完全不同，硬移植无意义。**核心 invariant 保留**：双方共识进入 → 对话发生 → 总结进 memory。

### D4：Memory ranking 重平衡 — 引入 importance 维度

**旧公式（4-way）**：
```
score = 0.40 × structural + 0.15 × keyword + 0.35 × recency + 0.10 × embedding
```

**新公式（4-way 调权）**：
```
score = 0.30 × structural + 0.30 × importance + 0.30 × recency + 0.10 × embedding
```

去掉 keyword 维度（embedding 路径已覆盖；hardcoded keyword 太脆）；importance 启用（之前 default 0.5 让 importance 维度无效）。

**ai-town 用的 normalize-then-sum**（每维 0-1 归一化）：
```
score = norm(struct) + norm(importance) + norm(recency) + norm(embed)
```
我们走**预设权重加权和**而非 normalize-then-sum，因为权重明确反映 SSWT 的检索语义优先级（structural matching 跟 importance 同等重要）。

**理由**：现有公式 importance 是 0.5 hardcoded → importance 维度等于 noise。启用 importance LLM 评分后，必须给它实际权重。重平衡后，retrieval 的 top-k 应该明显更"重要"。

### D5：Reflection 触发 — 阈值 + 日末双触发

**做什么**：
- **阈值触发**：累积 importance 自上次 reflect 以来 > 50.0（importance 在 [0,1] 范围下，~50 条 importance=1 的事件）
- **日末触发**：on_day_end hook 强制对每个 protagonist reflect 一次（即使未达阈值）
- 触发后调 reflect op：
  - LLM 提示词："你刚刚经历了这些（recent 100 memories），写出 3 条对你来说重要的 insight"
  - parse 返回 → 每条 insight 入库为 MemoryEvent[kind="reflection"]，含 `related_memory_ids` 字段
  - reflection event 自带高 importance（默认 0.8）

**理由**：
- 阈值触发对应 ai-town 的高重要性聚类逻辑
- 日末触发保证每天都有 narrative 沉淀（即使 baseline / boring 一天，也至少一条 reflection）
- 双触发组合让 reflection 自然分布在 14 天里

### D6：保留 Planner.replan 与 ai-town decision tree 并存

**做什么**：
- `Planner.replan` 不动（push → 同步 LLM → 改 plan，已有的"立即响应"路径）
- `agent/operations/` 是**新增**的 async 路径（do_something / generate_message / remember / reflect）
- `AgentRuntime.step()` 决策树先检查 pending op → 再检查 dialogue → 再走 plan-based Intent

**Sync replan vs async ops**：
| | replan（同步）| operation（异步）|
|---|---|---|
| 触发 | should_replan 返回 True | 决策树某分支 |
| 效果 | 立即更新 plan | 下 tick 才生效 |
| LLM | sonnet | sonnet / haiku / nano |
| 用途 | push 紧急响应 | 长期、不紧急的决策 |

**理由**：sync replan 的"push 来了立刻反应"语义不能丢（thesis-direct）。async ops 是补充。

### D7：identity_text / plan_text 是 LLM-generated 简介，单独 frozen

**做什么**：
- `AgentProfile` 加 `identity_text: str | None` 和 `plan_text: str | None` 字段
- 这两个不是 ABS census 维度，是 LLM 一次性生成的"agent 自我描述"，作为 conversation prompt 的 system context
- 生成时机：population sample 后立即 batch LLM 调用（每 protag ~50 tokens × 100 protag = ~5000 tokens / sample，几美分）
- frozen 后不变

**理由**：
- ai-town 用 `AgentDescription.identity` 作为 conversation prompt 的"persona statement"。我们当前没有等价物——profile 是 19 维 typed 字段，LLM 不会从中读出"我是谁"
- LLM-generated 简介让 conversation 消息有"角色感"（"作为 30 岁单身的图书管理员，我..."）
- 990 scripted 不需要这两个字段

### D8：Conversation/dialogue 与 Conversation/propagation 并存

```
Protagonist agents (10) ──→ Dialogue（LLM 双方对话）→ Memory + share via tie
                                        ↓
Scripted agents (990) ←─── Information propagation（probabilistic）
```

两者互通（信息流动）：
- Dialogue 结束 → 总结成 Information，注入 ConversationService.record_origin(info, protagonist, tick)
- Information 后续按 propagation 公式向 scripted agents 扩散
- 反向：scripted 间扩散的 Information 可被 protagonist learn → 进入 protagonist 的 dialogue 上下文

**理由**：thesis 完整性——dialogue 是深而少（10 个 protag 间），propagation 是浅而广（1000 agent 全网）。两者结合是真实社会的样子。

## Risks / Trade-offs

[**风险 R1**] 9 周工时是大投入；中途如果发现规模不对、性能不够、或 ai-town 行为不符预期，沉没成本大
→ **Mitigation**：6 phase 分批 ship；每 phase end-to-end 可验证；最早可在 Phase B 末跑 mini sim 验证 reflection 是否真出来。Phase A+B 完成约 3 周，是天然的 go/no-go 节点。

[**风险 R2**] ai-town 5-50 agent 验证 → SSWT 100 protagonist（如果用 100 个全 stack）规模未证
→ **Mitigation**：Phase E 加 scale benchmark；如果发现 wall time 不够，protagonist 数从 100 降到 30/50；async + tier 路由是已知 lever。

[**风险 R3**] LLM 成本飙升：reflection / dialogue / message 都是 LLM；不慎可能 $200+/seed
→ **Mitigation**：Phase A 内置成本仪表（per-op token tally）；reflection / score_importance 强制走 nano（gemini flash）；dialogue 的 message 限 max_tokens=300。

[**风险 R4**] 现有 thesis 信号方向变化（hp.traj_dev 不再 < gd.traj_dev）—— prompt 引入新维度可能扰动
→ **Mitigation**：Phase F 强制 benchmark：同 seed 同 variant，老 SSWT vs 新 stack 必须 hp.traj_dev < gd.traj_dev 不变。如果方向变了，先 root cause（不是验收 fail，可能是发现了新现象）。

[**风险 R5**] Async op pool 引入 race / deadlock 风险（asyncio.gather + 共享状态）
→ **Mitigation**：Op handler **不直接 mutate** AgentRuntime；只产 result，主线程在下 tick 开头消费；保持 actor model 风格。

[**风险 R6**] dialogue 跟 propagation 并存可能产生一致性问题（同一 Information 既走 dialogue 又走 propagation 路径）
→ **Mitigation**：Information.source 标记区分（dialogue / scripted_encounter）；propagation 不重复 share 已 known 的 info；conversation 完整 e2e test 覆盖。

## Migration Plan

无破坏性 API 变更。6 phase 串行：

| Phase | 内容 | 时长 | 验证 |
|---|---|---|---|
| **A** | embeddings_cache + importance + async op pool 框架 | 1.5 周 | 单元测试通过；importance LLM 评分能跑 |
| **B** | reflection 模块 + ranking 重平衡 | 1.5 周 | mini sim 跑出 reflection；ranking 公式回归测试通过 |
| **C** | dialogue 子系统 | 2.5 周 | 单元测试 + 2 protag dialogue mini sim |
| **D** | AgentRuntime 决策树嵌入 | 2 周 | 5 个分支各 e2e 测试 |
| **E** | tier LLM 路由 + scale benchmark | 1 周 | 14d × 30 protag dev sim 跑通；wall time < 60min |
| **F** | full benchmark + 文档 + commit + archive | 0.5 周 | 老 SSWT vs 新 stack 同 seed 对比；thesis 方向不变 |

回滚：每 phase 是独立 commit；任意 phase 可回退到上一 phase。Phase A + B 是 additive（不改老路径）；Phase C 是 additive；Phase D 是 invasive（动 AgentRuntime.step）—— 可加 feature flag `use_aitown_decision_tree: bool = True`。

## Open Questions

1. **Q1**：identity_text / plan_text 用哪个 LLM 生成？
   - **倾向**：population sample 时 batch 调用 sonnet（一次性，结果固定）。每 protag ~50 tokens × 100 = 5000 tokens ≈ $0.10。

2. **Q2**：dialogue 触发频率怎么调？
   - 太高（>50 dialogue / protag / day）→ 跑得很慢且不真实
   - 太低（< 1 / day）→ thesis 信号弱
   - **倾向**：决策树里 dialogue 概率初始为 0.05/encounter（5% 触发率），按 e2e 反馈调

3. **Q3**：reflection 阈值 50.0（累积 importance）合理吗？
   - 如果 importance 评分中位数 0.5 → 100 events 累积；14 天 × 5 events/day = 70 events → 不一定够
   - **倾向**：先用 30.0，看 reflection 频率；如果 < 1/day/protag 就降；> 5/day/protag 就升

4. **Q4**：dialogue cooldown（同 pair 不能频繁聊）？
   - **倾向**：同 pair 24 simulated 小时内不重复（除非 push 触发）。避免两个高 strength tie 的 agent 一直聊。

5. **Q5**：identity_text / plan_text 在 multi-day run 之间会变吗？
   - **倾向**：不变（frozen）。如果 14 天后 agent 真的"成长"了想更新 identity，由 reflection 模块在第 7 天 mid-point 写一条 update_identity reflection（但不修改原 profile.identity_text）。
