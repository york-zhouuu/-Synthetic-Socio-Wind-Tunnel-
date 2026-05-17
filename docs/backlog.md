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
