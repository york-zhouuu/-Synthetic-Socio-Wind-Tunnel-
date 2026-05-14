## Why

`Chain-Position: spatial-output → social-downstream`（thesis 因果链最后一环）

thesis 声明的因果链是：

```
手机推送  →  注意力转移  →  到达推送地点  →  看见附近  →  真的"附近"了
  ↓            ↓              ↓                ↓                ↓
attention-  attention-     scripted_plan +   ❌缺           encounter +
channel     main           navigation        感知           reflection
✅          ✅             ✅                此环节         ⚠️ 半信号
```

现在缺**最后一环之前的关键步**：agent 走到 cafe 坐标，但**不会"看见" cafe**。
`PerceptionPipeline`（视觉 / 听觉 / 嗅觉滤镜）实现完整，但：

1. `synthetic_socio_wind_tunnel/agent/scripted_plan.py::build_scripted_plan` 完全
   不调 `PerceptionPipeline.render()`——990 个 scripted agent 永远无视感知。
2. `synthetic_socio_wind_tunnel/agent/planner.py::Planner.replan` 也不调——10
   个 protag 在 replan prompt 里看不到"窗外正在发生什么"。
3. `synthetic_socio_wind_tunnel/agent/runtime.py::build_observer_context()` 实现
   完整，但**只被 perception 自检调用**，没接进决策。

**后果**：
- thesis 答辩塌——审稿人会问"agent 真的'感受到附近'了吗？"，回答只能是"不"。
- reflection 内容空洞："我去了 Cowper 街口 cafe"（应该是"我在 cafe 看到那个总
  坐窗边的男人"）。
- 2.5D 沙盘 inspector 缺最重要功能（"agent 此刻看到什么"）。
- F4 拟真维度（来自 `docs/agent_system/20-realism-roadmap.md`）从 0% 接入。

本 change = 拟真度 Stage 2，把感知接入决策回路。

## What Changes

- **MODIFIED**：`agent::Planner.replan` 接受可选 `perceptual_context: SubjectiveView | None`
  参数；当注入时，prompt 增加 `【环境】` block 描述 agent **看见 / 听见的具体场景**
  （"cafe_main 现在排着 5 个人"、"街角广告牌写着今晚有音乐会"）。
- **MODIFIED**：`agent::AgentRuntime.step` 在调 `Planner.replan` 前调用
  `perception.render(observer_ctx)` 取 `SubjectiveView`，作为 `perceptual_context`
  传给 replan。
- **ADDED**：`agent::scripted_plan` 新增 lightweight perception-gated rule：
  当 agent 抵达 destination 时，若 `SubjectiveView.visible_entities` 包含同
  location 的 agent 数 > `crowd_threshold`（默认 5），有概率（受 `personality.openness`
  调制）触发"换 destination"——以替代纯 LLM-driven path 给 990 个 scripted agent
  也加一层"看到拥挤就换地方"的反应。
- **ADDED**：新 `tools/agent_perception_inspector.py`：CLI 工具，dump 给定 (seed,
  agent_id, day, tick) 的 SubjectiveView 文本快照——用于 debug + 给后续 2.5D
  沙盘 C3 inspector 面板提供数据源。
- **MODIFIED**：`perception::ObserverContext` 已带 `digital_state`；保持不变。
  本 change 只是**让 Planner / scripted_plan 真正读 SubjectiveView 输出**——
  不动 perception 内部。
- **NON-GOAL**：本 change **不**改 perception 内部滤镜（视觉 / 听觉 / 嗅觉）；
  这些已经在 `perception` capability 里 ship。
- **NON-GOAL**：本 change **不**对 protag 走 ai-town 路径的 `do_something /
  generate_message` ops 加感知 block——那是后续 ai-town port 完善的范围。
- **NON-GOAL**：本 change **不**改 `scripted_plan` 主循环（time-of-day 模板 +
  destination sampling）；只在抵达后加 perception check。

## Capabilities

### New Capabilities

无。本 change 是接通已有 perception 与 agent 的接口缺口。

### Modified Capabilities

- `agent`: `Planner.replan` 接受 perceptual_context；`scripted_plan` 加 perception-gated
  destination-swap rule；`AgentRuntime.step` 在 replan 前 render perception。

## Impact

**代码**：
- `synthetic_socio_wind_tunnel/agent/planner.py::Planner.replan` —— 签名增加
  `perceptual_context` kwarg；prompt 增加 `【环境】` block；解析逻辑不变
- `synthetic_socio_wind_tunnel/agent/planner.py::_build_replan_prompt` —— 增加
  perception render helper
- `synthetic_socio_wind_tunnel/agent/runtime.py::AgentRuntime.step` —— replan
  分支前 render perception；存进 interrupt_ctx
- `synthetic_socio_wind_tunnel/agent/scripted_plan.py` —— 新 helper
  `_perception_gated_destination_swap(plan_step, observer_ctx, rng)`；step 抵达
  后调用
- `tools/agent_perception_inspector.py` —— 新 CLI

**测试**：
- `tests/test_planner_perception_block.py` —— 验证 replan prompt 含 `【环境】`
  block；空 perceptual_context 时该 block 整块省略（不破坏现有 prompt 测试）
- `tests/test_scripted_plan_perception_gate.py` —— 验证 crowd_threshold 触发
  destination-swap；高 openness vs 低 openness 行为差异
- `tests/test_agent_runtime_perception_in_replan.py` —— 端到端：runtime step →
  replan prompt 真的含 perception 文本
- `tests/test_perception_inspector_cli.py` —— CLI smoke：dump 一个 agent 的
  SubjectiveView 文本

**API / 契约**：
- `Planner.replan` 签名向后兼容（新 kwarg 默认 None）—— 已有 callers
  （memory.process_tick）不需要改
- `scripted_plan` 输出仍是 DailyPlan；只是某些 step 现在能在中途插入
  destination-swap 替代

**外部影响**：
- A1 是 thesis 因果链最后一环 —— 完成后 publishable run 的 hp variant
  encounter / reflection 内容质量都会上升。
- 本 change **不**重跑 publishable suite；smoke 验证通过即归档。
- F4 拟真维度从 0% 接入到 70%（剩 30% 是后续 ai-town path 给 do_something /
  generate_message 加感知，留给 ai-town port 后续 task）。
