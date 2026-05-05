## Context

当前 push → replan 的链路在两个层面存在结构性偏差：

1. **Prompt 层（`planner.py:580 _build_replan_prompt`）**：push 被置于"打断者"位置，居中显示；其它 context（physical / social / internal / habit）几乎不入 prompt。LLM 几乎只能基于 push + memory 决策——结构本身在向"跟着 push 走"倾斜。

2. **门控层（`runtime.py:167 should_replan`）**：单一 urgency 阈值
   ```python
   threshold = 0.4 + 0.3 * routine_adherence - 0.3 * curiosity
   return candidate.urgency > threshold
   ```
   只用 2 维 personality；无 context modifier；无随机性。结果：在不同 sample 规模下表现极不稳定（v2 publishable 30 seed × 100 agent 看到 22% encounter shift；inspector 1 seed × 6 agent 看到 0% replan）。

这个 change 不重写两层架构，只**重新平衡 prompt 内容比例 + 阈值表达力**——架构无破坏，行为更接近真人。

## Goals / Non-Goals

**Goals**

1. **Prompt 对称性**：push 是 prompt 中**与 personality / memory / 周围环境 / 当前活动 / life_pattern 并列**的一个 block，不被语言学特殊化为"打断者"。
2. **Goldilocks 触发率**：跨 100 agent × 24 小时，hyperlocal_push 触发 replan 的比例落在 **[5%, 15%]**。低于 5% = push 被全无视（thesis 立不住）；高于 15% = push 太轻易拽走（不真实，prompt artifact）。
3. **个体异质响应**：同一条 push 给 8 维 personality 不同的 100 agent，response 应该是**多峰分布**（不同 personality 簇有不同模态），不是单峰。
4. **可解释性**：每次 should_replan 决策（True / False）都留下决策日志，能追溯到入参 + 阈值 + 哪些 personality 维度起作用。

**Non-Goals**

- ❌ Push 内容个体化（语言 / 兴趣定制）——延到下一个 change
- ❌ 改 AttentionService 投递机制 / bias filter 算法
- ❌ 改 MemoryEvent 数据模型 / 4-way 检索打分
- ❌ 重做 scripted_plan（990 个 Haiku 档 agent 仍走 scripted；本 change 仅动 LLM replan 路径，覆盖 10 protag + 中段 200 agent）
- ❌ 重做 PerceptionPipeline——它本身已经能渲染 SubjectiveView，只是没接进 replan prompt

## Decisions

### D1：Prompt 重构为"对称 context window"

**做什么**：`_build_replan_prompt` 模板从下面这个：
```
当前时刻：{t}
发生了以下事件，打断了你的计划：
{trigger_desc}
最近的记忆：{memory}
你当前计划里还剩下的步骤：{remaining}
请重新规划...
```
改为：
```
你是 {name}。
人格：{personality 8 dim + life_pattern 锚点}

【现在】{t} · 你在 {current_location}（{location_kind: street/cafe/park/home}）
【正在做】{current_step.activity} ({current_step.duration_min}min, social={social_intent})
【周围】{nearby_agents 数 + 类型，e.g. "1 familiar + 2 strangers"}
【最近发生】{recent_memories 最多 5 条}
【手机】刚收到一条推送：{push 内容}
【接下来计划】{remaining_steps}

问：综合以上信息，你会改变接下来的计划吗？
```

**理由**：所有 context block 用同样的 markdown 强度展示（`【...】`包裹），push 不再是"事件 / 打断者"，只是"手机"项之一。LLM 不会被 prompt 结构暗示"必须响应 push"。

**Alternatives considered**：

- **A. 完全不放 push 进 prompt，只用 should_replan 门控** —— 拒绝。push 必须能被语言模型评估，否则我们只是在 personality 层做线性回归，丢掉 LLM 的 context understanding。
- **B. Push 放 prompt 末尾而非中间** —— 拒绝。仍然是位置编排技巧；context window 注意力分布不可控。
- **C. 选 D1（对称 markdown blocks）** —— ✓ 显式对称，不依赖位置 / 语序。

### D2：should_replan 多元阈值 + 上下文 modifier

当前公式：
```
threshold = 0.4 + 0.3 * adherence - 0.3 * curiosity
trigger = urgency > threshold
```

新公式（伪代码）：
```python
def should_replan(memory_view, candidate, current_step) -> bool:
    p = profile.personality
    base = 0.40 \
         + 0.25 * p.routine_adherence \
         - 0.20 * p.curiosity \
         - 0.15 * p.openness \
         + 0.10 * p.conscientiousness \
         - 0.10 * p.risk_tolerance + 0.05    # noise injection 通过 rng

    # context modifier：刚开始的 step 比刚做完的 step 阈值高
    #（已经走在路上 / 已经投入活动的 agent 不易被新信息拉走）
    if current_step.elapsed_min > current_step.duration_min * 0.3:
        base += 0.10

    # 同一 agent 本天累计 replan 次数衰减响应（疲劳 → 阈值升高）
    base += 0.05 * replan_count_today
    
    return rng.random() + (candidate.urgency - base) > 0  # 概率门，不是硬阈值
```

**关键变化**：
- 6 维 personality 共同决定（不只 2 维）
- context modifier：同一个 agent 在不同时刻反应不一样
- replan_count_today 衰减：避免一个 agent 一天替换 plan 5 次
- 概率门（`rng.random() + (urgency - base) > 0`）取代硬阈值：urgency=0.6 时不再"全 0 或全 1"

**Alternatives considered**：

- **A. 简单拓宽为 4 维 personality 但保持硬阈值** —— 拒绝。硬阈值是当前 inspector 看到 0 replan 的根因，不动它问题不解决。
- **B. 全 LLM 决策（move should_replan 进 LLM）** —— 拒绝。每 tick 每 agent 触发 LLM 调用预算爆炸。
- **C. 选 D2（多元 + 概率门 + context modifier）** —— ✓ 表达力够、成本不变、可解释。

### D3：interrupt_ctx 扩充

`Planner.replan(profile, current_plan, interrupt_ctx)` 的 `interrupt_ctx` schema：

```python
interrupt_ctx = {
    "trigger_event": MemoryEvent,        # 已有
    "recent_memories": list[MemoryEvent], # 已有
    "current_time": datetime,             # 已有
    # 新增：
    "current_step": PlanStep | None,        # 当前正在执行的 step
    "current_location_kind": str,            # "street"/"cafe"/"park"/"home"/...
    "nearby_agents": list[NearbyAgent],     # familiar / stranger 标签
    "social_state": dict,                    # 同行人 / 是否独处 (从 social_intent 推)
}
```

`MemoryService.process_tick` 负责装配这个 dict 后传给 `planner.replan`。physical / social 信号取自 `tick_result` + `ledger`；不重新调 PerceptionPipeline（避免 hot path 加 render 调用）。

### D4：Replan rate observability

每次 replan 决策（无论 True / False），记录：
```python
ReplanDecisionRecord(
    agent_id, tick, simulated_time,
    candidate_kind, candidate_urgency,
    threshold_computed, base_components={"adherence": 0.25, ...},
    context_modifier=0.10, replan_count_today=2,
    rng_roll=0.45, decision=True,
)
```

每 run 末汇总成 `replan_rate_by_variant`。Suite metrics 加一个新指标 `replan_rate_per_agent_per_day`，以变量纳入 contest report。

### D5：Suite 验证回归

- 新增 `tests/test_attention_rebalance.py`：
  - prompt 不含字符串 "打断了你的计划" / "interrupted your plan"
  - prompt 含 `【现在】` / `【正在做】` / `【周围】` / `【手机】` / `【接下来计划】` 五个 block 标记
  - 100 agent 同 push 跑一次，replan 决定的 personality 簇分布出现至少 3 个 mode
  - 触发率（hyperlocal_push variant 下）∈ [5%, 15%]
- 跑一次 dev 规模 publishable suite（5 seeds × 7 day × 6 variants），验证 hp 与 baseline 仍然有可检测 effect size（即使变小）

## Risks / Trade-offs

[**风险 R1**] effect size 可能从 22% 降到 < 3%，不再有统计显著性 → publishable suite 拿不到 hp ≠ baseline 的 finding
→ **Mitigation**：先跑 5 seeds dev 量级看数。若 effect size < 3% 且 CI 越 0，文档化为"在严谨 context model 下，hyperlocal push 的行为效应是边际级"——这本身是有价值的 negative finding。如果落到 3-8% 区间且 CI 不越 0，那是教科书级"小但真"effect size。

[**风险 R2**] prompt 重构后 LLM 输出的 plan 质量降低（XML 解析失败率上升）
→ **Mitigation**：现有 `_parse_xml_plan` 已有 fallback 路径（解析失败回 current_plan copy）。Apply 阶段先在 stub LLM 上跑过测试套件再切真 LLM。

[**风险 R3**] context modifier 引入 `current_step.elapsed_min`，需要从 `AgentRuntime` 暴露 step 进度——可能撞 runtime API 边界
→ **Mitigation**：`AgentRuntime` 已经持有 `_current_step_started_at`，加个只读属性即可，不破坏现有 API。

[**风险 R4**] D2 的概率门引入 RNG，破坏 reproducibility lock
→ **Mitigation**：should_replan 的 rng 必须取自 `MemoryService` 持有的 seeded `random.Random` 实例（已有），不能用 module-level random。reproducibility lock 既有 7 字段已覆盖 seed_pool，无需新增。

## Migration Plan

无破坏性 API 变更。

- Step 1：新分支实现 D1-D5；跑 dev mode publishable suite 看数
- Step 2：跑全规模 publishable suite（30 seeds × 14 days × 6 variants）→ 新数据替换 v2 数据
- Step 3：报告差异（commit message 明确标注 22% → 新值），更新 `docs/agent_system/19-system-snapshot.md`
- Step 4：归档 change

回滚策略：保留旧 prompt + 旧 should_replan 公式作为内部版本号 `v1`；新版 `v2`；CLI 加 `--prompt-version v1|v2`，必要时回退。**只在出大问题时启用**——日常不应同时维护两版。

## Open Questions

1. **Q1**：Goldilocks band [5%, 15%] 是先验拍的，没有外部 ground truth。是否需要先做一次小型外部校准（找 5-10 个真人，给 hyperlocal push 看 24 小时反应）来 ground truth？
   - **倾向**：先验跑、看数据、必要时再做真人校准。前期 ROI 低。

2. **Q2**：context modifier 的 `current_step.elapsed_min` 在 agent 还没开始 move 的场景（在家待机）怎么处理？
   - **倾向**：在 home_location stay step 中，elapsed_min 记 0，modifier 为 0；只有 active step（move / errand / leisure）才生效。

3. **Q3**：`nearby_agents` 在小 atlas / 稀疏布局下经常是空集，prompt 会显示"周围：无"——这会不会让 LLM 系统性地认为"独处所以可以换计划"？
   - **倾向**：不显示"无"，整个 `【周围】` block 在为空时省略。LLM 不会被空集误导。

4. **Q4**：D2 的 6 维 personality 系数是先验拍的（`+0.25 * routine_adherence` 等），是否应该可配置？
   - **倾向**：不配置，作为 frozen constants 写入代码。等数据出来后再决定要不要参数化。
