# 21 — Current Agent Design（当前 agent 系统盘点）

> 写于 2026-05-09，盘点当前 SSWT 里"一个 agent 由什么构成、它怎么决策、
> 真实数据进哪些层"。**不是设计提案**，是事实陈述 — 帮自己（和未来的人）
> 看清楚现在的 agent 系统**已有什么 / 还缺什么**。
>
> 前置：[`00-thesis.md`](00-thesis.md) / [`19-system-snapshot.md`](19-system-snapshot.md)。

---

## 0. 一句话

> **一个 agent = 静态身份（你是谁） + 经验流（你经历过什么） + 决策机制
> （你下一刻做什么）**。1000 个 agent 共享前两层的所有 capability；只有
> 10 个 protagonist 走 LLM-driven 第三层。

---

## 1. 三层结构 — 一张图

```
┌─────────────────────────────────────────────────────────────────────┐
│                          一个 Agent                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ▛ 第 1 层：静态身份（你是谁）  ── frozen at population sample        │
│  ▍ AgentProfile                                                      │
│  ▍   ├─ 19 个 ABS Census 维度（age/occupation/household/...）        │
│  ▍   ├─ PersonalityTraits（8 维 Big-5+ 扩展）                        │
│  ▍   ├─ DigitalProfile（screen_hours / feed_bias / apps）            │
│  ▍   ├─ LifePattern（preferred_cafe / commute_minute / weekend）     │
│  ▍   └─ identity_text + plan_text  ← 仅 protagonist；LLM 生成        │
│                                                                      │
│  ▛ 第 2 层：经验流（你经历过什么）  ── grows tick-by-tick             │
│  ▍ MemoryStore                                                       │
│  ▍   └─ MemoryEvent[10 种 kind]                                      │
│  ▍       ├─ action / encounter / notification / task_received       │
│  ▍       │   （路径相遇 / 推送 / 自己动作 → 自动派生）                │
│  ▍       ├─ daily_summary（end-of-day LLM 概要）                     │
│  ▍       ├─ speech / observation（保留位）                           │
│  ▍       ├─ reflection ← protagonist only；importance 簇 → LLM       │
│  ▍       ├─ conversation ← protagonist only；rememberConversation 产 │
│  ▍       └─ shared_memory ← 集体注入；data_loader.lanecove           │
│  ▍ MemoryRetriever（legacy 4 维 / aitown normalize-then-sum）        │
│                                                                      │
│  ▛ 第 3 层：决策机制（你下一刻做什么）  ── per tick                   │
│  ▍ AgentRuntime.step(tick_ctx) → Intent                              │
│  ▍   ├─ scripted（990 个）：plan-driven，纯代码 / Stub LLM replan    │
│  ▍   └─ protagonist（10 个）：ai-town 6-step 决策树                  │
│  ▍       1. drain tick_inputs（async op 结果）                       │
│  ▍       2. pending_op gate                                          │
│  ▍       3. to_remember → schedule remember_conversation             │
│  ▍       4. dialogue lifecycle（invited→walking→participating→ended）│
│  ▍       5. plan-driven fallback                                     │
│  ▍       6. else → schedule do_something                             │
│  ▍ Planner（共用）：should_replan 6 维 personality + 概率门          │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. 第 1 层 — 静态身份（AgentProfile）

**文件**：`synthetic_socio_wind_tunnel/agent/profile.py`
**特性**：`frozen=True` Pydantic model；populate 时定一次，sim 期间不变。

### 2.1 来源（一个 agent 的"灵魂"由谁定）

```
                       (来自 ABS 2021 Census G09 / G62 / ...)
                                       │
                                       ▼
                          PopulationProfile.distribution
                                       │
              ┌────────────────────────┼────────────────────────┐
              │ rng (seed)             │                        │
              ▼                        ▼                        ▼
        采样个人维度              采样人格              采样 Digital
       (age/occupation/...)   (Big-5 + curiosity      (screen_hours/
                                routine_adherence)     feed_bias)
              │                        │                        │
              └────────────┬───────────┴────────────────────────┘
                           ▼
                     AgentProfile（19 + 8 + 5 + LifePattern 维）
                           │
                  ┌────────┴────────┐
                  │                 │
        is_protagonist=False  is_protagonist=True
        (990 scripted agents)  (10 protag)
                  │                 │
                  │                 ▼
                  │       LLM batch generate
                  │       ↓
                  │       identity_text + plan_text
                  │       (~3 句 persona prose + 1 句 today's goal)
                  │       由 sample_population(generate_identity=True) 触发
                  │
                  └─────────► identity_text=None / plan_text=None
```

### 2.2 19 维 ABS Census 校准（agent-calibration / agent-profile-enrich）

| Tier | 维度 | 用途 |
|---|---|---|
| 1（thesis core）| community_tenure_5yr / unpaid_child_care_hours / unpaid_domestic_hours / unpaid_disability_care / volunteer_status | rooted vs floating；为 H_meaning / H_structure rival hypothesis 切片 |
| 2（refinements）| english_proficiency / family_composition / dwelling_structure / vehicles_at_dwelling / year_of_arrival_bucket | migration / 设施使用差异 |
| 3（completeness）| indigenous_status / disability_status / education_level | 全画像；少数群体可见性 |

**当前状态**：5/6 calibration tier passed；行为校准（ABS Travel Survey + Popular Times）未做。

### 2.3 identity_text / plan_text — 唯一"非结构化"灵魂字段

**这是 ai-town port 引入的字段**。前 18 维都是结构化值（数字 / Literal）；
identity_text 是**自然语言 prose**，喂进 dialogue / do_something / remember
prompts 里作为 `About you: ...` 段落。

**当前生成方式**：populate 时 LLM 收到 19 维结构化值 + LifePattern，让它写
2-3 句 persona prose。**没有用 lane cove 真人数据**——LLM 凭自己写，所以
两次 sample 出来的 emma 可能 identity 完全不同（取决于 LLM 创意）。

> ⚠️ **填充缺口（用户 2026-05-09 的关注点）**：
> identity_text 当前是"LLM 即兴"，不是"基于 lane cove 真实居民画像采样"。
> 真正的"用社交媒体 / 当地新闻数据填充 soul"应该是：从 lane cove 公开
> 居民故事、council 报道、reddit 帖子里抽出 **persona archetype 模板**，
> sample_population 时按 archetype 分发给 protag，再让 LLM 在模板上变奏。
> 这是 **soul 维度填充缺口**，目前未做。

---

## 3. 第 2 层 — 经验流（Memory）

**文件**：`synthetic_socio_wind_tunnel/memory/{models,store,service,retrieval,reflection}.py`

### 3.1 10 种 MemoryKind（事件流）

| Kind | 谁产 | 用途 |
|---|---|---|
| `action` | 自动 — 来自 CommitRecord | 自己每 tick 做了什么 |
| `encounter` | 自动 — 来自 EncounterCandidate | 路径相遇了谁 |
| `notification` | 自动 — 来自 AttentionService | 收到推送 |
| `task_received` | 自动 — category=task 的 FeedItem | 收到任务 |
| `speech` | 保留位 | （目前未启用） |
| `daily_summary` | 半自动 — MemoryService.run_daily_summary 用 LLM 概括 | 跨日 carryover anchor |
| `observation` | 保留位 | （目前未启用） |
| **`reflection`** | **protagonist only** — 累积 importance ≥ 阈值 → LLM 抽象 | ai-town 论文核心机制 |
| **`conversation`** | **protagonist only** — handle_remember_conversation 产 | 完整对话总结 |
| **`shared_memory`** | 注入 — `data_loader.lanecove.inject_shared_memories_*` | Lane Cove 集体记忆（12 条 LC 大事件） |

### 3.2 检索两种模式

```
MemoryQuery + top_k
    │
    ├─ legacy mode（scripted agent / Phase 1.5 路径）
    │     weighted sum: struct (0.30) + importance (0.30)
    │                 + recency (0.30) + embed (0.10)
    │     recency: exp(-days/3)
    │
    └─ aitown mode（protagonist / Phase 2 ai-town port）
          1:1 ai-town: normalize-then-sum on (relevance, importance, recency)
          recency: 0.99^floor(hours_since_last_access)
          last_access 字段在 retrieve 时被 touch（未来 retrieve 用）
```

### 3.3 三个数据源进入 memory（"你经历过什么"）

```
来源 1：sim 内事件（每 tick 自动派生）
     ├─ TickResult.commits → action events
     ├─ TickResult.encounter_candidates → encounter events
     └─ AttentionService.notifications → notification / task_received events

来源 2：sim 内 LLM 反思（protagonist 专属）
     ├─ ReflectionService.reflect → reflection events
     ├─ handle_remember_conversation → conversation events
     └─ run_daily_summary → daily_summary events

来源 3：sim 启动前注入 ← 真实世界数据
     └─ data_loader.lanecove.inject_shared_memories_for_protagonists
        └─ data/lanecove/shared_memories.json (12 条 Lane Cove 大事件)
```

> ⚠️ **填充缺口**：
> - 来源 3 目前**只有 12 条 community-shared events**（封城 / Galuwa / Crows
>   Nest Metro 等 — 全 LC 居民都该知道的）。
> - **没有的**：每个 agent 自己独特的"过去经历"。比如 emma 应该有 "8 年前
>   搬来 Longueville Road"、"第一次在 Pottery Lane 做义工" 这种**第一人称
>   生命史**。这是 **memory 维度填充缺口**。

---

## 4. 第 3 层 — 决策机制（AgentRuntime.step）

**文件**：`synthetic_socio_wind_tunnel/agent/runtime.py`（846 行）

### 4.1 两条路径

```
                    AgentRuntime.step(tick_ctx)
                              │
              ┌───────────────┴───────────────┐
              │                               │
              │                               │
   profile.is_protagonist=True       profile.is_protagonist=False
   AND use_aitown_decision_tree=True  OR use_aitown_decision_tree=False
              │                               │
              ▼                               ▼
       _aitown_step                   _legacy_step
       （6-step decision tree）       （plan-driven 老路径）
       ── 10 protagonist ─            ── 990 scripted ─
```

**当前 default**：`use_aitown_decision_tree=False`。也就是**目前所有 agent
其实都走 _legacy_step**——ai-town port 是"装好但默认关掉"的状态，等接到
multi-day runner 才会真正激活。

### 4.2 _legacy_step — 1000 个 agent 默认走的路径

```python
if plan is None: WaitIntent("no_plan")
while plan.current() expired: plan.advance()
if plan.current().action == "move":
    if at_destination: WaitIntent("at_destination")
    else: MoveIntent(plan.current().destination)
else: WaitIntent(plan.current().activity)
```

**Plan 来源**：
- 启动时 LLM/Stub 生成（StubReplanLLM 或 真 LLM Haiku/Gemini）
- 中途 `should_replan` 概率门触发 replan（6 维 personality + context modifier
  + 疲劳衰减）
- LLM 失败 fallback 到 `LifePattern.preferred_*`（agent-realistic-routine 加的）

### 4.3 _aitown_step — 6 step 决策树（仅 protagonist 启用时）

ai-town `Agent.tick()` 1:1 港。详见
[`agent-stack-aitown-port`](../../openspec/changes/agent-stack-aitown-port/specs/agent/spec.md) spec。

```
1. drain tick_inputs (async op result)
   ├─ generate_message → 写消息进 dialogue
   ├─ remember_conversation → bridge_to_memory_and_propagation
   └─ do_something → 暂存 _pending_action
2. pending_operation 未 timeout → WaitIntent("awaiting_op")
3. to_remember → schedule remember_conversation op
4. dialogue lifecycle（per-agent member_status）
   ├─ invited → 0.8 概率 accept；否则 reject
   ├─ walking_over → MoveIntent(target_location)
   ├─ participating + 我的 turn + over_msg/over_dur → schedule generate_message phase=leave
   ├─ participating + 我的 turn → schedule generate_message phase=continue
   ├─ participating + 对方 turn → WaitIntent("listening")
   └─ ended → mark_to_remember + clear current_dialogue_id
5. legacy plan-driven path
6. plan WaitIntent in {no_plan, plan_exhausted, move_no_destination}
   AND operation_pool != None → schedule do_something
```

### 4.4 决策机制依赖的服务（注入到 AgentRuntime）

| 字段 | 类型 | 谁用 |
|---|---|---|
| `attention_service` | AttentionService | 感知 phone_feed → 进 build_observer_context |
| `social_graph` | SocialGraphService | familiar_with（决策树未来用 / 当前 nearby_agents） |
| `dialogue_service` | DialogueService | 决策树第 4 步 dialogue lifecycle |
| `operation_pool` | OperationPool | 决策树第 3/4/6 步 schedule LLM ops |
| `memory_service` | MemoryService | 决策树拿 recent_memories 给 prompt |
| `nearby_hint`、`candidate_destinations_hint`、`recent_memory_hint` | list | 由 orchestrator 在 step 前 set，传给 op args |

---

## 5. 关系层（社交图）

**文件**：`synthetic_socio_wind_tunnel/social_graph/service.py`

```
SocialGraphService（每 sim 一份）
    │
    ├─ record_encounter(a, b, tick) ← MemoryService.process_tick 同步累积
    │   └─ Tie.encounter_count += 1（同 tick 同 pair 幂等）
    │       strength = N / (N + K=10)
    │
    ├─ get_tie(a, b) → Tie | None
    └─ familiar_with(agent_id) → set[other_id]
        （strength > WEAK_TIE_THRESHOLD=0.1 才算 familiar）
```

**当前关系网启动状态**：**全部从 0 开始**。1000 个 agent 在 day 0 互相
都是 strangers；要靠 14 天累积 encounter 才会形成 weak tie。

> ⚠️ **填充缺口（用户 2026-05-09 的"关系"维度）**：
> - 没有 **关系先验**：emma 应该在 day 0 就和 X / Y / Z 是"几年邻居"或
>   "同事"，而不是从 0 累积。
> - 缺数据来源（候选）：ABS commute matrix → 同公司通勤者；country-of-birth
>   SA1 → 同语种 enclave；household → 室友/家人。
> - 文件位置候选：`data/lanecove/social_priors.json`（已在路线图但未做）。

---

## 6. 真实数据进入 agent 的位置（盘点）

> 这一节回答用户的核心问题："我做的填充进了哪儿？"

```
┌─────────────────────┬─────────────────────────────────────────────┐
│  数据 / 来源        │  进入 agent 的位置                           │
├─────────────────────┼─────────────────────────────────────────────┤
│ ABS Census 2021     │  ✅ AgentProfile.{19 维结构化字段}           │
│ Lane Cove SA2       │     LANE_COVE_PROFILE.{distribution}        │
│ 121011686           │     populate 时 rng 采样                    │
├─────────────────────┼─────────────────────────────────────────────┤
│ Lane Cove 大事件    │  ✅ MemoryStore.{kind="shared_memory"}       │
│ (council/news/      │     12 条；只 protagonist；                  │
│  reddit web search) │     run-start 注入                           │
├─────────────────────┼─────────────────────────────────────────────┤
│ Lane Cove 居民      │  ❌ 未做                                     │
│ archetype           │     identity_text 当前"LLM 即兴"，没有       │
│                     │     archetype 模板                           │
├─────────────────────┼─────────────────────────────────────────────┤
│ 个体生命史          │  ❌ 未做                                     │
│ ("我 8 年前搬来"等) │     没有第一人称 backstory 注入接口          │
├─────────────────────┼─────────────────────────────────────────────┤
│ 关系网先验          │  ❌ 未做                                     │
│ (commute / ethnicity│     SocialGraphService 启动时空白            │
│  enclave / family)  │                                              │
├─────────────────────┼─────────────────────────────────────────────┤
│ 本地话题种子        │  ❌ 未做                                     │
│ (school zone /      │     do_something prompt 没有"本地话题"提示   │
│  parking / cafe)    │                                              │
└─────────────────────┴─────────────────────────────────────────────┘
```

---

## 7. 用户原意的三件套对照

> 用户 2026-05-09 原话：用 lane cove + ABS 数据填充 agent 的 **soul / memory / 关系**。
> 这三件套对照当前系统：

| 用户提的 | 当前实际做的 | 真正完整需要 |
|---|---|---|
| **soul** | ABS 19 维 ✅；identity_text LLM 即兴 ⚠️ | 加一层 lane cove archetype 模板（"通勤金融白领" / "退休本地人" / "新移民"），让 identity_text 在 archetype 上变奏，而不是从 0 写 |
| **memory** | shared_memories 12 条 ✅；个体生命史 ❌ | 加 individual life-history 注入：emma 自己的"8年居民经历"那种第一人称 backstory（5-10 条 personal MemoryEvents per protag） |
| **关系** | encounter-累积式 ✅（从 0）；先验 ❌ | 加 social_priors.json：ABS commute / ethnicity / family → SocialGraphService.preload_ties() 启动时注入 |

---

## 8. ai-town port 的位置（避免混淆）

ai-town port 不是"agent 的另一种选择"——它是**给现有 agent 加深度的一层**：

```
ai-town port 加了什么：
├─ 第 1 层：identity_text + plan_text 字段（改 AgentProfile）
├─ 第 2 层：reflection / conversation MemoryKind + ImportanceScorer
│           + EmbeddingsCache + retrieval aitown mode
├─ 第 3 层：6-step decision tree + OperationPool + 3 handlers
└─ 横切：DialogueService（4-state machine）+ Information(category="dialogue")

ai-town port 没改的：
├─ 990 scripted agent 行为完全不变
├─ Population sampling 流程不变（identity_text 是可选追加字段）
├─ thesis primary metrics（traj_dev / weak_tie / info_propagation）不变
└─ multi-day suite 默认还是 scripted-only（use_aitown_decision_tree=False）
```

ai-town port **完整接到 multi-day runner 上跑**还差：
- task 19.2: tier_llm_factory 接到 run_variant_suite
- task 22.2: inspector smoke 看 reflection_log / dialogue_log
- task 24.x: ablation benchmark（aitown ON vs OFF）

---

## 9. 三个最常见的混淆

### Q1: "我有 protagonist 这个概念吗"
**有**。`AgentProfile.is_protagonist: bool`。当前 1000 agent 里 10 个 = True。
他们：
- 用 Sonnet 档（base_model="claude-sonnet-...")
- 有 identity_text + plan_text
- shared_memories 注入只针对他们
- ai-town port 的 LLM dialogue / reflection / decision tree 只对他们启用
（前提：use_aitown_decision_tree=True）

### Q2: "现在的 dialogue 是真有 LLM 在聊天吗"
**取决于哪个 dialogue**：
- **Information propagation**（V1，2026-05-05 ship）：**没**有 LLM 聊天 —
  encounter 时按概率把信息从 a 传给 b，binary share，文本不变。
- **DialogueService + handle_generate_message**（ai-town port，2026-05-09
  ship）：**有** LLM 聊天，4-state machine（invited→walking→participating
  →ended），但**只在 use_aitown_decision_tree=True 时启用**。
- **当前 multi-day suite**：use_aitown=False default → 跑的是 V1
  propagation，没 LLM dialogue。

### Q3: "shared_memories 怎么进 prompt 的"
路径：
```
data/lanecove/shared_memories.json
   ↓ load_shared_memories()
   ↓ inject_shared_memories_for_protagonists()
MemoryService.record() × 12 (per protag)
   ↓ MemoryStore.append() — kind="shared_memory"
   ↓ MemoryRetriever.retrieve(top_k=N) — by importance
   ↓ AgentRuntime.recent_memory_hint = [ev.content for ev in top]
   ↓ _schedule_generate_message_op(...)
PendingOp.args["relevant_memories"] = recent_memory_hint
   ↓ handle_generate_message
LLM prompt: "Relevant memories you have:\n- ...\n- ..."
   ↓ LLM 输出
emma's actual dialogue line
```

**前提**：use_aitown_decision_tree=True 才会执行整条路径。**默认关闭**。

---

## 10. 还在路上的（不是"要做"清单，是"已经被识别但未做"清单）

| 项目 | 处在哪一层 | 工作量估计 |
|---|---|---|
| ai-town port 接 multi-day runner（task 19.2 / 22.2 / 24） | 第 3 层 | 1-2 天 |
| individual life-history 注入（per-protag backstory） | 第 2 层 | 2 天 + web research |
| Lane Cove archetype 模板（identity_text 不再 LLM 即兴） | 第 1 层 | 1 天 + web research |
| social_priors.json + SocialGraphService.preload_ties | 关系层 | 2 天 + ABS data parse |
| conversation_topics.json（do_something 本地话题种子） | 第 3 层 | 0.5 天 + web research |
| Behavioral calibration（Popular Times / ABS Travel Survey） | 跨层 | 1 周 |
| Stereotype audit + Face validity（publishable 解锁） | 跨层 | 各 1 周 |

---

## 11. 与其它 canonical 文档的关系

| 文档 | 它管什么 | 和本文关系 |
|---|---|---|
| [`00-thesis.md`](00-thesis.md) | thesis + 主边界 + Chain-Position | 本文回答"agent 装置怎么承载 thesis" |
| [`13-research-design.md`](13-research-design.md) | 14-day protocol / β 严谨度 / 五幕报告 | 本文是"实验装置的 agent 端" |
| [`19-system-snapshot.md`](19-system-snapshot.md) | 全 capability + 决策点表 | 本文是 19 文档"agent" 行的展开 |
| [`20-realism-roadmap.md`](20-realism-roadmap.md) | 5 stage 拟真路线图 | 本文不在 roadmap 上，是 stage 6 ai-town port 的 reference |

---

## Postscript

如果发现这个文档和代码不一致，**以代码为准**，并提 issue / change 修文档。
本文是 2026-05-09 的快照，会随 ai-town port 接入 multi-day runner / 个体
backstory 注入接口落地等更新而漂移。
