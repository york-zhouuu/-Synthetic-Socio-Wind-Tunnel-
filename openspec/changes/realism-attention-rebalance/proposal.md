## Why

当前 push 在 agent 决策中是**打断式中心事件**，不是**上下文中可被权衡的一个信号**——这与现实中手机注意力的工作方式不一致，并且会让我们的核心论证（hyperlocal push 改变行为）产生 prompt artifact 风险。

具体表现：

1. **Prompt 结构把 push 放在中心**（`synthetic_socio_wind_tunnel/agent/planner.py:580 _build_replan_prompt`）。当前模板：
   ```
   当前时刻：{current_time}
   发生了以下事件，打断了你的计划：
   {trigger_desc}        ← push 内容居中
   最近的记忆：{memory}
   你当前计划里还剩下的步骤：...
   请重新规划...
   ```
   推送事件被置于"打断者"位置，而**物理环境（agent 当前正在做什么 / 看见什么）/ 内部状态（疲劳 / 心情）/ 社交（同行人 / 周围人）/ 习惯锚（life_pattern）**根本没进 prompt。LLM 几乎只能看到 push，自然倾向跟着 push 走。

2. **数据上的不对称**：v2 publishable real-LLM suite 显示 hp variant 相对 baseline 有 ~22% encounter shift；现实世界 hyperlocal push 的 CTR 普遍 < 2%，行为改变率更低。22% vs <2% 差一个数量级——可能不是真实信号，而是 prompt 工程伪影。

3. **反向的失灵**：刚跑的 inspector payload（1 seed × 6 inspected agents × 7 days × hyperlocal_push variant，使用 Gemini Flash）：12 条 push delivered，**0 条 replan_traces**。也就是说在小样本下 should_replan 阈值反而过严——同一套机制在大 suite 里看着像"100% 反应"，在小 inspector 里像"0% 反应"，**机制本身并不稳定**。

我们要的不是更多 push 触发 replan、也不是更少。我们要的是：

> push 是 context 中**与物理 / 记忆 / 内部状态 / 社交并列**的一个输入；response 由 personality（已部分接入 routine_adherence + curiosity）× 当时所有 context 信号共同决定；同样的 push 给不同 agent 在不同时刻产生**有解释力的差异化反应**——既不全 0，也不全 1。

修这个是 thesis 自身可信度的根本前提：如果 push 表现的"行为改变"主要来自 prompt 结构而非真实的注意力竞争，那么 hp ≠ baseline 这个结果就经不住质疑。

## What Changes

### Prompt 层（planner.py）

- **重构 `_build_replan_prompt`**：把当前的"打断者居中"模板改为**对称 context window**：
  ```
  当前时刻 / 当前位置 / 当前活动
  你的人格：{personality 8 维 + life_pattern 锚点}
  你最近发生的事：{recent_memories}
  你周围的环境：{周围人 / 当前 location 类型 / 其他 agent}
  你刚收到一条手机推送：{push 内容}
  你的当前剩余计划：...
  
  问：基于以上所有信息综合判断，你会改变行为吗？
  ```
- push 不再被标记为"打断者"——它只是 context block 之一，跟 personality / memory / 周围 / 计划并列。

### 决策门控层（memory + agent）

- **`should_replan` 阈值多元化**：当前是单一 `urgency > 0.4 + 0.3*adherence - 0.3*curiosity`。改为：
  - 引入 personality 多维（`extraversion` / `risk_tolerance` / `openness` 都参与）
  - 加入 context modifier：刚刚完成 commute 的 agent 阈值比刚醒来的高（疲惫不易被新信息拉走）
  - 引入随机性 noise（防止 deterministic 全 0 或全 1）

- **目标拟真带**：跨 24 小时跨 100 agent，hyperlocal push 触发 replan 的比例落在 **5-15%**——既显著高于 0、又远低于 100%；与现实 CTR + 实际行为改变率（<5%）合理对齐。

### 验证层（新测试 + 监控）

- 新增 `tests/test_attention_rebalance.py`：
  - prompt 结构测试：push 不在 prompt 居中位置
  - response heterogeneity：同一 push 给 8 维 personality 不同的 100 agent，response 分布应该是多峰
  - 拟真带：hyperlocal_push 变体下 replan 触发率 ∈ [5%, 15%]
- 在 inspector payload 增加 `replan_decision_log`：每次 should_replan 调用的入参 + 阈值 + 结果，可追溯解释每个 0 / 1 决策。

### 非目标（Non-goals）

- ❌ **不**做 push 内容个体化（roadmap 原 Stage 3 内容）——延到下一个 change
- ❌ **不**做 household coupling（Stage 4）
- ❌ **不**做 POI capacity（Stage 5）
- ❌ **不**重做 AttentionService 的投递机制 / bias filter（只调阈值，不改架构）
- ❌ **不**重做 memory.py 的事件流模型
- ❌ **不**改 scripted_plan path（Haiku 档 990 个 agent 走 scripted；只动 LLM replan 路径）

## Capabilities

### New Capabilities

无。这是对现有能力的 rebalance，不引入新的能力边界。

### Modified Capabilities

- `agent`：`Planner._build_replan_prompt` 的 prompt 结构由"打断者居中"改为"对称 context window"；`Planner.replan` 接受更丰富的 interrupt_ctx（physical / social / internal blocks）。
- `memory`：`MemoryService.process_tick` 中调用 `should_replan` 的判定从单一 urgency 阈值改为多元 personality + context-modifier 阈值；引入决策日志便于解释和回归。

### Untouched

- `attention-channel` 不动（投递、urgency 标签、bias filter 保持原状）
- `cartography` / `atlas` / `ledger` / `engine` / `perception` 不动
- `orchestrator` / `multi-day-run` / `policy-hack` / `metrics` / `suite-wiring` 不动

## Impact

**代码**：
- `synthetic_socio_wind_tunnel/agent/planner.py`（`_build_replan_prompt` 重写；`Planner.replan` 接受额外 ctx 字段）
- `synthetic_socio_wind_tunnel/memory/service.py`（`should_replan` 多元阈值 + 决策日志）
- `synthetic_socio_wind_tunnel/agent/runtime.py`（`build_observer_context` 已有，可能需要扩展暴露给 planner ctx）
- `tools/export_inspector_payload.py`（输出 `replan_decision_log`）

**测试**：
- `tests/test_planner.py`（prompt 结构断言）
- `tests/test_memory.py`（should_replan 多元判定）
- 新增 `tests/test_attention_rebalance.py`（拟真带 + heterogeneity）

**外部约定**：
- 重跑 publishable suite（30 seeds × 14 days × 6 variants）查看 hp vs baseline 在新阈值下的 effect size——可能从 22% 降到 5-8% 区间。**这是预期的，不是问题**：更小但更可信的 effect size 比大但有 prompt artifact 嫌疑的 effect size 更值得发表。
- v2 publishable suite 报告中的 effect size 数字会被新数据覆盖；要在 commit message 里清楚标注前后对比。

**风险**：
- 拟真带 [5%, 15%] 是先验目标，可能跑出来落不到这个区间——若如此，需要回到 design 阶段重新讨论是否需要更细粒度的拟合（personality × context interaction 的更复杂建模）。
- prompt 重构后 LLM 输出的 plan 质量可能不一致（XML parser 已有 fallback，但需 dev 跑一遍验证）。

**性能**：prompt 长度增加 ~30-50 token，单次 replan LLM 调用成本上涨 < 10%；可接受。
