# Suite Wiring — 因果链接通

> 把已归档 `policy-hack` + `metrics` + `memory` 等 capability 的零件在
> Suite CLI 组装时**真的串成行为因果链**。由
> `openspec/changes/archive/2026-04-25-suite-wiring/` 实现。

---

## 问题背景

metrics 归档日的 smoke 跑暴露：`run_variant_suite.py` 构造 orchestrator
栈时**没挂 MemoryService + Planner**，结果：

```
variant.push(feed_item) ────► AttentionService ────► notification event ...
                                                                   │
                                                                   ▽
                                                     ↔ ↔ ↔ ↔ ↔ ↔ 🚫 断链
                                                                   │
                                                                   ▼
                                                   agent 读 scripted plan
                                                   （不受 notification 影响）
```

表现：hyperlocal_push 与 global_distraction 的 `trajectory_deviation_m`
**byte-equal**；contest 全部 inconclusive。

## 修后的因果链（完整版）

```
┌──────────────────────────────────────────────────────────────────┐
│ Variant (policy-hack)                                            │
│   apply_day_start(ctx) ─┐                                        │
│                          │                                       │
│                          ▼                                       │
│   AttentionService.inject_feed_item(item, recipients)            │
│                          │                                       │
│                          ▼                                       │
│   每 tick 结束时 fires on_tick_end:                               │
│     1. TickMetricsRecorder.on_tick_end(tr)      ← observe        │
│     2. MemoryService.process_tick(tr, agents, planner)  ← mutate │
│          │                                                        │
│          ├── 写 memory events（action / encounter / notification）│
│          │                                                        │
│          └── 对每 agent：if should_replan(events, candidate):     │
│                            planner.replan(profile, plan, ctx)     │
│                                │                                  │
│                                ▼                                  │
│                    StubReplanLLM.generate(prompt)                 │
│                      按 variant_name 分派 → JSON plan            │
│                                │                                  │
│                                ▼                                  │
│                    Planner._parse_plan → new PlanStep[]          │
│                                │                                  │
│                                ▼                                  │
│                    agent.runtime.plan = merged                    │
│                                                                   │
│   下一 tick: AgentRuntime.step() 读新 plan → 走新 destination    │
└──────────────────────────────────────────────────────────────────┘
        │
        ▼
Ledger entity.location_id changes
        │
        ▼
TickMetricsRecorder 捕获 end_of_day_location
        │
        ▼
RunMetrics.trajectory_deviation_m 反映变化
        │
        ▼
ContestReport 给出方向正确的 evidence_alignment
```

---

## StubReplanLLM Dispatch 表

| variant_name | Stub 响应 | 期望行为 |
|---|---|---|
| `hyperlocal_push` | JSON: 1 条 step 走向 `target_location` | agent trajectory 向 target 靠拢 |
| `global_distraction` | `"[]"` | Planner fallback 保持原 plan；trajectory 不变 |
| `shared_anchor` | JSON: 1 条 step 走向 community heuristic（park/plaza） | anchor 组 agent 聚集到 community location |
| `phone_friction` | `"[]"` | profile 改动生效在 DigitalProfile；replan 不直接改 plan |
| `catalyst_seeding` | `"[]"` | personality 改动影响 should_replan 阈值；plan 结构不变 |
| `baseline` / 未知 | `"[]"` | 无 variant 信号；零 replan |

**关键设计**：Stub **不解析 prompt 内容**；按构造时注入的 `variant_name`
分派。稳定、可测、与 prompt 演变解耦。

---

## CLI 用法

### 默认（零 LLM 成本）

```bash
python3 tools/run_variant_suite.py \
    --variants baseline,hyperlocal_push,global_distraction,phone_friction,shared_anchor,catalyst_seeding \
    --seeds 30 --num-days 14 --agents 100 \
    --mode publishable --phase-days 4,6,4 \
    --suite-name thesis_v1
```

### 真 LLM（Anthropic Haiku）

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python3 tools/run_variant_suite.py \
    --variants baseline,hyperlocal_push \
    --seeds 5 --num-days 7 --agents 20 \
    --mode publishable --use-real-llm \
    --suite-name real_llm_pilot
```

**成本警告**：14-day × 100-agent × 30-seed × 6-variant 下，每 agent
intervention phase 约触发 1-5 次 replan → ~50-200 × 30 seed × 5 variants
= **~30,000-60,000 LLM 调用**。按 Haiku 0.80 美元/百万 token、每调用
~1.5K token 算，单次完整 suite ≈ **$36-72 USD**。建议先用 stub 调通
pipeline 再开 `--use-real-llm`。Cost 控制是未来 `model-budget` change 的事。

---

## Metrics 观察信号

`run_variant_suite.py` 会把 replan 统计写入 `RunMetrics.extensions`：

```json
{
  "extensions": {
    "replan_count": 8,
    "replan_by_day": [0, 4, 4]
  }
}
```

可立即用来 sanity-check wiring 是否生效：
- `baseline.replan_count == 0` → feed 无注入 → 预期
- `hyperlocal_push.replan_count > 0` → 注入成功且 agents 被触发 → 预期
- `global_distraction.replan_count > 0` 但 trajectory_deviation_m 不降 →
  stub 返回 "[]" → Planner fallback → 预期

---

## 与已归档 capabilities 的关系

| Capability | Suite-wiring 用它什么 |
|---|---|
| `attention-channel` | `AttentionService.inject_feed_item` / `notifications_for` |
| `memory` | `MemoryService.process_tick(tr, agents, planner)` |
| `agent` | `Planner.replan` / `AgentRuntime.should_replan` |
| `policy-hack` | `VariantRunnerAdapter.attach_to(runner)` |
| `multi-day-run` | `MultiDayRunner.run_multi_day(on_day_start=...)` |
| `metrics` | `TickMetricsRecorder` + `build_run_metrics` + `RunMetrics.with_extensions` |

本 change **不改任何已归档 spec**；只是用 CLI 层把它们的公共 API 串起来。

---

## 已知限制

1. **Stub 对 shared_anchor 的 heuristic location 选择偏粗**：优先
   `park/plaza`；否则回退到 destinations[0]（= hyperlocal_push 默认 target）。
   真实 LLM 下会更细。
2. **Stub 不支持 variant-level 参数扫描**：例如 hyperlocal_push 的
   `daily_push_count=5` 与 `=20` 的区分需要 real LLM 或更复杂的 stub；本
   change 只证"推一条就有效"。
3. **Real-LLM 路径未做 cost / rate limit**：跑崩 API / 超配额自行处理。
4. **AttentionState 的 four-way allocation 仍未完整**：仅 phone_feed_proxy
   一项；physical_world / task / conversation 三项需 perception 层扩展。

---

## 下一步建议

1. 用当前 stub 跑一次 publishable suite（30 seed × 14 day × 6 variant ≈
   35-40 分钟），看 contest.json 的 alignment 是否从 inconclusive 转为
   consistent（主要在 hp / gd 对比）
2. 若 smoke 证据稳定，开 `validation-strategy` change（处理 LLM
   stereotype swap test、Google Popular Times 校准等 —— metrics 讨论中
   提到的 Q1/Q2 伦理 + LLM bias 审计）
3. 若想跑 real LLM，开 `model-budget` change（cost 追踪 + tiered
   haiku/sonnet 分派）
