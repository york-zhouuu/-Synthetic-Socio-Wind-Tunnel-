## ADDED Requirements

### Requirement: SHALL support mid-day resume via start_tick parameter

Orchestrator.run MUST accept a `start_tick: int = 0` parameter such that
the tick loop runs `range(start_tick, ticks_per_day)`. SimulationCheckpoint
SHALL carry a `tick_index_in_day` field recording which tick within
day_index had completed at snap time. MultiDayRunner on resume SHALL
pass `start_tick = snap.tick_index_in_day + 1` to the first resumed day,
so the boundary tick is not re-executed.

#### Scenario: resume from mid-day snap matches fresh run

- **GIVEN** fresh 2-day run with seed=42 produces final ledger time T_fresh
- **WHEN** the same world is run 1 day → mid-day snap at tick 144 →
  resume restores → runs to day-2 end
- **THEN** final ledger.current_time SHALL equal T_fresh
- **AND** per-agent state SHALL equal fresh run's per-agent state

#### Scenario: start_tick out of bounds raises

- **GIVEN** an Orchestrator with ticks_per_day=288
- **WHEN** `run(day_index=0, start_tick=300)` is invoked
- **THEN** SHALL raise ValueError with "out of bounds"

#### Scenario: start_tick = num_ticks is noop

- **GIVEN** an Orchestrator
- **WHEN** `run(day_index=0, start_tick=288)` is invoked
- **THEN** SHALL return SimulationSummary with total_ticks=0
- **AND** ledger.current_time SHALL NOT advance

### Requirement: SHALL snapshot ConversationService state

ConversationService MUST implement `to_snapshot_state` / `from_snapshot_state`
covering `_rng` state, `_infos` dict, `_known` per-agent knowledge map,
`_known_by_info` inverse index, and `_share_count`. SimulationCheckpoint
SHALL carry a `conversation_service_state` field. MultiDayRunner SHALL
populate it (from memory_service._conversation) and restore it through
SimulationCheckpoint.restore_into.

#### Scenario: ConversationService RNG round-trip

- **GIVEN** a ConversationService with seed=42 that has consumed N draws
- **WHEN** to_snapshot_state → write JSON → read JSON → from_snapshot_state
  into a fresh service with a different seed
- **THEN** fresh service's next `_rng.random()` SHALL equal original's
  (N+1)th draw

#### Scenario: ConversationService propagation state round-trip

- **GIVEN** a ConversationService with N recorded infos and known mappings
- **WHEN** to_snapshot_state → from_snapshot_state
- **THEN** fresh service SHALL have identical _infos, _known,
  _known_by_info, and _share_count

### Requirement: SHALL compute drift expected time from tick_in_day

The `_check_ledger_drift_static` helper MUST derive tick_in_day from
`snap.tick_index - snap.day_index * ticks_per_day` (works for both legacy
and new snaps). Expected ledger time SHALL be `anchor + day_idx*1d +
(tick_in_day+1)*5min` — accounting for the fact that snap fires AFTER
tick completes, so ledger has advanced (tick_in_day+1) ticks from the
day boundary.

#### Scenario: day-boundary snap reports no false-positive drift

- **GIVEN** a snap with day_index=1, tick_index=288, ledger=anchor+1d+5min
- **WHEN** drift check runs against anchor=day_0
- **THEN** SHALL NOT emit drift warning (expected = actual)

#### Scenario: legacy snap derives tick_in_day from tick_global

- **GIVEN** a legacy snap (no tick_index_in_day field) with day_index=1,
  tick_index=432, ledger=anchor+1d+12h05min
- **WHEN** drift check runs
- **THEN** tick_in_day = 432 - 1*288 = 144; expected = anchor + 1d +
  145*5min = anchor+1d+12h05min; SHALL NOT emit warning
