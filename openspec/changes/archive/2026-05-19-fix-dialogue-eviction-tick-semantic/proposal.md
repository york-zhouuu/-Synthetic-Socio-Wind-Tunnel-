## Why

2026-05-20 项目全量审查发现 `DialogueService.evict_old_dialogues` 跟
encounter eviction (just fixed) **完全相同的 tick semantic bug** —
caller-callee 不同维度的 tick 比较，导致所有 ended dialogue 立刻被
demote 成 summary（丢掉具体 messages list）。

精确根因：

- `multi_day.py:666-668` caller 计算 cutoff: `(day_index - grace_days)
  * ticks_per_day` → **global tick scale** (e.g. day 12 grace 2 → 2880)
- `dialogue_service.py:492` filter: `if d.ended_tick >= before_tick:
  continue # too recent`
- `d.ended_tick` 是 `tick_result.tick_index` 派生 → **per-day** (0-287)
- `d.ended_tick (max 287) >= before_tick (2880+)` **永远 False** →
  "too recent" 路径不走 → **每个 ended dialogue 每次 day_end 立刻
  demote**

产品影响：grace_days 等于失效——任何对话只要 ended 就立刻被压缩成
summary，丢掉具体 message contents。论文要分析 "对话内容深度 / push
之后的对话是否更具体地谈到附近事件"，**没有 message 原文可用**，
只剩 message_count 这种粗粒度 metric。

类比：研究朋友怎么变成朋友，每次他们见完面立刻撕掉聊天记录，只留
"见过 5 分钟" 这种 metadata。

## What Changes

- `DialogueService.evict_old_dialogues(before_tick)` → 改 signature
  `evict_old_dialogues(before_day_index)`
- filter `d.ended_tick >= before_tick` → 加 `day_index` 字段对比
- 改 caller (`multi_day.py:666-672`) 传 `before_day_index=max(0,
  day_index - grace_days)`
- 新加 integration test：dev smoke 真跑 → 读 final snapshot →
  断言 grace window 内的 dialogue messages 仍存在
- 更新既有 dialogue eviction unit tests signature

NOT in scope:
- 不改 dialogue 结束逻辑 (`_end` method 仍 receive per-day tick)
- 不改 DialogueSummary schema
- 不动 active dialogue handling

## Capabilities

### Modified Capabilities

- `social-downstream-conversation` (或 dialogue-related capability):
  eviction filter contract changed from `before_tick` (global,
  mismatched dimension) to `before_day_index`.

## Impact

**Affected code**:
- `synthetic_socio_wind_tunnel/conversation/dialogue_service.py`
  (`evict_old_dialogues` + `Dialogue` may need `day_index` field)
- `synthetic_socio_wind_tunnel/orchestrator/multi_day.py:666-672`
  (caller updated)
- 既有 dialogue tests update

**Affected behavior (positive)**:
- ended dialogues 在 grace window 内保留完整 message list
- 论文 dialogue narrative section 有素材可用

**Affected behavior (negative)**:
- DialogueService size grows ~2 days of dialogues 不再立刻压缩
- 估每 cell +50MB at publishable scale (200 active dialogues × ~30
  messages × ~300 chars) — 远低于 RSS cap

**Test impact**: 1 subprocess e2e test (verifies real artifact) +
update 8 existing unit tests for new signature.
