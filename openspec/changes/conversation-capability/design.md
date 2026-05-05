## Context

social-graph 已 ship：encounter 流转化为 pairwise tie，agent 之间能区分"陌生人 vs 弱关系 vs 强关系"。但这层只承载"我们认识"——不承载"我们交流过什么"。

thesis 的最后一环（信息流动→社区涌现）需要：
1. 每 agent 有一个"known information set"
2. encounter 时按概率把 information share 给对方
3. 全局 metric：每条 information 跳了多少跳、覆盖多少 agent

V1 的核心简化：**不做 LLM dialogue**。只用概率门决定 share / 不 share；信息内容是 opaque 字符串。这让我们：
- 14 day × 1000 agent × ~50 encs/pair-day 在毫秒级算完，**不烧 LLM 预算**
- 测的指标（`info_reaching_2plus_hops`）已经是 thesis-direct 信号，不依赖 dialogue 真实性
- V2 想加 LLM dialogue 时，conversation capability 提供的 origin / share / hop tracking 是天然的接入点

## Goals / Non-Goals

**Goals**

1. **信息有"源"**：每个 push delivery 转化为一条 Information，origin_agent 知道，hops=0
2. **encounter 时按概率传播**：tie strength × extraversion × salience × recency 联合决定 share 概率
3. **跳数追踪**：每个 (agent, info) pair 记录最短跳数（避免 A→B→A 反向重复加跳）
4. **可观测 metric**：`info_reaching_2plus_hops` 填进 RunMetrics，contest scorer 可消费
5. **零侵入旧 path**：conversation = None 时所有现有行为不变；publishable run 默认开

**Non-Goals**

- ❌ LLM 多轮对话（V2）
- ❌ 信息变形 / Chinese whispers
- ❌ Trust-weighted propagation（tie strength 替代）
- ❌ misinformation / rumor 区分
- ❌ 3+ agent 群聊
- ❌ topic modeling
- ❌ 信息疲劳 / 二次 share 抑制（除"已知则跳过"外）
- ❌ 持久化 / 跨 seed run 状态共享

## Decisions

### D1：概率公式 — 5 个独立 modifier 相乘

```python
P(share | encounter, info) = base × tie_mod × pers_mod × salience × recency_decay
```

具体值：
- `base = 0.15`（典型偶遇 15% 概率聊到具体话题；先验拍板）
- `tie_mod = 0.5 + 1.0 × tie.strength`（陌生人 0.5，强关系 1.5；rule of thumb）
- `pers_mod = (extra_a + extra_b) / 2`（外向程度均值，∈ [0, 1]）
- `salience` ∈ [0, 1]（信息自带；hyperlocal 0.8 / local 0.6 / commercial 0.5 / global 0.3）
- `recency_decay = exp(-days_since_origin / 3)`（3 天半衰期）

期望值：tie 中等 0.3 + 外向中等 0.5 + salience hyperlocal 0.8 + 当天 recency 1.0：
P = 0.15 × 0.8 × 0.5 × 0.8 × 1.0 = 0.048 ≈ **4.8% per encounter**

意味着：双方每天碰几次的话，几次后必有一次 share。比真实人类略高，但 V1 可调。

**Alternatives considered**：

- **A. 单一阈值（urgency-style）** —— 拒绝。同一信息给所有 pair 同概率，不分 tie。
- **B. 累加 score（不乘）** —— 拒绝。modifiers 之间是相乘关系（每个都是必要条件不是充分），加法语义错。
- **C. 选 D1（multiplicative）** —— ✓ 每个 modifier 都是独立 gating factor，乘积语义自然。

### D2：hops_at_learn — 单 agent 单 info 取最短

每个 (agent, info) pair 只记录**第一次**learned 时的 hops。原因：
- 同一信息可能从多条路径传到同一 agent；后到的不重要，只有第一次到达决定"传到了"
- 反向 share（A→B→A）不更新 hops（A 已 known）
- 这是 BFS 的最短路径语义

实现：`InformationLedger._known: dict[agent_id, dict[info_id, _Knowledge]]`，`learn` 仅当 info 不在 dict 中时插入。

### D3：信息源接入 — 走 MemoryService 而非 hook AttentionService

**做什么**：MemoryService.process_tick 在 ingest_notifications 之后，检查每条新 ingested 的 notification，调 conversation.record_origin。

**理由**：
- AttentionService 已经被多个 capability 监听；不再加 hook
- MemoryService 已经是 push delivery 的下游消费者；走它最符合 Demeter
- conversation.record_origin 接受 (info, agent_id, tick) 是纯领域操作，不需要懂 attention 内部
- conversation = None 时 MemoryService 跳过这步——零侵入

**Alternatives considered**：

- **A. AttentionService 内置 conversation 引用** —— 拒绝。attention 不应该知道"信息会被传"——它只管"信息已交付"。
- **B. 单独 ConversationOriginHook 订阅 orchestrator** —— 拒绝。多一个 hook 类型，违反"all in process_tick"原则。
- **C. 选 D3（MemoryService 入口）** —— ✓ 跟 social-graph 的注入点一致，单一处理流。

### D4：Salience 由 FeedItem 推导

每个 FeedItem 已有 `category` / `hyperlocal_radius` 字段。salience 推导规则：
```python
def _salience_from_feed(feed: FeedItem) -> float:
    if feed.hyperlocal_radius and feed.hyperlocal_radius < 1000:
        return 0.8                      # 本街 / 本社区级
    if feed.category in ("local_news", "task"):
        return 0.6                      # 本地相关
    if feed.category == "commercial_push":
        return 0.5                      # 商业推送
    if feed.category in ("global_news", "global_distraction"):
        return 0.3                      # 全球新闻 / mirror
    return 0.4                          # default
```

**理由**：让 mirror（global_distraction）的 salience 显著低于 hp，使得即便 mirror 触发同样多 encounters，**信息层的传播显著弱**——这才是 thesis-direct 的对照（不是单看 encounter 数）。

### D5：metric 集成走 metrics/factory + recorder

- `RunMetrics.info_propagation_hops`（已有 placeholder）由工厂在 conversation 注入时填充：
  ```python
  {
      "info_count_total": graph.info_count(),
      "max_hop_observed": graph.max_hops(),
      "info_reaching_2plus_hops": graph.count_reaching(min_hops=2),
      "avg_reach_per_info": graph.avg_reach(),
  }
  ```
- `DayMetricsSummary` 加 4 daily counter（origins / shares / 2plus_today / avg_hops_today），从 conversation 在 day rollup 时查询

**Alternatives considered**：

- **A. 用 RunMetrics.extensions 字典** —— 拒绝。`info_propagation_hops` 已经是 metrics spec 中**硬保留**的字段（typed），用 typed 比 dict 更稳。
- **B. 选 D5（filled-in typed field）** —— ✓ schema 友好。

### D6：reproducibility — 共享 seeded rng

ConversationService 接受 `seed: int | None = None`，内部持有 `random.Random(seed)`。同 seed 同输入 → 同 share decision 序列。这与 reproducibility lock 已有的 `seed_pool` 字段一致。

**注**：MemoryService 已有自己的 `_rng`，**不**复用——因为 conversation 决策在 memory 之后；如果共享 rng，memory 的 should_replan 决策会消耗 rng 状态干扰 conversation。各持有自己的 seeded rng（同 seed 但状态独立）。

## Risks / Trade-offs

[**风险 R1**] V1 概率公式是先验拍的，没有真实数据校准；4.8% per-encounter share 可能太高 / 太低
→ **Mitigation**：先跑 e2e 看数。如果 publishable run 显示"几乎所有 info 都 100% reach"——base 调到 0.05；如果"几乎没 info 跳过 1 hop"——base 调到 0.30。这是单 magic number，调参成本低。

[**风险 R2**] hp vs baseline 的 info_reaching_2plus_hops 差异不显著（因 baseline 也有 push 来源，只是 salience 低 + 触发率低）
→ **Mitigation**：baseline 几乎无 push（除自然 task 通知），所以 baseline.info_count_total 应该比 hp 低一个数量级。两者比较的不是"hp/baseline"，是"hp/global_distraction"——同样多 push origin 但 salience 低，看是否传播差距显著。

[**风险 R3**] 没有"信息疲劳"机制可能让 14 天后某条 hyperlocal news 被全村人知道，看起来像 viral 但其实不真实
→ **Mitigation**：recency_decay = exp(-days/3) 让 3 天后 share 概率降到 36%，6 天后降到 14%；14 天后 0.9% — 自然衰减不需要硬截断。

[**风险 R4**] V1 不持久化跨 seed 的 known sets，每 seed run 从空开始；如果 multi-day 跑出来一个 long-tail propagation chain，这个 chain 在每 seed 都得重启
→ **Mitigation**：单 seed run 内 14 天累积已经足够看 viral 形态。跨 seed 持久化属于过度工程。

[**风险 R5**] 没有 LLM dialogue 让"信息内容"变成空洞符号——reviewer 可能挑战"这是真的对话吗"
→ **Mitigation**：proposal Why 已写"V1 测的是 propagation 是否发生，不是 dialogue 真实性"。reviewer 挑战时，V2 接 LLM dialogue 是直线扩展，不需要重新设计。

## Migration Plan

无破坏性 API 变更。

1. **Step 1**：实现 conversation 模块（models / service）+ 单元测试
2. **Step 2**：MemoryService 接 conversation 参数 + process_tick 调 record_origin & process_tick；零注入时旧行为
3. **Step 3**：metrics 接入 conversation + 填 info_propagation_hops
4. **Step 4**：tools 装配（run_variant_suite / replan_trace / export_inspector_payload）
5. **Step 5**：跑 e2e（mini sim 50 agent × 3 day stub）→ 看 info_reaching_2plus_hops 数量级
6. **Step 6**：commit + archive；下个 publishable run 默认开

回滚：tools 不传 conversation，行为退回到 social-graph-only。

## Open Questions

1. **Q1**：base=0.15 是否太激进？（每 encounter 15% 基础聊天概率）
   - **倾向**：先用 0.15。看 e2e 数据；过高再降。

2. **Q2**：`recency_decay = exp(-days/3)` 的 3 天半衰期合理吗？
   - **倾向**：合理。市集 / 新店开张 3 天后确实没人聊；新闻类 7 天衰减更慢但本 V1 用同公式简化。

3. **Q3**：salience 的具体值映射 (hyperlocal=0.8 / global=0.3) 怎么校准？
   - **倾向**：先用本提案中的拍板值。real LLM publishable run 后看 hp / gd ratio 是否合理（thesis 预期 ratio ≥ 2x）。

4. **Q4**：是否限制单条 info 的 max_hops（比如 max=5）？避免某些 info 看起来传遍全村。
   - **倾向**：不限。recency_decay + 已知则跳过两层机制已经在自然抑制。

5. **Q5**：`info_reaching_2plus_hops` 应该是 contest scorer 的 primary_metric for hp variant 吗？
   - **倾向**：作为 secondary。primary 仍是 trajectory_deviation_m / encounter.total（保持与之前 publishable run 可比较），但 contest report 的 narrative 段落会突出 conversation metric。
