## Context

当前 sim 的 encounter 数据流：

```
Orchestrator.run(tick) 
  → tick_result.encounter_candidates: tuple[EncounterCandidate, ...]
                                                ↓
MemoryService.process_tick
  → 写入 per-agent kind="encounter" MemoryEvent（双向各一条）
                                                ↓
[end of tick]                       ← encounter 信息只存在于 per-agent memory；
                                       全局 / pairwise 没有累积
```

现状的痛点：
- 14 天 sim 跑完后，"agent A 和 agent B 累积见过 N 次"这件事**只能从 A 的 memory 中扫描 actor_id == B 的 encounter 事件**统计——昂贵且 ad-hoc
- 没有"关系强度"的概念，只有"见过 / 没见过"的二态
- 没法做 thesis-relevant 的 metrics（weak ties count / new ties per day 等）

这个 change 在不破坏 memory 现有结构的前提下，新增一个**累积层**：每个 encounter 既继续作为 per-agent 的主观经历写入 memory（保留），又同时在 social-graph 层累积成一条 pairwise tie。

```
Orchestrator.run(tick)
  → tick_result.encounter_candidates
                                 ↓
       ┌─────────────────────────┴─────────────────────────┐
       ↓                                                    ↓
MemoryService.process_tick                         SocialGraphService
  → per-agent encounter MemoryEvent                  → record_encounter(a, b, tick)
                                                       Tie.encounter_count++
                                                       Tie.strength = N/(N+10)
```

## Goals / Non-Goals

**Goals**

1. **累积**：把瞬时 encounter 转成 persistent pairwise tie，O(1) 查询
2. **可解释强度**：单一公式 `strength = N / (N + K)`，K=10 给"10 次 = weak tie 阈值 0.5"的明确语义
3. **薄封装**：MemoryService / AgentRuntime 拿到的是 ergonomic API（`familiar_with(other_id)`），不需要懂 graph 内部结构
4. **thesis 指标**：暴露 weak / strong tie counts 作为 metric，让 contest report 可以用 `tie_count_weak` 作为 hp variant 的 primary_metric——首次让 thesis 中段的"社会层产出"在 contest 中有可比 number
5. **可注入**：service 是 optional 依赖（MemoryService 接 None 时降级到旧行为），不破坏未接 social-graph 的旧 code path

**Non-Goals**

- ❌ Tie decay（V2 再做）。理由：V1 看累积趋势；想清楚再做衰减系数 / 公式
- ❌ Trust / 同质性偏置：弱关系不带"亲疏 / 信任度"，只有强度
- ❌ Conversation / 多方对话：那是下一个 change `conversation-capability` 的领地
- ❌ 数字社交（online ties via push / feed）：本 change 只关注物理 co-location 派生的 ties
- ❌ 历史回填：服务启动时**不**扫 memory store 重建 ties；从启动 tick 0 开始累积
- ❌ Tie 类型化（家庭 / 同事 / 邻居）：V1 只有一种 generic tie

## Decisions

### D1：Strength 公式选 `N / (N + K)` 而非 sigmoid 或线性

**做什么**：
```python
strength = encounter_count / (encounter_count + K)   # K = 10
```

**理由**：
- **平滑且单调**：1 次 → 0.09，5 次 → 0.33，10 次 → 0.50（weak tie 阈值），30 次 → 0.75
- **K 半饱和参数语义清晰**："多少次 encounter 算 weak tie 50%"——K=10 暗示 10 天每天碰一次就算"邻居"
- **饱和但不到 1**：避免"数到爆"的问题
- **不需要 fit**：单参数 K 即可调，没有 sigmoid 的非线性曲率参数

**Alternatives considered**：
- **A. 线性 `strength = min(1.0, N * 0.05)`** —— 拒绝。20 次后所有人都是 1.0，分辨力丢失。
- **B. Sigmoid `1 / (1 + exp(-(N - 10)/3))`** —— 拒绝。两个参数（中点 + 斜率），过度参数化。
- **C. 选 D1（asymptotic）** —— ✓ 单参数、可解释、平滑。

### D2：Pair canonical ordering（lexico smaller 在前）

**做什么**：所有 internal storage 都用 `(agent_a, agent_b)` 满足 `agent_a < agent_b`。lookup / record 时先 normalize。

**理由**：
- 同一对 (Emma, Linda) 不能存两条记录 (E, L) + (L, E) → dedup 必要
- 用排序 tuple 当 dict key 简单且 O(1)
- 无方向性 tie 是 V1 的明确假设（有方向性留给 conversation-capability 那边）

### D3：Service 持有 in-memory dict，不持久化

**做什么**：
```python
class SocialGraphService:
    _ties: dict[tuple[str, str], Tie]   # canonical pair → Tie
```

**理由**：
- 单进程 sim，不需要跨 process / cross-run 持久化
- 14 day × 100 agent × ~50 encounters/day-pair = 50k unique pairs 上限，内存 < 5MB
- Multi-day run 末调 `run_daily_summary` 时可序列化进 inspector payload，**但 service 内部不存储跨 run state**

### D4：MemoryService 注入 SocialGraph，而非 SocialGraph 订阅 Orchestrator

**做什么**：`MemoryService.__init__(..., social_graph: SocialGraphService | None = None)`，process_tick 内部转发 encounter_candidates 给 graph.

**理由**：
- MemoryService 已经在每 tick 处理 encounter_candidates；让它顺手转发，避免 Orchestrator 多挂一个 hook
- social_graph 只接收一个领域 fact（"两 agent 在 tick X co-located"）—— Demeter law 友好
- 测试时可不传 social_graph，旧行为完全保留

**Alternatives considered**：
- **A. SocialGraphService 自己 register_on_tick_end** —— 拒绝。增加 orchestrator 耦合面；orch 已挂 N 个 hook，再加一个不利于人理解。
- **B. 选 D4（依赖注入到 MemoryService）** —— ✓ 单一入口处理 encounter。

### D5：is_familiar 来源切换：从 memory.encounter 改到 social_graph.familiar_with

**做什么**：`MemoryService._nearby_agents_for` 装配 NearbyAgent 时，`is_familiar` 用 `self._social_graph.familiar_with(agent_id)`（如果 social_graph 注入了），否则降级到原行为（memory 里有 encounter actor_id）。

**理由**：
- 当前 attention-rebalance 的 is_familiar 是"曾在 memory 出现过"，过于宽松——见过一次的人也算 familiar
- social_graph 提供阈值化判断：strength > 0.1（即 > ~1 次 encounter）才算 familiar
- 渐进式：social_graph=None 时旧行为不变，注入时升级

### D6：Metric 集成走 TickMetricsRecorder 已有 hook

**做什么**：TickMetricsRecorder 接受 social_graph 引用，每 tick 末（或每日末）从 graph dump 4 个新指标进 RunMetrics。

**理由**：
- 不增加新 hook 类型；recorder 已经是 SuiteAggregate 上游唯一聚合点
- contest scorer 能消费任何 RunMetrics 字段作为 primary_metric——只要新指标是 numeric

## Risks / Trade-offs

[**风险 R1**] K=10 的半饱和阈值是先验拍的；真实"邻里关系建立"门槛不一定是 10 次 co-location
→ **Mitigation**：K 作为 SocialGraphService 构造参数（default 10），dev / publishable 各自实验找合适值。如果 e2e 测试发现 K=10 让 hp 跟 baseline 区分度太低 / 太高，可调到 5 或 20 而无需改公式。

[**风险 R2**] 不做 tie decay —— 14 天 sim 跑完每个 agent 的 ties 数量只能涨不能减；长期会"通货膨胀"
→ **Mitigation**：本 change 14 天 scale 不会撞上这个问题（最多 ~14 个 unique encounter pairs 总不到 100）。decay 留 V2，加 `last_seen_tick` 字段已经为它准备好。

[**风险 R3**] 社会层 metrics 加了之后 contest scorer 可能改变 alignment 结论（hp / gd 现在 inconclusive，加新 metric 后可能变 supports 或 contradicts，且方向未知）
→ **Mitigation**：新 metric 是**新增不替换**——baseline 的 trajectory_deviation_m / encounter.total 仍然存在。新 tie metric 进入 contest 但作为 secondary 信号，不强制成为 primary_metric（spec 要求 hp 可选用 tie_count_weak 作为 primary，而非必须）。

[**风险 R4**] 100 agent 在 7 天内可能产生 < 5 weak ties，metric 信号弱到不可用
→ **Mitigation**：通过 e2e test 提前 baseline 一下数量级。如果实际 < 5 ties 总数，K 调小到 5；如果还不够，把 weak tie 阈值从 0.1 降到 0.05（即 0.5 次 encounter 就算 familiar）。

## Migration Plan

无破坏性 API 变更：

1. **Step 1**：实现 social_graph capability 模块；MemoryService / metrics / agent 接受 optional social_graph 参数；不传时走旧行为
2. **Step 2**：tools/run_variant_suite.py 构造 SocialGraphService 注入；publishable suite 默认带 social_graph
3. **Step 3**：跑一次 5 seed × 7 day dev suite，验证 hp.tie_count_weak > baseline.tie_count_weak
4. **Step 4**：commit + archive；下一个 change `conversation-capability` 立项

回滚：tools 不传 social_graph 即可降级到旧行为，无需 code 回滚。

## Open Questions

1. **Q1**：weak tie 阈值用 strength > 0.1（~ 1 次 encounter）还是 > 0.2（~ 2-3 次）？
   - **倾向**：0.1。一次 encounter 后再次见到时不应该当陌生人。

2. **Q2**：strong tie 阈值用 strength > 0.5（10 次 encounter，K=10）还是 > 0.7（~ 25 次）？
   - **倾向**：0.5。在 14 天 sim scope 里，让"强关系"门槛进得去。

3. **Q3**：encounter pair 在同一 tick 出现多次 (e.g., A 和 B 在两个 shared_locations) 算 1 次还是 N 次？
   - **倾向**：1 次。tick + pair 唯一性。理由：同 tick 同 pair 仍是同一个"会面事件"。

4. **Q4**：weak ties metric 如何展示在 inspector payload？
   - **倾向**：每个 inspected agent 输出 `weak_ties: list[{other_agent_id, strength, encounter_count}]`，方便前端可视化"agent X 这周认识了哪些人"。

5. **Q5**：是否在 design 阶段就提供"sleeping tie 激活"概念（即 hp push 把过去见过 1 次的人重新拉到一起）？
   - **倾向**：不做。下一个 change `conversation-capability` 用得着这个概念再加，本 change 保持轻。
