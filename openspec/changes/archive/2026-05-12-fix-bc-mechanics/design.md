## Context

A1-A5 已修 + B/C 全 disclose。User 决定再修 B/C 中"可实现"的 5 个 (B1/B4/B5/B6/C2)，
留 5 个 (B2/B3/C1/C3/C4/C5) 给 future work。

## Goals / Non-Goals

**Goals:**
1. B1 work_mode 反 COVID 异常
2. B4 hp/gd push 等量
3. B5 attention fatigue
4. B6 transit drive-by discount
5. C2 child movement restriction
6. 262+ regression test PASS

**Non-Goals:**
- 不动 LLM prompt template
- 不重 calibration walking_speed / BASE_NOTICING_RATE
- 不跑 1000-agent capacity test

## Decisions

### D1 · B1 work_mode steady-state vs ABS-raw

**选 steady-state**: ABS 2021 in Sydney Delta lockdown，53% remote 是 COVID
异常。Lane Cove 稳态 ~18% remote (per ABS 2016 + post-2022 surveys)。

权衡：偏离 ABS 2021 → calibration test 上 work_mode chi² 会有较大 deviation。
但 thesis 测的是 "通勤者 vs 居家者" 接触社区的差异——COVID 异常会扭曲此对照。
publishable 报告需明确 "we de-anomalized work_mode from raw 2021 to estimated
steady-state for thesis relevance"。

### D2 · B4 push 等量 5/day

5/day 是真实社交 app 推送频率中位数（Instagram/TikTok ~3-7 push/day）。
等量后 paired-mirror 真测"方向"：hp 推近 cafe vs gd 推远 distraction。

### D3 · B5 fatigue half-life N=8

5 push/day 配合 N=8 half-life：当日第 1 push delta 100% / 第 5 ~64% /
第 10 ~42%。8 是"city dwellers desensitize at ~1/2-day mark" 直觉。

### D4 · B6 transit penalty 设计

`transit_factor = 1 / (1 + max(a_moves, b_moves) / 5)`:
- 0 moves (settled): factor = 1.0 → no penalty
- 5 moves (slow walker): factor = 0.5 → mild penalty
- 25 moves (heavy driver): factor = 0.17 → strong penalty

penalty 通过 effective_attention 注入：
`effective_a = a_attn + (1 - factor) × 0.5`. 此设计复用现有 noticing
formula 无需重写公式。

### D5 · C2 儿童 destination 限制

简化规则：age < 6 → 全 stay home；age 6-12 → 学校通勤保留，其他全 home。
不区分有家长接送（C2.next phase 留 household coupling change）。

### D6 · B2/B3/C1/C3/C4/C5 不修原因

- **B2 walking_speed 80/150/250/280**: 已是 first-order defensible 值 (80=5km/h walking pace, 250=15km/h urban driving)。empirical refinement 需 Sydney commute survey 实测，留 future
- **B3 BASE_NOTICING_RATE=0.3**: 已是定性合理值 (ideal-condition street co-presence ~30%)。empirical calibration 需 face validity 问卷
- **C1 dialogue ai-town only**: stub 路径无 LLM 是架构选择；publishable 用 ai-town 全程
- **C3 per-trip mode**: 简化假设 (1-车户 fixed driving) 与 Sydney 实际接近 (most 1-car households drive for >85% trips)
- **C4 LLM 不见 in-flight**: prompt 改动 valuable 未定；future change
- **C5 1000-agent wall time**: 需实跑测；publishable 前再加 capacity audit

## Risks / Trade-offs

- **[B1 偏 ABS 校准]** publishable run 的 work_mode chi² calibration 会 fail
  strict；需 best-effort tier
- **[B4 hp 推送变 5 倍]** 之前 1/day 改 5/day 让 hp signal 大幅放大，可能
  超过 gd 的 5/day。但这是好事——thesis 现在能在等量下做方向对照
- **[B5 fatigue 让 push 效果变小]** delta 减小让 phone_attention 累积变慢，
  noticing rate 提升——pf signal 应更显著 (与 thesis 一致)
- **[B6 transit penalty 减 encounter]** 总 encounter 数会下降；thesis 方向
  不变，但绝对值更小
- **[C2 儿童 stay home]** 整城 ~13% 14 岁以下 + 6 岁以下完全 stay → encounter
  density 下降 ~5-8%；预期，更真实

## Migration Plan

1. B1 work_mode_distribution 替换 (population.py)
2. B4 daily_push_count = 5 in hp + gd; hp radius 1000m
3. B5 compute_notification_delta + AttentionService counter
4. B6 noticing _is_encounter_noticed + memory loop pass movement counts
5. C2 _restrict_to_child_destinations in scripted_plan
6. Test (262 PASS)
7. limitations-ethics.md 更新 fix-vs-defer 状态

## Open Questions

- B1 work_mode 数值（59.4/18/12.7/9.9）是估计；publishable 前可二次复核
- B6 transit threshold 5 segments 是直觉；可调
- C2 boundary 6-13 是直觉；ABS school age start 5 in NSW
