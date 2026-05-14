## Why

`docs/audit/2026-05-12-deep-issues.md` 暴露：thesis 中心论断
"Attention-induced nearby blindness"（手机注意力 → 看不见邻居 → 不形成弱关系）
**在代码里根本没建模**。

具体证据：

1. **encounter detection 是纯地理 co-location** —— 同 location_id + 同 tick →
   encounter，**无 attention gate**。两人在 cafe 低头各刷手机，也是 encounter
2. **`phone_feed_proxy` 是推送频率代理** —— `delivered_notifications/(N×D×20)`，
   不是"agent 在看屏幕"
3. **实测 stub 路径** ：hp 推 18 次但 encounters byte-equal baseline (13758)；
   pf "减少手机吸力" 让 encounters 仅降 0.6%（13758→13679）
4. **thesis 论文核心**就是关于"看手机 vs 看邻居"的区分 —— 但模拟里**不区分**

publishable run 跑出来的结果会被审稿人 1-shot 问倒：
> "你们说 hyperlocal push 把注意力拉回邻居，但你们的 encounter 是纯物理 colocation，
> 推送增加只是改变了 plan 路线，不是真的'noticing' —— 你们的 weak_tie 增长来源
> 不是 thesis 机制而是路径效应。"

### 不修的代价

跑 D2 publishable 大概率得到"variant 效应 < 噪音"或"效应有但来源错位"。
论文无法 honestly 主张 thesis hypothesis 被验证。

## What Changes

### 新增 capability `attention-induced-noticing-gate`

- 每个 agent 携带 dynamic `phone_attention: float ∈ [0, 1.5]` 状态
  - baseline 从 `profile.digital.daily_screen_hours / 16h` 推断（持续屏幕占有率）
  - per-tick 自然衰减（`× 0.85`，half-life ≈ 4 tick = 20 分钟）
  - 收到 notification 时增 `+Δ`，Δ 由 (urgency × notification_responsiveness × openness) 决定
- `AttentionService` 暴露 `get_phone_attention(agent_id) → float`
- 新增 `EncounterNoticingService.noticed(a_attn, b_attn, rng) → bool`：
  - `noticing_prob = max(0, 1 − max(a_attn, b_attn)) × BASE_NOTICING_RATE`
  - BASE_NOTICING_RATE = 0.3（即使两 agent 都不刷手机，街上擦肩而过也只 ~30% 真"看到"）
- `memory.process_tick` 在调 `social_graph.record_encounter` 前 SHALL 通过 noticing
  gate；未 noticed 的 encounter 仍记入 `encounter_count_total`（地理 colocation），
  但 SHALL NOT 累入 `noticed_encounter_count` 也 SHALL NOT 触发 weak_tie 形成

### 新增 metrics

- `noticed_encounter_count_total` （weak_tie 形成的来源）
- `noticing_rate` = noticed / total（每变体诊断指标）

### 修改 weak_tie 形成语义

- `SocialGraphService.record_encounter` 拆为：
  - `record_physical_encounter(a, b, tick)` —— 记录但不增 strength（向后兼容）
  - `record_noticed_encounter(a, b, tick)` —— 增 strength → weak_tie 形成
- `memory.process_tick` 调 `record_physical_encounter` for all colocations，
  调 `record_noticed_encounter` only for noticed pairs

### Variant 效应通过新通道传导

- `phone_friction` → suppress notifications → 累积 phone_attention ↓ → noticing ↑ → encounter ↑（thesis 预期）
- `global_distraction` → push 50/day → phone_attention 飙升 → noticing ↓ → encounter ↓
- `hyperlocal_push` → push 18/day → phone_attention 中等 → noticing 略降，但**未来 spec**：push 内容 ABOUT push_location → 同 push_location 的 encounter 给 noticing 加 bonus（本 change 不实现，留作 §future）

### Non-goals

- 不实现 spatial noticing bonus（hp "推送对附近的 boost"）— 留下次 change
- 不改 perception pipeline / SubjectiveView
- 不改 dialogue（dialogue 仍只在 ai-town 路径触发）
- 不改 D2 publishable 协议；只让 variant 效应通过 thesis-mechanism 通道 surface

## Capabilities

### New Capabilities

- `attention-induced-noticing-gate`: phone_attention state + noticing probability
  + encounter gating（新 spec）

### Modified Capabilities

- `attention-channel`: AttentionService 持有 per-agent phone_attention state；
  deliver_feed_item 时增 attention；每 tick decay
- `social-graph`: record_encounter → physical / noticed 二分；weak_tie 形成
  来源 SHALL 是 noticed
- `metrics`: RunMetrics 新增 `noticed_encounter_count`, `noticing_rate` 字段

## Impact

- **代码**：
  - 新增 `synthetic_socio_wind_tunnel/attention/noticing.py`（noticing gate + state）
  - 修改 `attention/service.py`（per-agent phone_attention state + decay tick hook）
  - 修改 `social_graph/service.py`（split physical/noticed encounter）
  - 修改 `memory/service.py`（process_tick 调用 noticing gate）
  - 修改 `metrics/models.py`、`metrics/factory.py`（新字段）
- **测试**：
  - 新 `tests/test_attention_noticing.py`（gate 概率、decay、variant 效应）
  - 修改 `tests/test_social_graph.py`（保留旧 record_encounter 行为 + 新接口）
  - 修改 `tests/test_variant_smoke_e2e.py`（新断言：pf.noticed > baseline.noticed > gd.noticed）
- **expected outcome**:
  - hp/gd/pf 的 noticed_encounter / weak_tie 出现可测差异
  - thesis hypothesis "phone attention causes blindness" 在数据中可观测
