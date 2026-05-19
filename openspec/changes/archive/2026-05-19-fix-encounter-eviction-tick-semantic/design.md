## Context

2026-05-20 04:00 实测 publishable resume 暴露 encounter eviction
**每次都把全部 encounter event 清空** — root cause 是 `tick` 字段在
caller 和 callee 之间维度错配（caller 用 global tick 算 cutoff，
event store 是 per-day tick）。详细 trace 见 proposal.md 和 backlog 1.16。

## Goals / Non-Goals

**Goals:**
- encounter event 在 grace window 内正确留存
- API 改动最小化（不 rename `tick` 字段）
- 加 integration test 真读 artifact 验证 — 这次别再被 mock 漏

**Non-Goals:**
- 不重命名 `MemoryEvent.tick` → `tick_in_day`（更大重构，留 backlog）
- 不改 encounter 检测路径
- 不动其它 kind 的 eviction 逻辑（其它 kind 当前没 eviction）

## Decisions

### D1: 用 `day_index` 比较，不用 derived `tick_global`

**选项**:
- (A) MemoryEvent.tick 改为 tick_global — 改 caller (process_tick)
- (B) Eviction signature 改为 `before_day_index` — 改 callee
- (C) Eviction 内部 `ev.day_index * 288 + ev.tick` 算 global

**选定: (B)** `before_day_index`

理由：
- (A) 改 event 写入语义影响下游 (retrieve / snapshot serialization)
- (C) 需要 `ticks_per_day` 参数 + 假设固定，hidden assumption
- (B) signature 明确 (`day_index` vs `tick`) — caller 一眼能看出
  哪个维度的对比；callee 不依赖 ticks_per_day
- caller 改动也最小：`cutoff_tick = (day-grace)*288` 改成
  `cutoff_day = max(0, day - grace)` —— 更接近 cold-prune 人类直觉

### D2: 既有 mock-based unit test 改 signature，不删

6 个既有 test 仍然有价值：测 eviction 机制（哪些被删、哪些保留、
reverse-index 重建等）。只是 signature 从 `before_tick=N` 换成
`before_day_index=N`，行为不变（因为这些 test 的 events 都有
explicit day_index field）。

### D3: 新加 1 个 integration test 真跑 dev smoke

测试名: `test_encounter_events_present_in_grace_window_real_smoke`

跑 50 agent × 4 day dev smoke，结束后读 `seed_42_tick_final.snapshot.json`
的 `memory_store_state.agent_events`，aggregate encounter event 总数。
断言 > 0 且分布合理（最近 2 day 应该有 encounter）。

这次 test 跟之前的不同：
- 不 mock — 真跑
- 读真实 artifact (snapshot.json) — 不 inspect in-memory state
- 断言 product-level invariant ("encounter should accumulate") —
  不只测 API mechanic

这种 test 就是 backlog 1.15 preflight 的雏形 — 推广到所有重要 capability
是真正能止血的方法。

### D4: 不引入新 ABI break

`before_tick` 参数全删，改成 `before_day_index`。任何外部调用方现在
就改了（没有，这俩 API 是 internal）。

## Risks / Trade-offs

**[R1] memory_store 大小回升**
→ encounter event 不再被错杀。grace=2 → 最多 2 day 数据。1500
  encounter/tick × 288 × 2 × 2 (双向) = ~1.7M event。每个 event
  ~150-300 字节 = 250-500 MB in memory_store_state. 加上其它
  kind ~50 MB. publishable snapshot 预计从当前 74-82MB 长到
  600MB-1GB。仍可控且远低于 5.6GB 老 snapshot。

**[R2] resume RAM 峰值回升**
→ ~600MB snapshot Python 反序列化 5-10× = 3-6GB peak. 仍低于
  10GB cap。可接受。

**[R3] 错过其它 tick 语义错配点**
→ encounter eviction 修了，但其它 kind / 其它 module 可能有类似
  错配。Backlog 1.17 (新) 跟踪："tick / tick_in_day / tick_global"
  全局排查。

**[R4] grace_days=2 的语义微妙变化**
→ 旧 (buggy): "evict 所有 encounter" — 实际 grace_days 形同虚设
→ 新 (correct): "evict day_index < (current_day - 2)" — 真正
  grace 2 day. 行为更符合 spec 意图。

## Migration

1. Worker restart 即生效
2. Old snapshot 仍能 load（encounter event 字段是 backward-compat,
   from_snapshot_state 不变）
3. 没必要 rollback flag — 这是 bug fix 不是 behavior change

## Open Questions

- (闭合) day_index 比 tick_global 哪个好？答：D1 选 day_index
- (闭合) 删 vs 改既有 test？答：D2 改 signature 保留
- (闭合) integration test 在哪一层？答：D3 e2e dev smoke 读真 artifact
