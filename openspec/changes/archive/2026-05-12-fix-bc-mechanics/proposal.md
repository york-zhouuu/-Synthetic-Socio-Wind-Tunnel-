## Why

`docs/audit/2026-05-12-deep-issues.md` 的 B/C 类问题原本预定 "disclose 即可"，
但 user 决定一并修。本 change 把可实现的 5 个修了，剩余 5 个保留 disclose（empirical
calibration / architectural changes 留作 future work）。

## What Changes

### B1 · work_mode 反 COVID anomaly

ABS 2021 在 Sydney Delta lockdown 期间采集，`remote=52.7%` 是异常。修后
切换到 steady-state 估计 (commute=59.4% / remote=18% / shift=12.7% / nonworking=9.9%)。
publishable 报告 SHALL disclose 这个 de-anomaly 选择。

### B4 · 推送量等量

`hyperlocal_push.daily_push_count` 从 1 改为 **5**；
`global_distraction.daily_push_count` 从 20 改为 **5**。两 variant 每天每
recipient 等量推 5 条，把 paired-mirror 设计从"频率混方向"还原为单纯方向对照。
同时 `hyperlocal_push.hyperlocal_radius_m` 从 500m 改 **1000m** 对齐
CLAUDE.md 关键参数。

### B5 · Attention fatigue / desensitization

`compute_notification_delta(...)` 加 `notifications_received_today: int = 0`
参数。delta 乘 `exp(-ln(2) × n / 8)` —— 当日第 8 条 push 的 attention 增量
只有第 1 条的 50%。`AttentionService` 加 `_notifications_today` 计数器 +
`reset_daily_counters()` 在 day 边界清零。

### B6 · Transit drive-by discount

`memory._is_encounter_noticed(..., a_movement_count, b_movement_count)` 新参数。
任一 agent 单 tick 内 >5 segments → effective_attention 加 `(1 - transit_factor) × 0.5`
penalty，noticing 概率折扣。配合 `tick_result.movement_traces` 实时计算每
agent 当 tick 移动段数。

### C2 · 儿童 movement restriction

`build_scripted_plan` 调用 `_restrict_to_child_destinations` 后处理 child
agents:

- age < 6: 所有 step 转 `stay home`
- age 6-12: 保留 commute → school；其他 errand/leisure/outing → home

### B/C 仍 disclose（不修）

- **B2** walking speed calibration (80/150/250/280 m/min): 缺实证数据
- **B3** BASE_NOTICING_RATE=0.3: 缺 face validity 实证
- **C1** dialogue 只在 ai-town path: 架构限制
- **C3** per-trip mode: 简化合理（real 1-车户也大致 fixed）
- **C4** LLM 不见 in-flight state: prompt template 改动；valore 未定
- **C5** 1000-agent wall time: 需实跑测；publishable 前补 capacity test

### Non-goals

- 不重新校准 walking speed / NOTICING_RATE
- 不动 LLM prompt template
- 不跑 capacity test (留 publishable 前)

## Capabilities

### Modified Capabilities

- `agent`: LANE_COVE_PROFILE.work_mode_distribution 反 COVID-anomaly；scripted_plan 加儿童 restriction
- `attention-channel`: compute_notification_delta 加 fatigue；AttentionService 加 daily counter
- `attention-induced-noticing-gate`: noticing gate 加 transit penalty
- `policy-hack`: hp / gd daily_push_count 等量；hp radius 对齐 1000m

## Impact

- 代码：population.py / scripted_plan.py / attention/noticing.py / attention/service.py / memory/service.py / policy_hack/variants/{hyperlocal_push,global_distraction}.py
- 测试: 262 passed regression (含 scripted_plan / orchestrator / agent / attention / memory / variant_smoke / social_graph_integration)
- 文档: limitations-ethics.md 已 disclose 全 B/C 类，本 change 后**A1-A5 全 fix，B1/B4/B5/B6 fix，C2 fix；B2/B3/C1/C3/C4/C5 仍 disclose**
