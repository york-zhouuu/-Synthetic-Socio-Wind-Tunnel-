## ADDED Requirements

### Requirement: 7 phase events SHALL fire from wired sites in real worker run

The 7 phase events documented in `comprehensive-runtime-instrumentation` D7 SHALL be emitted from the documented code sites — not just be theoretically available via the `emit_event` API. A real worker run (dev smoke or publishable) SHALL produce events.jsonl containing all 9 phase events (including PROCESS_START + EXIT already wired) in correct order:

```
PROCESS_START → SETUP_START → SETUP_DONE →
[SNAPSHOT_LOAD_START → SNAPSHOT_LOAD_DONE]?  (resume path only)
→ TICK_LOOP_START → (DAY_START → ... → DAY_END)* → EXIT
```

Each phase event SHALL include phase-specific fields per D7:

- `SETUP_START` — no extra fields beyond default (ts, rss_mb)
- `SETUP_DONE` — `duration_sec` + `rss_before_mb` + `rss_after_mb`
- `SNAPSHOT_LOAD_START` — `snapshot_path`, `size_bytes` (read from disk)
- `SNAPSHOT_LOAD_DONE` — `duration_sec`, `rss_before_mb`, `rss_after_mb`,
  `delta_mb`
- `TICK_LOOP_START` — no extra fields
- `DAY_START` / `DAY_END` — `day_index`

#### Scenario: dev smoke subprocess emits all phase events in order

- **WHEN** `tools/run_variant_suite.py --mode=dev --variants=baseline
  --seeds=1 --num-days=1 --agents=50` runs as subprocess to completion
- **THEN** `seed_42.events.jsonl` in output dir SHALL contain phase
  events in this order: PROCESS_START, SETUP_START, SETUP_DONE,
  TICK_LOOP_START, DAY_START, DAY_END, EXIT (no SNAPSHOT_LOAD_*
  since not resuming); SHALL NOT have duplicates

#### Scenario: resume path adds SNAPSHOT_LOAD_START + SNAPSHOT_LOAD_DONE

- **GIVEN** an existing snapshot at `seed_<N>_tick<T>.snapshot.json`
- **WHEN** worker spawned with `--resume --resume-strategy=auto`
- **THEN** events.jsonl SHALL include `SNAPSHOT_LOAD_START` (before
  load) + `SNAPSHOT_LOAD_DONE` (after load with duration_sec and rss
  delta) between `SETUP_DONE` and `TICK_LOOP_START`

#### Scenario: SETUP_DONE event includes duration

- **WHEN** any worker setup completes
- **THEN** the SETUP_DONE event SHALL have `duration_sec >= 0` and
  `rss_after_mb >= rss_before_mb` (setup growth ≥ 0)

### Requirement: memstat sampling SHALL fire periodically from on_tick_end hook

`MultiDayRunner._init_memory_management_hooks` SHALL register a call
to `get_instrumentation().sample_metrics(tick_global, day_index,
tick_in_day, memory_service=..., dialogue_service=...,
llm_tracker=...)` inside its `_on_tick_end_memory` hook callback, fired
every `INSTRUMENTATION_SAMPLE_EVERY_N_TICKS` (default 12) ticks.

Each sample call SHALL populate the full memstat schema per existing
`runtime-instrumentation` spec — including the `memory_store`,
`dialogue_service`, and `llm_health` substructures derived from
the live service references.

`INSTRUMENTATION_DISABLE=1` SHALL skip sample calls entirely (via the
no-op stub returned by `get_instrumentation()`).

#### Scenario: 1-day dev smoke produces ≥ N memstat samples

- **GIVEN** `INSTRUMENTATION_SAMPLE_EVERY_N_TICKS=12` (default),
  ticks_per_day=288
- **WHEN** dev smoke 50 agent × 1 day completes
- **THEN** `seed_42.memstat.jsonl` SHALL contain at least 20 sample
  lines (288 / 12 = 24 expected, allow some early-tick skip for tick=0)

#### Scenario: each memstat line has memory_store.total_events from live service

- **WHEN** dev smoke runs with `MemoryService` accumulating ~1000
  encounter events per day per agent
- **THEN** the last memstat sample's `memory_store.total_events`
  SHALL be > 0 (reflecting live service state, not 0 placeholder)

#### Scenario: INSTRUMENTATION_DISABLE skips sampling

- **WHEN** `INSTRUMENTATION_DISABLE=1` set
- **THEN** dev smoke SHALL NOT create `seed_42.memstat.jsonl` file
  (or it SHALL be empty)
