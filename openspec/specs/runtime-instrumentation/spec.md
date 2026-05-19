# runtime-instrumentation Specification

## Purpose
TBD - created by archiving change comprehensive-runtime-instrumentation. Update Purpose after archive.
## Requirements
### Requirement: RuntimeInstrumentation process singleton

`synthetic_socio_wind_tunnel.observability.instrumentation.RuntimeInstrumentation` SHALL be a process-wide singleton accessed via `get_instrumentation()` (lazy init from env), with `reset_for_tests()` available for test isolation. Pattern matches existing `LLMHealthTracker.get_tracker()`.

The singleton SHALL open three line-buffered JSONL files on first use:

- `<output_dir>/seed_<N>.memstat.jsonl` — periodic metric samples
- `<output_dir>/seed_<N>.events.jsonl` — discrete events
- `<output_dir>/seed_<N>.llm.jsonl` — per-LLM-call records

`output_dir` SHALL be controlled by env `INSTRUMENTATION_OUTPUT_DIR` with default fallback to current working directory.

`INSTRUMENTATION_DISABLE=1` SHALL make `get_instrumentation()` return a no-op stub (all emit methods are silent), enabling production rollback.

#### Scenario: First access creates singleton + opens 3 files

- **WHEN** `get_instrumentation()` is called for the first time in a process with `INSTRUMENTATION_OUTPUT_DIR=/tmp/test`
- **THEN** SHALL create `/tmp/test/seed_<N>.memstat.jsonl`, `/tmp/test/seed_<N>.events.jsonl`, `/tmp/test/seed_<N>.llm.jsonl`; all three SHALL be opened in line-buffered append mode; subsequent calls return the same instance

#### Scenario: INSTRUMENTATION_DISABLE returns no-op stub

- **WHEN** env `INSTRUMENTATION_DISABLE=1` set, `get_instrumentation()` called
- **THEN** SHALL return a stub whose `emit_event` / `emit_llm_call` / `sample_metrics` are silent no-ops; no JSONL files SHALL be created

#### Scenario: reset_for_tests clears singleton + closes files

- **WHEN** test calls `reset_for_tests()`
- **THEN** SHALL close any open JSONL files and clear the module-level singleton so the next `get_instrumentation()` opens fresh files

### Requirement: Memstat sample schema + cadence

`RuntimeInstrumentation.sample_metrics(tick_global, day_index, tick_in_day)` SHALL be called from `MultiDayRunner._on_tick_end_memory` hook every `INSTRUMENTATION_SAMPLE_EVERY_N_TICKS` ticks (default 12). Each invocation SHALL append one JSON line to `memstat.jsonl` with the following schema:

```json
{
  "v": 1,
  "ts_iso": "<ISO-8601 UTC>",
  "ts_monotonic": <float seconds>,
  "tick_global": <int>, "day_index": <int>, "tick_in_day": <int>,
  "sim_time_iso": "<ISO-8601>",
  "memory": {
    "rss_mb": <int>,        // psutil.Process().memory_info().rss
    "vms_mb": <int>,
    "uss_mb": <int|null>,   // private; null on macOS if AccessDenied
    "rss_peak_mb": <int>,   // ru_maxrss (lifetime peak, informational)
    "open_fds": <int|null>, "threads": <int>
  },
  "cpu": {
    "percent_recent": <float>,
    "user_sec": <float>, "sys_sec": <float>,
    "wall_since_last_sample_sec": <float>,
    "tick_count_since_last_sample": <int>
  },
  "gc": {"gen0": <int>, "gen1": <int>, "gen2": <int>},
  "memory_store": {
    "agents": <int>, "total_events": <int>,
    "events_by_kind": {"<kind>": <int>, ...}
  },
  "dialogue_service": {"live": <int>, "evicted_total": <int>},
  "llm_health": {
    "rolling_fallback_rate": <float>, "rolling_sample_n": <int>,
    "keys_open": <int>, "keys_total": <int>
  },
  "handler_times_sec": {
    "<kind>": {"calls": <int>, "wall_sum": <float>,
               "p50_ms": <float>, "p95_ms": <float>}
  }
}
```

The `memory.rss_mb` field SHALL be the **current** RSS via psutil, NOT `ru_maxrss`. The `memory.rss_peak_mb` field SHALL be `ru_maxrss` for historical reference.

#### Scenario: memstat schema includes all documented fields

- **WHEN** `sample_metrics(tick_global=200, day_index=0, tick_in_day=200)` is called in a real test subprocess
- **THEN** the appended JSON line SHALL parse successfully and contain top-level keys `v`, `ts_iso`, `ts_monotonic`, `tick_global`, `day_index`, `tick_in_day`, `memory`, `cpu`, `gc`, `memory_store`, `dialogue_service`, `llm_health`, `handler_times_sec`

#### Scenario: rss_mb is current not peak

- **GIVEN** a process that allocated then freed 500 MB
- **WHEN** `sample_metrics` is called after the free + `gc.collect()`
- **THEN** `memory.rss_mb` SHALL be less than `memory.rss_peak_mb` (since current dropped after free but peak stayed)

#### Scenario: sample cadence respects env

- **GIVEN** `INSTRUMENTATION_SAMPLE_EVERY_N_TICKS=50` set
- **WHEN** worker runs 200 ticks
- **THEN** memstat.jsonl SHALL have exactly 4 sample lines (at tick 50, 100, 150, 200)

### Requirement: Phase event emit + ordering

`RuntimeInstrumentation.emit_event(kind="PHASE", phase=<name>, **kw)` SHALL append a phase-transition event to `events.jsonl` at every documented boundary. Required phase names + emit sites:

- `PROCESS_START` — first `get_instrumentation()` call
- `SETUP_START` — `tools/run_variant_suite.py` aitown wiring begin
- `SETUP_DONE` — aitown wiring complete (after `[aitown] wired` log)
- `SNAPSHOT_LOAD_START` — `MultiDayRunner._restore_from_snapshot` begin
- `SNAPSHOT_LOAD_DONE` — restore complete, before tick loop
- `TICK_LOOP_START` — `Orchestrator.run` first tick about to execute
- `DAY_START` — `MultiDayRunner.on_day_start` hook
- `DAY_END` — `MultiDayRunner.on_day_end` hook
- `EXIT` — `atexit.register`-hooked shutdown OR `MultiDayRunner.run_multi_day` finally

Each PHASE event SHALL carry `phase`, `ts_iso`, `ts_monotonic`, `rss_mb` (current), and phase-specific fields per design D7 table.

#### Scenario: All 9 phase events fire in correct order in real dev smoke

- **WHEN** dev smoke 50 agent × 1 day completes (no crash)
- **THEN** events.jsonl SHALL contain phase events in this order: PROCESS_START, SETUP_START, SETUP_DONE, [SNAPSHOT_LOAD_START + SNAPSHOT_LOAD_DONE only if resuming], TICK_LOOP_START, DAY_START, DAY_END, EXIT; no phase event SHALL appear twice (except DAY_START/DAY_END for multi-day)

#### Scenario: Crash still emits EXIT via atexit

- **GIVEN** worker crashes mid-tick with uncaught exception
- **WHEN** Python interpreter shuts down
- **THEN** atexit hook SHALL emit EXIT event with `reason="atexit"` + `final_rss_mb` field; events.jsonl SHALL have EXIT as final line

### Requirement: Eviction event schema

`RuntimeInstrumentation.emit_event(kind="EVICT", ...)` SHALL be called by `MemoryService.evict_cold_encounter_events_across_agents` after returning. Required fields:

```json
{"v": 1, "kind": "EVICT", "ts_iso": "...",
 "tick_global": <int>, "day_index": <int>,
 "before_tick_cutoff": <int>,
 "events_evicted": <int>,
 "memory_store_total_before": <int>,
 "memory_store_total_after": <int>,
 "duration_sec": <float>,
 "rss_before_mb": <int>, "rss_after_mb": <int>}
```

#### Scenario: EVICT event values match real store delta

- **GIVEN** memory_store has 100 encounter events, eviction with `before_tick_cutoff` evicts 30 of them
- **WHEN** EVICT event is emitted
- **THEN** `events_evicted == 30`; `memory_store_total_before - memory_store_total_after == 30`; `duration_sec > 0`

### Requirement: Retry event schema

`tools/tier_llm_factory._run_with_retry` SHALL emit one RETRY event per failed retryable attempt (NOT on success path). Required fields:

```json
{"v": 1, "kind": "RETRY", "ts_iso": "...",
 "tier": "sonnet|haiku|nano", "provider": "deepseek|...",
 "key_id": <int|null>, "attempt": <int 0-indexed>,
 "max_attempts": <int>,
 "exc_class": "openai.APIConnectionError",
 "exc_message": "<short str, truncated to 200 chars>",
 "backoff_sec": <float>,
 "elapsed_sec_since_op_start": <float>}
```

#### Scenario: Retry events emit per attempt, not at exhaustion only

- **GIVEN** `_run_with_retry` with `max_attempts=3` and operation raising real `openai.APIConnectionError` on attempts 1 and 2, succeeding on 3
- **WHEN** operation completes
- **THEN** events.jsonl SHALL contain exactly 2 RETRY events (attempts 1 and 2); no RETRY for successful attempt 3

### Requirement: Snapshot write event schema

`MultiDayRunner._write_snapshot` (or equivalent) SHALL be wrapped to emit one SNAPSHOT_WRITE event per write. Required fields:

```json
{"v": 1, "kind": "SNAPSHOT_WRITE", "ts_iso": "...",
 "tick_global": <int>, "path": "...",
 "duration_sec": <float>, "size_bytes": <int>,
 "rss_before_mb": <int>, "rss_peak_during_mb": <int>,
 "rss_after_mb": <int>}
```

`rss_peak_during_mb` SHALL be the max RSS sampled at write start, middle, and end (best-effort 3-point sample).

#### Scenario: SNAPSHOT_WRITE captures RSS delta during write

- **WHEN** snapshot write completes successfully
- **THEN** SNAPSHOT_WRITE event SHALL have `rss_peak_during_mb >= rss_before_mb` (writes can spike RSS); `size_bytes` SHALL match `os.path.getsize(path)` of the final file

### Requirement: LLM call sampling + error 100% capture

`RuntimeInstrumentation.emit_llm_call(tier, provider, model, kind, agent_id, latency_ms, status, attempt, exc_class=None, key_id=None)` SHALL be called by each tier client after each `generate()` returns or raises. Required fields:

```json
{"v": 1, "ts_iso": "...",
 "tier": "sonnet|haiku|nano",
 "provider": "deepseek|anthropic|gemini|volces|stub",
 "model": "<model-id>", "kind": "do_something|generate_message|...",
 "agent_id": "<id|null>", "key_id": <int|null>,
 "attempt": <int>, "max_attempts": <int>,
 "latency_ms": <int>,
 "status": "success|fallback|exhausted",
 "exc_class": "<class|null>",
 "prompt_chars": <int|null>, "response_chars": <int|null>}
```

Success calls SHALL be sampled per env `LLM_SAMPLE_RATE` (default 0.01 = 1%). Calls with `status != "success"` SHALL be recorded 100% regardless of sample rate (env `LLM_RECORD_ERRORS_ALL=true` default).

#### Scenario: success path samples 1% by default

- **GIVEN** 10000 successful LLM calls, default `LLM_SAMPLE_RATE=0.01`
- **WHEN** all are emit_llm_call'd
- **THEN** llm.jsonl SHALL contain approximately 100 ± 30 success rows (Poisson-distributed around 1% × 10000 = 100)

#### Scenario: error path always 100% recorded

- **GIVEN** 1000 failing LLM calls (status=fallback or exhausted), default settings
- **WHEN** all are emit_llm_call'd
- **THEN** llm.jsonl SHALL contain exactly 1000 error rows (no sampling)

### Requirement: Failure isolation — instrumentation MUST NOT crash worker

Every emit / sample method SHALL be wrapped in try/except. JSONL write failures, file system errors, psutil errors SHALL log warning and continue without raising.

#### Scenario: JSONL write failure does not crash worker

- **GIVEN** `events.jsonl` file descriptor becomes invalid (simulated via mock that raises OSError on write)
- **WHEN** `emit_event` is called
- **THEN** SHALL log warning containing "instrumentation"; SHALL return normally without raising

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

### Requirement: emit_llm_call SHALL fire from tier client generate() success path

Every tier client's `generate()` method in `tools/tier_llm_factory.py` (Stub / Gemini / DeepSeek / Anthropic / Volces) SHALL call `get_instrumentation().emit_llm_call(...)` after `_run_with_retry` returns successfully. The call SHALL pass:

- `tier` (sonnet / haiku / nano — passed in via constructor)
- `provider` (stub / gemini / deepseek / anthropic / volces — constructor param)
- `model` (`self._model`)
- `kind` — defaulted to `"unknown"` if caller didn't supply (do_something / generate_message / etc.)
- `agent_id` — defaulted to None if caller didn't supply
- `latency_ms` — measured via `time.perf_counter()` around `_run_with_retry`
- `status="success"`
- `attempt=0` for success (retries are emitted as separate RETRY events)
- `max_attempts=policy.max_attempts`
- `key_id` — index of the key actually used (0 for single-key providers like Anthropic)

emit failures SHALL NOT propagate — try/except per existing instrumentation isolation rule.

#### Scenario: dev smoke subprocess writes llm.jsonl with success records

- **WHEN** dev smoke 50 agent × 1 day runs with `LLM_SAMPLE_RATE=1.0` (force all-sample for test)
- **THEN** `seed_42.llm.jsonl` SHALL exist and contain at least 100 lines, each with `status="success"` and a numeric `latency_ms > 0`

#### Scenario: each tier client wires emit

- **WHEN** dev smoke completes
- **THEN** the set of `tier` values seen in llm.jsonl SHALL include the tiers actually used (at least one of sonnet/haiku/nano)

### Requirement: emit_llm_call SHALL fire from do_something fallback path

`synthetic_socio_wind_tunnel/agent/operations/handlers/do_something.py` handler's except branches (AllKeysOpenError, generic Exception, unparseable response) SHALL emit_llm_call with `status="fallback"` and `exc_class=<full class path>` (or `"unparseable_response"` for the parse-failure branch).

#### Scenario: fallback path emits to llm.jsonl

- **GIVEN** worker hits AllKeysOpenError or unparseable LLM response
- **WHEN** fallback path taken in do_something handler
- **THEN** llm.jsonl SHALL have a record with `status="fallback"` and either `exc_class="...AllKeysOpenError"` or `exc_class="unparseable_response"`

