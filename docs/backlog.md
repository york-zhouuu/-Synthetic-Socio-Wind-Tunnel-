# Backlog — 已识别但暂不开发的需求

记录用户确认过"需要做、但暂时不进开发流程"的事项。每条带上下文 + 优先级
+ 触发条件（什么时候应该把它从 backlog 移出来变成 OpenSpec proposal）。

---

## 1. Push 内容个体化（GD / PF）

**记录时间**：2026-05-17

**背景**：HP (HyperlocalPush) 已经过 `push-content-individualization` capability
精细化——5 个 PushTemplate × 5 audience variant + PushPersonalizer 路径。但
另外两个干预 variant 没走个体化：

- **GD (GlobalDistraction)**：10 条 generic global news headlines，所有 target
  收到同一条 broadcast。14 天 × 5 推送/天 会有大量重复。
- **PF (PhoneFriction)**：现已扩到 19 条 nudge templates（带 Lane Cove 地标 +
  时段 + 风格变化），但仍是 broadcast——所有 agent 同一时刻收到同一条。

**理想方向**：让 GD / PF 也走 PushPersonalizer，用 setup_content_cache 里的
`identity_text` + `life_history` 个体化 push：
- 对 35 岁有娃的设计师，PF nudge 提"孩子在 Canopy Park 等你"
- 对 65 岁退休志愿者，PF nudge 提"Plaza 长椅有人在等下棋"
- GD 也可按职业 / 兴趣个体化（财经 vs 娱乐 vs 体育 ……）

**优先级**：低。当前 D2 (β=10 publishable) 用 broadcast 路径已能给出 H_info /
H_pull 方向证据；个体化是"如果方向对，下一步加深效果"的扩展。

**触发条件**：D2 跑完，contest.json 显示 H_pull / H_info 方向有效但 effect
size 偏弱时考虑——届时 push 内容个体化是首要 amplification lever。

**估工**：1.5-2 hr 代码 + 0.5 hr 测试。

**Owner**：未指定。

---

## 1.5. 用 Doubao Seed Lite 替换 Gemini 3.1 Flash Lite（generate_message 路由）

**记录时间**：2026-05-17

**背景**：D2 attempt-4 把 `generate_message` (~69% ops/day) 从 DeepSeek
sonnet 路由到 Gemini 3.1 Flash Lite 提速。Gemini 跑得动但 D1' Gemini
connection-pool 不稳定的教训还在心里，多备一个 fast/cheap provider 做
backup 永远是对的。

**新加 provider**：Volces / 火山引擎 Doubao
- Endpoint：`https://ark.cn-beijing.volces.com/api/v3/responses`
- 默认模型：`doubao-seed-2-0-lite-260428`（字节跳动 fast 模型）
- API key：`.env` 里的 `VOLCES_ARK_API_KEY`（2026-05-17 设置）
- API 风格：Volces Ark "responses" 接口，input 数组 `{role, content=[{type, text|image_url}]}`
  支持多模态——**与 OpenAI chat-completions 不同**，需要新的 tier-client adapter

**何时考虑**：
- Gemini 不稳定 / 撞 quota → 切到 Doubao
- 跑超大 run（β=30+）想分散到 3 个 provider 提高总并发
- 想试 multimodal feature（agent "看见"图片 push）

**实施工作量**：~半天
- 在 `tools/tier_llm_factory.py` 加 `_VolcesTierClient` 类（mirror
  `_GeminiTierClient` / `_DeepSeekTierClient` 结构）
- 处理 Ark 的 `input` 数组格式 vs OpenAI `messages` 格式
- 加 `VOLCES_MODELS` dict + provider="volces" 入 `build_tier_clients`
- 在 run_variant_suite 切 generate_message tier 到 "volces" key 测一遍

**优先级**：低。当前 Gemini Flash Lite 工作正常；只在出问题时启用。

**Owner**：未指定。

---

## 1.7 多 worker 内存优化 + 去除运行时重复计算

**记录时间**：2026-05-18

**背景**：D2 attempt 4 (2026-05-18) 跑 4 seed × 4 variant = 16 worker
publishable 时，48 GB 单机内存被 D2 完全吃满 → 41 GB swap + 26 GB
compressor，Activity Monitor 显示 "Memory Used 138 GB"，workers 因 swap
thrash 速度比预期慢 50%（22 hr → 30+ hr）。最终凌晨 03:00 kill 掉
seed44 + seed45 两 suite 释放内存，β=2 跑完。

**问题诊断**：
- 每 worker 进程独立加载所有数据，**完全没共享**：
  - Atlas (~100 MB) × 16 = 1.6 GB（同一份地图）
  - shared_memories (~30 MB) × 16 = 480 MB
  - archetype / conversation_topic / social_prior_rule (~10 MB) × 16 = 160 MB
  - setup_content_cache 加载（per-seed 不同，但每 worker 读盘 + 解析独立）
  - Python interpreter + libraries (~700 MB) × 16 = 11 GB
- 每 worker 独立累积 MemoryStore (~1.5 GB peak after 14 day) × 16 = 24 GB
  → MemoryEvent 全在 RAM，没有 paging-to-disk 机制
- 每 worker 重复跑 `sample_population` / `build_location_pools` /
  `compute_social_priors_for_population`（同 seed 同结果）

**优化方向**（按 ROI 排序）：

### A. 进程间共享只读数据（高 ROI, 中等工作量）
- Atlas 用 `mmap` 持久化 → 16 worker 共享同一份 100 MB 而不是 1.6 GB
- 同样适用于 shared_memories / archetype / setup_content_cache
- 估省：~2-3 GB
- 工作量：~1 day（atlas 重做成 mmap-backed format）

### B. MemoryStore 改为 SQLite/DuckDB-backed（高 ROI，较大工作量）
- 当前所有 MemoryEvent 在 RAM 里。14 day × 500 protag × ~10 event/tick ×
  288 tick = 14M events → 1-2 GB / worker
- 改 backing store：写入 SQLite per seed，retrieve 时按需 read
- 估省：~1-1.5 GB / worker × 16 = 16-24 GB
- 工作量：3-5 day（MemoryService 接口不变，存储后端换）
- 风险：retrieve 性能可能下降（但 SQLite 索引 + cache 通常 OK）

### C. fork-based worker spawning（中 ROI，需要重构 launcher）
- 当前用 subprocess 起 worker，无 page sharing
- 改 `multiprocessing.fork` → child workers 自动 share parent 的 atlas
  / library page (COW)
- 估省：~5-8 GB（library 共享）
- 工作量：~2 day（run_variant_suite 重构）
- 注意：macOS fork() 在 Apple Silicon 上有 Objective-C / GIL 限制

### D. snapshot 保留策略：K=2 → K=1（小 ROI，极简单）
- tick-level-resume 保留最近 2 个 snapshot
- 改 K=1 节省 ~50 MB / worker × 16 = 800 MB（小但免费）
- 工作量：30 min（改 `_SNAPSHOT_KEEP_K` 常量）

### E. 去除运行时重复计算（小 ROI，简单）
- 同 seed 的 `sample_population` 跨 worker 完全确定性 → 跨 suite 第一次跑完
  缓存结果到磁盘，后续 worker 读
- 同 atlas 的 `build_location_pools` 类似可缓存
- 估省：~30 sec setup time / worker（不是内存收益，是时间）
- 工作量：~1 day（加 cache + invalidation 逻辑）

**实施触发**：下次想跑 β ≥ 8 publishable 时优先做 A + B。当前 β=2-4 可接受。

**估工总额**：A+B+D 大约 5-7 day 落实，能在同一 48 GB 机器上把 worker
上限从 16 拉到 ~40，β=10 publishable 单机可行。

**Owner**：未指定。

---

## 1.8 baseline-prefix-share：避免重复跑 baseline phase

**记录时间**：2026-05-18

**背景**：D2 attempt 4 跑下来发现，同 seed 下 4 个 variant 的 **Day 0-3
（baseline phase）完全一样**——没 push，agent 行为只受 seed 决定，跟
variant identity 无关。当前架构让 4 个 worker 独立跑了 4 遍同样的 Day 0-3。

**浪费量化**：
- 每 seed：3 个 intervention variant × 4 baseline day = 12 worker-day 重复
- D2 attempt 4 (4 seed) = 48 worker-day 重复
- 按 ~1 hr/worker-day 折算 = **~48 hr 冗余 wall**
- 即总 wall ~22-30 hr 中有 25-30% 是重复

**优化方案**：tick-level-resume 已经有 snapshot 基础，加 baseline-prefix-share：

```
新执行流程（per seed）：
1. seed42 baseline 单独跑 day 0-3 → 写 day3_checkpoint.snapshot
2. seed42 baseline 继续 day 4-13（作为 control）
3. seed42 hp / gd / pf 各自从 day3_checkpoint 续，跑 day 4-13
```

收益估算：
- 总 worker-day: 4 × 14 = 56 → 14 + 3 × 10 = 44 = 省 21%
- D2 attempt 4 (4 seed × 4 variant) 总 wall: ~22-30 hr → ~17-23 hr
- 节省 ~5-7 hr

**实施关键点**：
- snapshot 必须包含全部 mutable state（已有，tick-level-resume capability）
- launcher 协调：baseline worker 先跑 day 0-3，写 checkpoint，其它 3 个
  variant worker 等 checkpoint 就绪后并行启动（fork-style）
- baseline 继续跑 day 4-13 的同时其它 3 个并行跑
- 写 checkpoint 的 worker 需要 SIGUSR2 类似机制告知 launcher 就绪

**实施成本**：~1-2 day
- launcher 协调逻辑改：~50 行
- baseline_snapshot_at_day=3 机制：~30 行
- 单测：~100 行（验证 snapshot 内容、checkpoint 等价性、resume 后行为等于
  原跑）
- 风险：snapshot round-trip 已被 tick-level-resume 测过，但 4 个 variant
  从同一 snapshot 同时启动是新场景

**触发条件**：下次跑 β ≥ 4 publishable 之前先做。比纯内存优化（1.7）
ROI 更高——直接 25% wall 减少，工作量更小。

**对实验有效性影响**：理论上零影响——baseline phase 4 个 variant 本来就
应该等价（只是同一段计算重复跑了 4 次）。snapshot round-trip 已验证
state 等价性。

**Owner**：未指定。

---

## 1.9 所有直接 LLM call 加 asyncio.wait_for 硬超时兜底

**记录时间**：2026-05-18

**背景**：D2 attempt 4 (2026-05-18) hit day-end deadlock 6 次——多个
worker 在同样的 day-end reflection 调用点 hang 死 40-80 min 没醒。已对
`_process_ops_hook` 里 `maybe_reflect` 加了 60s `asyncio.wait_for` 硬超时
（commit 2d262b6），但**还有多个相同模式的调用点没修**。

**问题模式**：项目里存在两套独立的 LLM 调用路径：

**模式 A（受保护）**：通过 OperationPool → 每个 handler 都被
`asyncio.wait_for(handler(...), timeout=120s)` 包裹。
- `do_something` ✅
- `generate_message` ✅
- `remember_conversation` ✅

**模式 B（不受保护）**：直接 await llm_client.generate(...) 或类似——
**没有 asyncio 层的硬超时**。只靠 httpx 的 read_timeout / pool_timeout
等，但实测 httpx timeout 在 SSL handshake / pool 等待 / 半开连接等
情况下会失效。

**已知模式 B 调用点**（需要补 timeout）：

1. ~~`tools/run_variant_suite.py:874` `_process_ops_hook` 的 `maybe_reflect`~~
   → 已修（commit 2d262b6）
2. `synthetic_socio_wind_tunnel/memory/reflection.py:reflect` 内部对
   `llm_client.generate(prompt)` 的直接 await
3. `synthetic_socio_wind_tunnel/memory/importance.py:score_importance`
   对 LLM 的直接 await
4. `synthetic_socio_wind_tunnel/agent/planner.py:replan` 的 LLM 调用
5. `synthetic_socio_wind_tunnel/data_loader/lanecove.py` 里
   `_generate_life_history_for_one` / `_generate_identity_text_for_one`
   的 await（cache MISS 路径才走，HIT 不走 → 当前 D2 没踩，但理论上有
   风险）
6. `tools/prewarm_setup_content.py` 通过的同样路径

**统一修法**：

```python
# 推荐模板
import asyncio
try:
    result = await asyncio.wait_for(
        llm_client.generate(prompt, ...),
        timeout=60.0,  # 或基于 tier 调整
    )
except asyncio.TimeoutError:
    logger.warning("LLM call timed out, using fallback")
    result = fallback_value
```

**或者重构方向**（更彻底）：

让所有 LLM 调用强制经过一个统一的 `bounded_llm_call(client, prompt,
timeout)` wrapper，无 timeout 不允许调。可以是装饰器或 mixin。

**优先级**：高。
- 这次 D2 已经踩 6 次了，单次 cost ~40 min wall
- 不修下次跑 publishable 同样要踩
- 工作量小（~30 行代码 × 5 调用点 = ~150 行 + 单测）

**估工**：半天到一天。

**Owner**：未指定。

---

## 2. ReAct-style LLM 决策架构（替换 hint pre-fill）

**记录时间**：2026-05-17

**背景**：D2 attempt-4 pre-launch audit 揭示 `recent_memory_hint` /
`nearby_hint` / `candidate_destinations_hint` 三个字段都是死代码。我们当场
fix 成"在 schedule do_something / generate_message 时 lazily refresh"。
这是**功能修复**，不是架构修复。

**架构层面的问题**：整个 "hint pre-fill" 模式本身就不"像人"——
- 真实人类做决定不靠"someone hand me a list of recent memories"
  → 是**联想触发**：看到 Plaza 才想起上次在 Plaza
- 真实人类的"附近的人"不靠 dict lookup
  → 是**视觉感知**：转头看到旁边坐着人
- 真实人类的"可去的地方"不靠 enumerate list
  → 是**目标导向**：想吃饭 → 想到餐厅，想散步 → 想到公园

**理想方向**：ReAct-style LLM tool calling
- LLM 在做决定时**有工具可调**：
  - `memory.retrieve(query)`：按需查记忆
  - `perception.scan_nearby()`：扫描周围
  - `location.search(goal_keyword)`：按目标搜地点
- LLM **自己决定**要不要查、查什么、查多深
- 像真实"心智过程"——查询是认知行为的一部分，不是 prefilled context

**优先级**：低。这是架构重构，不是 bug。当前 lazy-fill 路径质量已经够 D2。

**触发条件**：
1. 答辩之后；OR
2. 决定上更大规模研究（β=30+ run）且想提升 LLM 决策真实性时

**估工**：3-5 天。涉及：
- OperationPool handler 重写（do_something / generate_message 改成可循环
  调用工具）
- LLM provider 选 tool-calling 友好的（DeepSeek v4 / Claude / GPT-4 都支持）
- prompt 模板大改（function-calling schema）
- 单元测试 + 端到端验证
- 性能：每个 do_something 现在 1 个 LLM call，ReAct 模式可能 3-5 个，
  成本上升

**Owner**：未指定。

---
