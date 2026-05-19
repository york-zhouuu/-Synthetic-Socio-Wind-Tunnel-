# memory-event-eviction Specification

## Purpose
TBD - created by archiving change enforce-worker-rss-cap. Update Purpose after archive.
## Requirements
### Requirement: MemoryStore 必须支持 cold prune encounter events

`MemoryStore` SHALL 提供 `evict_cold_encounter_events(before_tick: int) -> int`
方法，删除满足以下条件的 events：

- `kind == "encounter"`
- `tick < before_tick`

其它 kind 的 events SHALL NOT 被本方法触及（不动 life_history / action /
reflection / conversation / daily_summary / shared_memory / notification /
observation / speech / task_received）。

返回值：本次 evict 的 event 数。

实现 SHALL 同时清理依赖 events 列表的内部反向索引（若有，比如
by-kind 或 by-day 索引）。

#### Scenario: evict 只删 encounter events
- **WHEN** MemoryStore 含 5 个 events: [encounter@tick10, action@tick10,
  encounter@tick200, reflection@tick200, encounter@tick300]，调
  `evict_cold_encounter_events(before_tick=150)`
- **THEN** 返回 1（只第一个 encounter 被删）；store 剩 4 个 events；
  action 和 reflection SHALL 仍存在；后两个 encounter SHALL 仍存在

#### Scenario: 全 evict 后 store 合法
- **WHEN** store 全是 encounter events 且全部 tick < before_tick
- **THEN** 全删；store.all() == [] 但 store 可继续 append；
  事件总数 == 0 不抛

#### Scenario: 空 store evict no-op
- **WHEN** 空 MemoryStore 调 evict
- **THEN** 返回 0；不抛

### Requirement: MemoryService 必须暴露 cross-agent eviction

`MemoryService` SHALL 提供 `evict_cold_encounter_events_across_agents(before_tick: int) -> int` 方法，
遍历所有 agent stores 调用各自 `evict_cold_encounter_events`，累加返回
总 evict 数。

操作 SHALL 是 idempotent：同 before_tick 第二次调返回 0。

#### Scenario: 跨 agent evict 累计
- **WHEN** 3 agent stores 各含 (encounter@tick10, encounter@tick200);
  调 `evict_cold_encounter_events_across_agents(before_tick=100)`
- **THEN** 返回 3 (3 agent × 1 evict each)；剩余 events 全 tick=200

#### Scenario: 二次调用 idempotent
- **WHEN** 同 before_tick 第二次调
- **THEN** 返回 0；store state 不变

### Requirement: MultiDayRunner 必须在 day_end 触发 cold prune

`MultiDayRunner.run_multi_day` 的 day_end 内置 hook 链 SHALL 调用
`memory_service.evict_cold_encounter_events_across_agents(before_tick)`，
其中 `before_tick = max(0, day_index - grace_days) * ticks_per_day`，
grace_days 默认 2，可通过 env `MEMORY_EVENT_EVICT_GRACE_DAYS` 覆盖。

evict 数 SHALL 进 DayRunSummary 新字段 `evicted_encounter_count`（向后
兼容默认 0）。

#### Scenario: day 5 时 evict day < 3 的 encounter
- **WHEN** 跑到 day_index=5，grace_days=2，ticks_per_day=288
- **THEN** evict 调用 before_tick=3*288=864；DayRunSummary[5].
  evicted_encounter_count >= 0（实际数量取决于 simulation）

#### Scenario: 早期 day_index < grace_days 时 no-op
- **WHEN** day_index=1，grace_days=2 → before_tick=max(0, -1)*288=0
- **THEN** evict_cold_encounter_events_across_agents(before_tick=0)
  返回 0；no-op

### Requirement: snapshot round-trip 不携带 evicted events

snapshot serialize 后 evicted events SHALL NOT 出现在 snapshot JSON。
resume from snapshot 后 store.all() SHALL NOT 含 evicted events。

#### Scenario: snapshot + resume 不还原 evicted
- **WHEN** worker 跑 day 0-5，day_end 5 时 evict day<3 encounter；
  随后写 snapshot；新 worker resume 该 snapshot
- **THEN** restored store 的 encounter events 全部 tick >= 3*288；
  无 evicted event 复活

