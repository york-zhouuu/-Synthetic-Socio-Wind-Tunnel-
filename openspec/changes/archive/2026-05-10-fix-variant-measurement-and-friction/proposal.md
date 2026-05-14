## Why

`docs/audit/2026-05-09-bug-hunt.md` 排查发现 14-day publishable suite 跑出来的"thesis null 结果"基本上是测量装配链路的 bug 制造的，而不是 thesis 失败：

- **`traj_dev_m` 在 100 个 agent 上取 median**，10 个 protag 的真信号被 90 个 scripted agent 的固定路径稀释成噪音底，导致 hp seed42 = gd seed42 到 12 位小数完全相等。
- **`StubReplanLLM` 给 `global_distraction` 永远返回 `<plan></plan>`** → Planner 退回 `deep_copy(unchanged)` → gd 与 baseline 的 encounter / weak_tie **byte-identical**。replan_count 显示触发了 44–105 次 replan，但全是"空 replan"。
- **`phone_friction` 修改 `profile.digital`，但该字段在 movement 链路上没有下游 reader**（仅 perception filter / feed bias suppression 用），→ pf 与 baseline 全字段 byte-identical。
- **`phone_friction` 的 primary metric 选成 `attention.phone_feed_proxy`**，pf 和 baseline 都没注入 feed → 都是 0 → 永远 inconclusive (degenerate metric)。

这四个 blocker 一起把"打碎附近性盲区"这个 thesis 的可观测信号洗掉了。在不修这些 bug 的情况下跑 30 seed publishable run 就是浪费配额。本 change 把 measurement 与 variant 操作语义修到能让 thesis 信号被看见。

## What Changes

- **MODIFIED**：`metrics::trajectory_deviation_m` 计算口径——只对接到 push 的 target_agent 子集取 median，不再被 90 个 scripted agent 稀释。同时输出 `trajectory_deviation_m_all` 作为 sanity 对照。
- **MODIFIED**：`policy-hack::phone_friction` variant 的操作语义——除了改 `profile.digital`，必须在 intervention 期通过 `attention_service.inject_feed_item` 注入 friction-trigger event（source = `phone_friction_nudge`），让 memory → replan 链路真正触发，制造 plan-level 行为差异。
- **MODIFIED**：`policy-hack::phone_friction` primary metric——改成 `encounter.per_day_median`（friction 应提升的指标），不再用 degenerate 的 `phone_feed_proxy`。
- **MODIFIED**：`suite-wiring::StubReplanLLM` 对 `global_distraction` 的 dispatch——改为返回真的会消耗 plan 时间的 distraction step（agent 在原地多停留 / 改去与 hp target 无关的远端 location），让 gd 在 stub 路径下也有可观测的行为差异。
- **MODIFIED**：`suite-wiring::replan_count` 语义——只在 `new_future_steps` 真正非空（即 plan 真的被改）时才计数，否则计入 `replan_no_op_count`。
- **MODIFIED**：`suite-wiring::reproducibility_lock.phase_config` 的字符串索引 bug 修复——split 成 int 再写入。
- **NON-GOAL**：本 change **不**重跑 14-day × 30 seed publishable suite，只跑 1 seed × 4 variant smoke 验证修复。30 seed 留给下一个 change。
- **NON-GOAL**：本 change **不**重设计 hyperlocal_push variant，hp 已经在工作，只是被 metric 稀释了。
- **NON-GOAL**：本 change **不**触碰 ai-town port / Gemini async client / dialogue pipeline——那些已经是稳定基线。

## Capabilities

### New Capabilities

无。本 change 是对现有能力的修复 + 操作语义收紧。

### Modified Capabilities

- `metrics`: `trajectory_deviation_m` 的计算口径改为 push-target subset；新增 `trajectory_deviation_m_all` 作为对照字段。
- `policy-hack`: `phone_friction` 必须通过 attention_service 注入 trigger，让 friction 走 memory → replan 链路；primary metric 改为 `encounter.per_day_median`。
- `suite-wiring`: `StubReplanLLM` 对 `global_distraction` 返回真行为变化的 stub plan；`replan_count` 拆分为 `replan_count`（真改 plan）+ `replan_no_op_count`（空 replan）；`reproducibility_lock.phase_config` 修字符串索引 bug。

## Impact

**代码**：
- `synthetic_socio_wind_tunnel/metrics/factory.py` — `_compute_trajectory_deviation_m` 改口径
- `synthetic_socio_wind_tunnel/metrics/models.py` — `RunMetrics` 增加 `trajectory_deviation_m_all` 字段
- `synthetic_socio_wind_tunnel/policy_hack/variants/phone_friction.py` — `apply_intervention_start` 增加 feed_item 注入；`primary_metric` 字段
- `synthetic_socio_wind_tunnel/policy_hack/base.py` 或 spec 内的 metric mapping — pf 默认 primary metric
- `tools/suite_stub_llm.py::StubReplanLLM` — gd dispatch 改为非空 plan
- `synthetic_socio_wind_tunnel/memory/service.py::process_tick` — 检测空 replan 不计数
- `synthetic_socio_wind_tunnel/metrics/recorder.py`（或 factory）— 增加 `replan_no_op_count`
- `tools/run_variant_suite.py` — `phase_config` 字符串索引 bug 修复

**测试**：
- 新增 `tests/test_phone_friction_behavioral.py` 验证 friction 真触发了 ≥1 个 agent 的 plan 变化
- 新增 `tests/test_traj_dev_protag_only.py` 验证 metric 在 protag-only 子集上的计算
- 新增 `tests/test_global_distraction_stub_dispatch.py` 验证 gd stub 返回非空 plan
- 修改 `tests/test_suite_stub_llm.py` 反映新的 gd dispatch 语义

**API / 契约**：
- `RunMetrics` 增加可选字段 `trajectory_deviation_m_all`，老 reader 兼容（可选）
- `RunMetrics.extensions.replan_count` 语义收紧；下游消费者（report builder）需要更新

**外部影响**：当前 14-day suite 数据不再作为 thesis 结论依据；下一个 change 会基于修复后跑 30 seed 出真实结论。
