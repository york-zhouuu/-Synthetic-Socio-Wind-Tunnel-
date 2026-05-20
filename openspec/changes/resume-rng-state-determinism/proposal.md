## Why

User goal (2026-05-21): "断点续跑要和正常跑完全一模一样" — resume
should produce identical state to a fresh run (modulo LLM stochasticity,
which is acknowledged out of scope).

Resume already restores `ledger_state`, `agent_runtime_states`,
`memory_store_state`, `attention_service_state`, `dialogue_service_state`.
Each of those services serializes its own `_rng` state via
`to_snapshot_state` / `from_snapshot_state`. The snapshot's catch-all
`rng_state: dict[str, list[Any]]` field (intended for non-service RNGs)
is currently set to `{}` in both `_write_snapshot` and
`_write_final_snapshot_on_graceful_stop` — labeled "Caller-injected RNGs
not tracked here; future work".

This change locks the existing per-service RNG preservation behind
characterization tests so it can't silently regress, and documents the
remaining determinism gaps as known limitations to scope for follow-up.

## What Changes

- Add real-artifact tests verifying each service's RNG state survives
  snapshot round-trip: AttentionService, MemoryService, DialogueService
- Verify the generic `capture_rng` / `restore_rng` path with
  `SimulationCheckpoint.rng_state` field round-trips through atomic
  write / read
- Document the snap-after-tick semantic gap discovered during testing:
  `_on_tick_end_resume_hook` fires after each tick completes, so a snap
  labeled `tick_global=N` represents "N ticks have completed". On
  resume, `Orchestrator.run(day_index=D)` re-runs from tick 0, causing
  a 1-tick re-execution at the day boundary. Tracked separately —
  fixing requires Orchestrator changes (resume mid-day at exact tick),
  not RNG capture changes.

## Capabilities

### Modified Capabilities

- `tick-level-resume`: RNG state preserved across snapshot/resume for
  Attention/Memory/Dialogue services; `rng_state` field round-trips

## Impact

**Affected code**:
- `tests/test_resume_byte_identical_to_fresh.py` (new)

**Affected behavior**:
- Locks existing per-service RNG snapshot behavior behind tests
- Tests are characterization (no behavior change in production)

**Non-goals**:
- NOT fixing snap-after-tick semantic (see `docs/backlog.md` follow-up)
- NOT capturing ConversationService._rng (low-impact unsnapshotted RNG)
- NOT bit-equality across LLM calls (acknowledged limitation)
