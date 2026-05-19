## MODIFIED Requirements

### Requirement: MemoryStore 必须支持 cold prune encounter events

`MemoryStore` SHALL 提供 `evict_cold_encounter_events(before_day_index: int) -> int` 方法，删除满足以下条件的 events:

- `kind == "encounter"`
- `day_index < before_day_index`

**2026-05-20 修正**：参数从 `before_tick` 改为 `before_day_index`。
原 signature `before_tick` 假设 `ev.tick` 是 global tick，但实际
caller 传 global cutoff (`day*288+...`) 而 `ev.tick` 是 per-day
(0-287)，导致所有 encounter event 永远满足 `ev.tick < cutoff` → 全被
错杀。改用 `day_index` 比较语义清晰、跟 caller 直觉一致 ("evict
grace_days 之前的 day")。

其它 kind 的 events SHALL NOT 被本方法触及（不动 life_history / action /
reflection / conversation / daily_summary / shared_memory / notification /
observation / speech / task_received）。

返回值：本次 evict 的 event 数。

实现 SHALL 同时清理依赖 events 列表的内部反向索引。

#### Scenario: evict 只删 day_index < before_day_index 的 encounter

- **WHEN** MemoryStore 含 5 个 events: [encounter@day0/tick10,
  action@day0/tick10, encounter@day3/tick50, reflection@day3/tick50,
  encounter@day5/tick100]，调 `evict_cold_encounter_events(before_day_index=3)`
- **THEN** 返回 1（只 day=0 的 encounter 被删）；store 剩 4 个 events；
  action / reflection / day=3 + day=5 encounter SHALL 仍存在

#### Scenario: 全 evict 后 store 合法

- **WHEN** store 全是 encounter events 且全部 day_index < before_day_index
- **THEN** 全删；store.all() == [] 但 store 可继续 append；
  事件总数 == 0 不抛

#### Scenario: 空 store evict no-op

- **WHEN** 空 MemoryStore 调 evict
- **THEN** 返回 0；不抛

### Requirement: MemoryService 必须暴露 cross-agent eviction

`MemoryService` SHALL 提供 `evict_cold_encounter_events_across_agents(before_day_index: int) -> int` 方法，遍历所有 agent stores 调用各自 `evict_cold_encounter_events`，累加返回总 evict 数。

**2026-05-20 修正**：signature 同步从 `before_tick` 改为 `before_day_index`。

操作 SHALL 是 idempotent：同 before_day_index 第二次调返回 0。

#### Scenario: 跨 agent evict 累计

- **WHEN** 3 agent stores 各含 (encounter@day0, encounter@day3);
  调 `evict_cold_encounter_events_across_agents(before_day_index=2)`
- **THEN** 返回 3 (3 agent × 1 evict each)；剩余 events 全 day=3

#### Scenario: 二次调用 idempotent

- **WHEN** 同 before_day_index 第二次调
- **THEN** 返回 0；store state 不变

### Requirement: MultiDayRunner 必须在 day_end 触发 cold prune

`MultiDayRunner.run_multi_day` 的 day_end 内置 hook 链 SHALL 调用 `memory_service.evict_cold_encounter_events_across_agents(before_day_index=...)`，其中 `before_day_index = max(0, day_index - grace_days)`，grace_days 默认 2，可通过 env `MEMORY_EVENT_EVICT_GRACE_DAYS` 覆盖。

`MultiDayRunner._write_snapshot` 在写盘前 SHALL 调用同一 API（pre-write
prune，见 `tick-level-resume` capability）。

evict 数 SHALL 进 DayRunSummary 新字段 `evicted_encounter_count`（向后兼容默认 0）。

#### Scenario: day 5 时 evict day < 3 的 encounter

- **WHEN** 跑到 day_index=5，grace_days=2
- **THEN** evict 调用 before_day_index=3；day 0/1/2 的 encounter
  SHALL 被删；day 3/4/5 的 encounter SHALL 保留

#### Scenario: 早期 day_index < grace_days 时 no-op

- **WHEN** day_index=1，grace_days=2 → before_day_index=max(0, -1)=0
- **THEN** evict_cold_encounter_events_across_agents(before_day_index=0)
  返回 0（没有 day_index < 0 的 event）；no-op

## ADDED Requirements

### Requirement: encounter events SHALL accumulate in grace_days window

memory_store SHALL retain encounter events with `day_index >= (current_day - grace_days)` after each eviction cycle.

**Product-level invariant**: 当 worker 跑过 N day 且 N > grace_days 时，memory_store 里 encounter events 数量 > 0（具体是 last `grace_days` 天的 encounter）。**这是 thesis dependent variable**（agent 识别邻居依赖 encounter 累积）。

这个 invariant **必须**用 end-to-end integration test 验证（真跑 dev smoke
+ 读真 snapshot artifact），不允许用 mock test 替代 — 2026-05-20 的
教训就是 mock test 全过、真跑全空。

#### Scenario: 4 day dev smoke 后 encounter > 0

- **WHEN** 跑 50 agent × 4 day dev smoke，grace_days=2
- **THEN** final snapshot (`seed_<N>_tick_final.snapshot.json`) 的
  `memory_store_state.agent_events` aggregate 起来，encounter
  events 总数 SHALL > 0
- **AND** 这些 encounter events 的 day_index SHALL 全部 ≥ 2 (= 4-2)
- **AND** day_index < 2 的 encounter events SHALL 已被 evicted (为 0)
