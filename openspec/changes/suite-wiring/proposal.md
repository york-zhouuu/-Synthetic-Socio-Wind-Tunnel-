## Why

metrics 归档后的 smoke 跑暴露了一个关键 wiring 缺口：`tools/run_variant_suite.py`
构造 orchestrator 栈时**没有接入 `MemoryService` 与 `Planner.replan`**，结果：

```
AttentionService.inject_feed_item(...)    ✓（policy-hack variant 会 push）
   │
   ▼
NotificationEvent 进入 attention channel    ✓（基建层）
   │                                           
   ▽ ↔ ↔ ↔ ↔ ↔ ↔ ↔ ↔ ↔ ↔ ↔ ↔ ↔ ↔ ↔ ↔ ↔  ← 这里断了
   │
   × MemoryService.process_tick            ← 没接入
   × agent.should_replan                    ← 没触发
   × planner.replan                         ← 不运行
   │
   ▼
AgentRuntime.step() 读 **scripted plan**    ← 行为完全不受 push 影响
```

后果：在 metrics 的 6-variant × 2 seed × 3 天 smoke 里，
- `hyperlocal_push` 与 `global_distraction` 的 `trajectory_deviation_m` **byte-equal**（356.27m）
- `phone_friction` 的 `phone_feed_proxy` 与 baseline 都是 0.0
- `shared_anchor` / `catalyst_seeding` 的 encounter 数与 baseline 一致
- 所有 6 行 Contest 判 `inconclusive`——不是因为 seed 不够，是因为**没有行为差**

换言之，**风洞造好了，但飞行器没装进去**。本 change 补上 variant → attention →
memory → replan → 行为 的那段缺失因果链。

**Chain-Position**: `infrastructure`（CLI 层组装修补；不引入新边界、不改
任何已归档 capability 的 spec 契约）。

**Fitness-report 锚点**：非 phase-2-roadmap 能力的 follow-up。动机来自
metrics 归档日 smoke 的实测观察，记录在
`openspec/changes/archive/2026-04-23-metrics/` 的 sync 讨论 +
本 proposal 的上游引用。

## What Changes

### 1. 新 helper `tools/suite_stub_llm.py`（NEW file）

`StubReplanLLM` ——**零 LLM 成本**、**seed-reproducible** 的 replan 客户端。

- 实现 `LLMClient` 协议（`async generate(prompt, *, model) -> str`）
- 从 prompt 中解析 trigger event 的 `origin_hack_id`（variant 签名，policy-hack
  已在 FeedItem 里填）+ 事件 content
- 对不同 variant 签名产生不同 plan JSON：
  - `"hyperlocal_push"` → 生成走向 target_location 的 plan step
  - `"global_distraction"` → 空 plan（global news 不拉 agent；stub 体现
    "无效推送"语义）
  - `"shared_anchor"` → 走向 task_templates 隐含的 community 地点
  - 其它（含未知）→ 返回空 JSON list（planner.replan 兜底保持原 plan）
- 所有输出都从 `Random(seed + tick + agent_id hash)` 派生，跨 seed 可复现

### 2. 修改 `tools/run_variant_suite.py`（MODIFIED）

`run_seed_with_metrics` 的 orchestrator 栈增补：

```python
# before (metrics archive 时):
orchestrator = Orchestrator(atlas, ledger, runtimes,
                            attention_service=attention, ...)
orchestrator.register_on_tick_end(recorder.on_tick_end)
# memory + planner 未接入

# after (本 change):
memory = MemoryService(attention_service=attention)
planner = Planner(llm_client=StubReplanLLM(seed=seed))  # 或真 LLM
orchestrator.register_on_tick_end(recorder.on_tick_end)
orchestrator.register_on_tick_end(
    lambda tr: memory.process_tick(tr, agents_by_id, planner)
)
# memory.process_tick 内部会调 agent.should_replan + planner.replan
```

### 3. 新 CLI flag `--use-real-llm`

默认 False（走 `StubReplanLLM`）。True 时 import `anthropic.Anthropic` 用真
Haiku。**不改变本 change 范围**——只是 opt-in；真实 LLM 成本门禁与速率限制
留给未来 `model-budget` change。若 anthropic SDK 未安装，启用 flag 时立刻
报错退出。

### 4. Replan 事件被 metrics 观察到（最小扩展）

为让 metrics smoke 读者能看到 "wiring 起作用了" 的直观信号，通过
`RunMetrics.with_extensions(replan_count=N, replan_by_variant={...})` 把
replan 次数写入 metrics **extensions** dict（`metrics` spec 明文预留的
未来挂载点，无需改 metrics spec）。

实现路径：`run_seed_with_metrics` 在 `memory.process_tick` 返回的 replan
list 上累加计数，run 结束后用 `run_metrics.with_extensions(...)` 写入。

### 5. Tests

- `tests/test_suite_stub_llm.py`: StubReplanLLM 对每种 variant 签名产出合法
  JSON；空 prompt 时 fallback；跨 seed 可复现
- `tests/test_suite_wiring.py`（E2E 扩展 `test_run_variant_suite.py`）：
  - **行为差异断言**：3 天 × 2 seed × 20 agent 下，hyperlocal_push 的
    trajectory_deviation_m **显著小于** global_distraction（方向正确）
  - replan_count 字段在 extensions 里可见；baseline 为 0、push variant > 0

### 6. 文档

- `docs/agent_system/17-suite-wiring.md`（新）：
  - 完整因果链图（variant → feed → memory → replan → agent → 行为）
  - StubReplanLLM 的 variant 签名分派表
  - `--use-real-llm` 切换语义
  - 与 metrics / policy-hack / multi-day-run 的关系
- 更新 `README.md` Development Status：加 "Suite wiring (variant→replan 因果链)"

## Non-goals

- **不**抽象 LLM provider（Haiku 硬编码；多 provider 属未来）
- **不**做 cost 控制 / token 预算（`model-budget` change 的事）
- **不**扩展 `AttentionState` 到完整四元组（perception 层扩展）
- **不**改任何已归档 capability 的 spec 契约——纯 CLI 层 + 新 helper
- **不**新增 phase-2-roadmap capability——这是归档 change 的 wiring 修补
- **不**预设实验结果——仅要求 hyperlocal_push 与 global_distraction 的 trajectory 
  可区分（方向正确），不要求 inconclusive → consistent（那需要 30 seed × 14 天）

## Capabilities

### New Capabilities

（无——本 change 不引入 capability；修的是 CLI 组装）

### Modified Capabilities

（无 spec 变动——只改 CLI 与文档）

## Impact

- **新代码**：
  - `tools/suite_stub_llm.py`（StubReplanLLM + `_extract_origin_hack_id` 
    helper + variant 签名 dispatch）
- **修改**：
  - `tools/run_variant_suite.py`（orchestrator 栈增补 + `--use-real-llm`
    + replan_count 采集）
- **新增测试**：
  - `tests/test_suite_stub_llm.py`
  - `tests/test_suite_wiring.py`（E2E 3 天 × 2 seed，断言行为差异）
- **文档**：新 `docs/agent_system/17-suite-wiring.md` + README 更新
- **前置依赖**：
  - `metrics` capability（RunMetrics.with_extensions）
  - `policy-hack` capability（VARIANTS + FeedItem.origin_hack_id）
  - `multi-day-run` capability（MultiDayRunner）
  - `memory` capability（MemoryService.process_tick + planner.replan）
  - 全部已归档，只用既有公共 API
- **下游影响**：补完之后，`data/experiments/*` 的 ContestReport **第一次**
  会产出 variant 之间可区分的 effect size（即使 seed 少，mirror_delta 会
  是非零值）
- **性能**：StubReplanLLM 零 LLM 调用；memory.process_tick 每 tick O(agent ×
  event)；3 天 × 20 agent × 288 tick ≈ 17,000 memory 记录，内存可忽略
