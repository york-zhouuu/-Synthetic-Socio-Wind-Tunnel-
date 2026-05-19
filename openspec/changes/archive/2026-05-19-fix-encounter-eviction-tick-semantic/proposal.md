## Why

2026-05-20 04:00 实测 publishable resume 暴露 `enforce-worker-rss-cap`
+ `prune-before-snapshot-write` 引入的 encounter eviction **每次都把全
部 encounter event 清空**——背后是 tick 字段的两种语义在 caller 和
callee 之间错配。

**精确根因**：

- `orchestrator/service.py:260` 主 tick 循环 `for tick_index in
  range(num_ticks)` 其中 `num_ticks = 288` per day → `tick_index ∈
  [0, 287]` **per-day**
- `MemoryService.process_tick` 把这个 per-day tick 写进
  `MemoryEvent.tick` 字段
- `multi_day.py` 计算 cutoff: `(day_index - grace) * ticks_per_day`
  → 这是 **global** scale (day 12 grace 2 → 2880)
- `MemoryStore.evict_cold_encounter_events(before_tick)` 比较
  `if ev.kind == "encounter" and ev.tick < before_tick`
- `ev.tick ∈ [0, 287] < 2880` **永远成立** → 每次 eviction 把全部
  encounter event 清空（action / life_history / shared_memory 因为
  filter 限定 `kind=="encounter"` 不受影响）

**研究层后果**：

encounter event 是 thesis 主线 dependent variable（agent 是否
"recognize 邻居" → social tie 累积）。bug 让 1000 agent 全部得"严重
健忘症"：物理 encounter 检测出来了（WAL `encounter_count` 1500/tick）
但记忆里 1 小时就清空。任何依赖 encounter 累积的 conclusion 都不可信
（认识邻居 / tie 强度 / "看不见的邻居"现象观察）。

**为什么测试漏掉**：

- `tests/test_memory_store_encounter_eviction.py` 用 hand-crafted
  events with explicit small tick (0, 10, 200) + explicit cutoff。
  测的是 eviction **机制**（"if tick < cutoff → 删"），不测 **tick
  语义是否一致**。
- 同 2026-05-20 撞到的另外两个 bug 一个模式：mock 关键测量值 / API
  契约 pass，integration 时 caller-callee 语义错配 → 现场死。

## What Changes

- **改 `MemoryStore.evict_cold_encounter_events`** signature 从
  `before_tick: int` → `before_day_index: int`，内部 filter 改成
  `if ev.kind == "encounter" and ev.day_index < before_day_index`。
- **改 `MemoryService.evict_cold_encounter_events_across_agents`**
  同步 signature。
- **改 `MultiDayRunner` 2 个调用点**（day_end hook 和 snapshot
  pre-write）把 `before_tick=cutoff_tick` 换成
  `before_day_index=max(0, day_index - grace_days)`。
- **新 e2e test**：跑真 dev smoke 50 agent × 4 day grace=2，**直接
  从 final snapshot 的 `memory_store_state` 读 encounter 数量**，
  断言 day 3 时 day 0-1 encounter 已 evicted 但 day 2-3 encounter
  存在（**不是 0**）。这种 test 才会捕捉今天这个 bug。
- 既有 6 个 mock-based eviction unit test 配套更新 signature。

NOT in scope:
- 不改 `MemoryEvent.tick` 字段语义（保持 per-day，跟其它 kind 一致）
- 不重命名 `tick` → `tick_in_day`（更大重构，留 backlog）
- 不动 encounter 检测路径 / WAL `encounter_count`

## Capabilities

### Modified Capabilities

- `memory-event-eviction`: eviction filter contract 改 — 不再按
  `before_tick` (混淆维度) 比较 `MemoryEvent.tick`，改按
  `before_day_index` 比较 `MemoryEvent.day_index`。语义清晰，符合
  cold-prune 的人类直觉 ("删 grace_days 之前的")。

## Impact

**Affected code**:
- `synthetic_socio_wind_tunnel/memory/store.py`
  `evict_cold_encounter_events`（signature + filter）
- `synthetic_socio_wind_tunnel/memory/service.py`
  `evict_cold_encounter_events_across_agents`（signature）
- `synthetic_socio_wind_tunnel/orchestrator/multi_day.py`
  2 调用点（day_end hook + `_write_snapshot` pre-write hook）

**Affected behavior (positive)**:
- encounter event 在 grace window 内不再被错杀
- agent 真有 "recognize 邻居" 的 memory 累积
- LLM context 看得到 historical encounter，决策真实
- thesis dependent variable (encounter density / tie 强度) 在数据
  里可以被正确量化

**Affected behavior (negative)**:
- encounter event 数量大涨 → snapshot file 也会涨。但 `grace=2` 仍
  然 bounded（最多 2 day 的 encounter，比无 evict 14 day 累积小很多）
- ~1500 encounter/tick × 288 tick × 2 day × 2 agent (双向) =
  ~1.7M encounter events 在 memory_store 稳态。约 100-300MB。
  publishable resume RAM 峰值可能从 3-6GB 变到 4-8GB —— 仍远低
  10GB cap

**Test impact**:
- 6 个既有 eviction unit test 改 signature
- 2 个新 e2e integration test 真跑 dev smoke 验证 encounter 留存
- 既有 1872 regression baseline 不动

**Migration**:
- 改完即生效，下次 spawn 立即受益
- 已写的 lean snapshot 不受影响（encounter 已经 0，重新跑会重新累积）
