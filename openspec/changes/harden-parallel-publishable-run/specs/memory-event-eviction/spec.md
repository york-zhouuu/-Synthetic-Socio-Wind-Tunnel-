## ADDED Requirements

### Requirement: SHALL evict encounter events with correct day_index filter

`MemoryStore.evict_cold_encounter_events(before_day_index)` MUST actually
remove events matching `kind == "encounter" AND day_index < before_day_index`.
Verified by: 1000-agent × 4-day smoke MUST produce events_evicted > 0 at the
first day_end where `before_day_index >= 1` (i.e. day 3+ with GRACE=2, or
day 2+ with GRACE=1).

The fix SHALL address root cause (one of):
- record() sets event.day_index correctly from tick's day, not from record
  call's current_day
- evict_cold_encounter_events kind filter matches the actual kind string used
  by encounter event creation

#### Scenario: evict reports non-zero count when old events exist

- **GIVEN** a MemoryStore with 1000 encounter events spanning day_index 0..3
- **WHEN** `evict_cold_encounter_events(before_day_index=2)` is invoked
- **THEN** returned count SHALL be > 0 (specifically, the number of events
  with day_index < 2 and kind=="encounter")
- **AND** events_evicted in the EVICT event written to events.jsonl SHALL
  match the returned count

#### Scenario: post-evict snapshot shrinks

- **GIVEN** a publishable smoke at day 3 end with 4M+ memory events
- **WHEN** cold-prune fires (GRACE=2, before_day_index=1)
- **THEN** snapshot file written immediately after SHALL be < snapshot file
  written at day 2 end × 0.7 (significant shrink, not just metadata
  difference)

### Requirement: SHALL log diagnostic counts on every evict invocation

`evict_cold_encounter_events_across_agents` MUST log diagnostic counts every
time it's invoked, so future regressions are immediately visible in worker logs:

```
[evict_diag] before_day_index=1 total_events=4426274
  encounter_count=2200000 with_day_index=2200000 old_enough=1130000
  → evicting 1130000 events
```

#### Scenario: diagnostic log emitted

- **GIVEN** any call to `evict_cold_encounter_events_across_agents`
- **WHEN** the function executes
- **THEN** a log line with prefix `[evict_diag]` SHALL be emitted
- **AND** the log SHALL include: total_events, encounter_count,
  with_day_index, old_enough, before_day_index
