## ADDED Requirements

### Requirement: snapshot 写盘前 cold-prune encounter events

`MultiDayRunner._write_snapshot` SHALL 在调用 `SimulationCheckpoint.write_atomic()` 之前先调用 `self._memory_service.evict_cold_encounter_events_across_agents(before_tick=cutoff)`，其中：

```
cutoff = max(0, day_index - grace) * ticks_per_day
```

`grace` 取自既有 env `MEMORY_EVENT_EVICT_GRACE_DAYS`（默认 2），与
day_end eviction 共享同一配置。

`cutoff <= 0` 时（早期 day，未到 grace window）SHALL 跳过 evict
直接写完整 snapshot。

env `SNAPSHOT_PRUNE_BEFORE_WRITE` 默认 `true`；设 `0` / `false` SHALL
完全禁用 pre-write evict，恢复旧行为（写完整 snapshot）。

evict 失败 SHALL 仅 log warning 不抛异常 — snapshot write 继续进行。

写盘后 SNAPSHOT_WRITE event SHALL 新增 `events_evicted_before_write`
字段反映本次 pre-write prune 释放的事件数（0 当 cutoff<=0 或 disabled）。

#### Scenario: snapshot 写盘前自动 prune

- **GIVEN** `MEMORY_EVENT_EVICT_GRACE_DAYS=2`，worker 当前 `day_index=10`，
  ticks_per_day=288，memory_store 含 day 0-10 累积的 encounter events
- **WHEN** `_write_snapshot(tick_index_global=2880, day_index=10, ...)`
  被调用（snapshot 触发点）
- **THEN** 调用前 SHALL 触发
  `evict_cold_encounter_events_across_agents(before_tick=8*288=2304)`；
  snapshot 文件落盘时 `memory_store_state` SHALL 不含 tick < 2304 的
  encounter events；day 8-10 的 encounter events 保留

#### Scenario: 早期 day 跳过 prune

- **GIVEN** `MEMORY_EVENT_EVICT_GRACE_DAYS=2`，worker 当前 `day_index=1`
- **WHEN** `_write_snapshot(tick_index_global=288, day_index=1, ...)` 被调用
- **THEN** `cutoff = max(0, 1-2) * 288 = 0`，SHALL 跳过 evict；
  snapshot 落盘时 `memory_store_state` 保留全部历史 encounter events

#### Scenario: env 关闭 prune 恢复旧行为

- **WHEN** `SNAPSHOT_PRUNE_BEFORE_WRITE=0` 设置，`day_index=10`
- **THEN** `_write_snapshot` SHALL NOT 调用 evict；snapshot 落盘时
  `memory_store_state` 含完整历史；events_evicted_before_write=0

#### Scenario: evict 失败不阻塞 snapshot write

- **GIVEN** `_memory_service.evict_cold_encounter_events_across_agents`
  抛 RuntimeError（mock）
- **WHEN** `_write_snapshot(day_index=10, ...)` 被调用
- **THEN** SHALL log warning 包含 "pre-write evict failed"；snapshot
  SHALL 仍然落盘（虽然没 prune，size 较大但写入完成）

#### Scenario: SNAPSHOT_WRITE event 包含 events_evicted_before_write

- **GIVEN** pre-write evict 释放 50000 events
- **WHEN** `_write_snapshot` 完成
- **THEN** instrumentation 写入的 SNAPSHOT_WRITE event SHALL 含字段
  `events_evicted_before_write: 50000`
