## Why

User goal (2026-05-21): "断点续跑要和正常跑完全一模一样" — resume
SHALL produce identical state to a fresh run, modulo LLM stochasticity
(server-side randomness, acknowledged out of scope).

Original scope was narrow ("preserve existing per-service RNG via
characterization tests"). Deeper investigation found 4 concrete
divergence sources that broke "完全一模一样":

1. **Mid-day snap re-execution** (backlog 1.16): `_on_tick_end_resume_hook`
   fires AFTER tick completes. A snap at `tick_global=288` actually
   represents "288 ticks have completed", but `Orchestrator.run(day_index=1)`
   on resume re-runs day 1 from tick 0 → boundary tick double-executed.
   1-tick offset per resume; accumulates over 14-day run with multiple
   resumes.

2. **ConversationService._rng + state not snapshotted**: P(share)
   probabilistic gate in `process_tick` consumes `_rng.random()` per
   share decision. `_known` / `_known_by_info` / `_share_count` are
   per-info propagation state. Resume currently starts these empty,
   diverging from fresh at first ShareEvent emission.

3. **Drift check formula bug** (`_check_ledger_drift_static`): formula
   `expected = anchor + day*1d + tick*5min` treated `snap.tick_index`
   (tick_GLOBAL) as if it were `tick_in_day`. Produced false-positive
   drift warnings of `day_idx * 24h` on every cross-variant resume.

4. **R5 MagicMock regression**: 3 existing tests in
   `test_snapshot_pre_write_prune.py` + `test_snapshot_size_reduction.py`
   were broken when R5 added `start_date_anchor_iso: str | None` to
   pydantic model (MagicMock not coerced).

## What Changes

### Mid-day resume (closes backlog 1.16)

- `SimulationCheckpoint.tick_index_in_day: int = 0` field — records
  which tick within `day_index` had just completed when snap fired
- `Orchestrator.run(start_tick: int = 0)` parameter — tick loop
  becomes `range(start_tick, num_ticks)`; `total_ticks` reflects actual
  ticks run; out-of-bounds raises ValueError
- `MultiDayRunner._write_snapshot` populates `tick_index_in_day` from
  `tick_result.tick_index`
- `MultiDayRunner.run_multi_day` on the first resumed day passes
  `start_tick = snap.tick_index_in_day + 1`; subsequent days pass 0
- E2E test: fresh 2-day run == mid-day-snap resume run (byte-equal
  ledger + agent state at end)

### ConversationService state snapshot

- `ConversationService.to_snapshot_state` / `from_snapshot_state`
  methods covering `_rng`, `_infos`, `_known`, `_known_by_info`,
  `_share_count` (callable providers not snapshotted — rebuilt at
  init)
- `SimulationCheckpoint.conversation_service_state` field
- `SimulationCheckpoint.restore_into(conversation_service=...)` param
- `MultiDayRunner` populates / restores via
  `self._memory_service._conversation` (canonical owner)

### Drift formula fix

- `_check_ledger_drift_static` derives `tick_in_day` from
  `tick_global - day*ticks_per_day` instead of using `tick_index`
  as tick_in_day. Formula becomes `expected = anchor + day_idx*1d +
  (tick_in_day+1)*5min`
- Warning message updated to surface tick_in_day instead of tick_global
- 2 new tests: false-positive at day boundary; legacy snap derives
  via tick_global

### R5 MagicMock regression fix

- `test_snapshot_pre_write_prune.py` + `test_snapshot_size_reduction.py`
  fixtures set explicit ints + `runner._start_date_anchor = None` to
  short-circuit `.isoformat()` calls leaking MagicMock into pydantic

### Per-service RNG characterization tests (original scope)

- `test_resume_byte_identical_to_fresh.py` covers RNG round-trip for
  Attention/Memory/Dialogue services + arbitrary `rng_state` field

## Capabilities

### Modified Capabilities

- `tick-level-resume`: SHALL support mid-day resume via
  `start_tick`; `conversation_service_state` SHALL round-trip;
  drift check formula uses tick_in_day

## Impact

**Affected code**:
- `synthetic_socio_wind_tunnel/orchestrator/service.py` (`start_tick`)
- `synthetic_socio_wind_tunnel/orchestrator/multi_day.py`
  (write snap with tick_in_day; restore with conversation_service;
  drift formula; passes start_tick on resume)
- `synthetic_socio_wind_tunnel/run_resilience/state_snapshot.py`
  (new fields; restore_into conversation_service param)
- `synthetic_socio_wind_tunnel/conversation/service.py`
  (`to_snapshot_state` / `from_snapshot_state`)
- 2 test fixture files patched
- 2 new test files / appended classes

**Affected behavior**:
- Mid-day resume now byte-equal to fresh (verified via e2e)
- Drift warnings no longer false-positive at day boundaries
- ConversationService _share_count / _known continues across resume
- Backwards compatible: legacy snaps (without new fields) load fine

**Non-goals**:
- LLM-call bit-identity (server-side randomness)
- `RuntimeInstrumentation._rng` / `DigitalAttentionFilter._rng`
  snapshot — confirmed by audit as telemetry-only (no ledger impact)
