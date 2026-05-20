## 1. Mid-day resume (closes backlog 1.16)

- [x] 1.1 `SimulationCheckpoint.tick_index_in_day: int = 0` field
- [x] 1.2 `Orchestrator.run(start_tick=0)` parameter + tick range
- [x] 1.3 `Orchestrator.run` out-of-bounds raises ValueError; total_ticks reflects actual
- [x] 1.4 `MultiDayRunner._write_snapshot` populates tick_in_day
- [x] 1.5 `MultiDayRunner.run_multi_day` passes start_tick on first resumed day
- [x] 1.6 e2e test: fresh 2d == mid-day-snap resume

## 2. ConversationService snapshot

- [x] 2.1 `ConversationService.to_snapshot_state` / `from_snapshot_state`
- [x] 2.2 `SimulationCheckpoint.conversation_service_state` field
- [x] 2.3 `SimulationCheckpoint.restore_into(conversation_service=...)`
- [x] 2.4 `MultiDayRunner._write_snapshot` populates it
- [x] 2.5 `MultiDayRunner` restore path passes it via memory_service._conversation
- [x] 2.6 round-trip test (RNG + infos + known)

## 3. Drift formula fix

- [x] 3.1 `_check_ledger_drift_static` uses tick_in_day not tick_global
- [x] 3.2 warning message says (tick_in_day+1)*5min
- [x] 3.3 regression tests: day-boundary snap, legacy snap derivation

## 4. R5 MagicMock regression

- [x] 4.1 test_snapshot_pre_write_prune.py fixtures set ints + None anchor
- [x] 4.2 test_snapshot_size_reduction.py fixtures set ints + None anchor

## 5. Per-service RNG characterization (original scope)

- [x] 5.1 AttentionService / MemoryService / DialogueService round-trip
- [x] 5.2 rng_state field arbitrary-RNG round-trip

## 6. Validate + archive

- [ ] 6.1 `openspec validate resume-rng-state-determinism --strict`
- [ ] 6.2 full regression test suite green
- [ ] 6.3 archive after commit
