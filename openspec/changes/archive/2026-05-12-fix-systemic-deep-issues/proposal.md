## Why

`docs/audit/2026-05-12-deep-issues.md` 跑完前 5 个 thesis-critical change 后
做的"超越代码 bug 层"系统盘点暴露 18 个潜在问题（A1-A5 高风险 / B1-B8 中风险
/ C1-C5 低风险）。

本 change 修高风险 A 类全部 5 个，并把 B 类 + C 类正式 disclose 在
`docs/limitations-ethics.md`。这是 publishable D2 前最后一波"非 bug 但
thesis 解读层面会被审稿人拆穿"的问题。

## What Changes

### A1 · ABS Lane Cove 家庭组成校准

`LANE_COVE_PROFILE.family_composition_distribution` 之前 `lone_person: 0.0` /
`group_household: 0.0` 是占位符——把 19% lone person + 5% group household
"塞"给了 `couple_kids_under_15`，让其飙到 49%（实际 ABS ~22%）。修后:

```python
{
    "lone_person": 0.1903,
    "couple_no_kids": 0.2666,
    "couple_kids_under_15": 0.2200,  # ↓ from 0.4923
    "couple_kids_15plus": 0.1500,
    "one_parent_family": 0.0945,
    "group_household": 0.0480,
    "other": 0.0306,
}
```

### A2 · `--num-protagonists` CLI flag

90% scripted agent 不响应 push → variant 效应被稀释。新增 CLI 参数让
publishable run 配置 ≥50% Sonnet protag。Default 仍 10% 保 dev 速度。

### A3 · Polygon-size noticing 折扣

`noticing_prob(a_attn, b_attn, polygon_extent_m=...)` 加空间因子：

```python
spatial_factor = min(1.0, VISUAL_RANGE_M / polygon_extent_m)  # 50m / extent
```

`memory.process_tick` 解析共享 location 的 polygon extent 传入。Mowbray Park
（1.4km）的 noticing 折扣到 ~3.6%——避免"公园里一头一尾算 encounter"。

### A4 · Tie 30-day half-life decay

`SocialGraphService.effective_strength(tie, now_tick)` 用指数衰减：

```python
days_since = (now_tick - tie.last_seen_tick) / 288
effective = tie.strength × exp(-ln(2) × days_since / 30)
```

新增 `weak_ties_decayed(agent_id, now_tick)` / `strong_ties_decayed(...)` 助手。
旧 `tie.strength` immutable 不变；decay 只在 read 时算（callers opt-in）。

### A5 · Joint smoke 验证

跑 1-day × 4 variants × `--use-aitown --aitown-provider stub` smoke 验证
walking_budget + ai-town path 不打架。已 PASS (eff=2412 baseline)。

### B/C 类 disclose

B1 (ABS COVID) / B2 (walking speed calibration) / B3 (BASE_NOTICING_RATE 0.3) /
B4 (hp/gd push 量不对等) / B5 (无 fatigue) / B6 (drive-by 4-10%) / B7 (encounter
geographic) / B8 (traj_dev / building target) + C1-C5 全写入
`docs/limitations-ethics.md` 第九节。

### Non-goals

- 不重新校准 walking_speed / BASE_NOTICING_RATE 数值（属 B 类 future work）
- 不实现 attention fatigue（B5 future）
- 不实现 intra-polygon position（B7 future）
- 不动 hp/gd 推送量参数（B4 留待 publishable 协议讨论）

## Capabilities

### Modified Capabilities

- `agent`: `LANE_COVE_PROFILE.family_composition_distribution` 校准
- `attention-induced-noticing-gate`: `noticing_prob` 加 polygon_extent_m 参数
- `social-graph`: 新增 `effective_strength` + decayed-ties helpers
- `suite-wiring`: 新增 `--num-protagonists` CLI

## Impact

- 代码:
  - `agent/population.py` (LANE_COVE_PROFILE 校准)
  - `attention/noticing.py` (noticing_prob 加 polygon_extent_m)
  - `memory/service.py` (_is_encounter_noticed 传 shared_location_id)
  - `social_graph/service.py` (effective_strength + decayed-ties)
  - `tools/run_variant_suite.py` (--num-protagonists CLI)
- 文档:
  - `docs/limitations-ethics.md` 第九节 A/B/C 系统局限
- 测试: 现 90 个相关 test 不 regress（已验证）
- 数据: 旧 archive 实验数据**不再可对比**——A1 改 distribution 影响 RNG 序列；
  A3/A4 影响 weak_tie 计数。Publishable 前再跑一次 D1' 作为新 baseline。
