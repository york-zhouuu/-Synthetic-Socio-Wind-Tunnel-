## ADDED Requirements

### Requirement: SHALL preserve per-service RNG state across snapshot

Per-service RNG state SHALL be serialized in `to_snapshot_state` and
restored in `from_snapshot_state` for AttentionService, MemoryService,
and DialogueService. A snapshot taken at time T followed by restore
into a fresh service produces an RNG that yields the identical
sequence as if the original service had continued.

#### Scenario: AttentionService RNG round-trip

- **GIVEN** an `AttentionService` with seed=42 that has consumed N draws
- **WHEN** `to_snapshot_state` is serialized and `from_snapshot_state`
  is called on a fresh service with a different seed
- **THEN** the fresh service's next `_rng.random()` SHALL equal the
  original service's (N+1)th draw

#### Scenario: MemoryService RNG round-trip

- **GIVEN** a `MemoryService` with seed=42 that has consumed N draws
- **WHEN** snapshot → restore into a fresh service with a different seed
- **THEN** fresh service's next draw SHALL equal the original's (N+1)th

#### Scenario: DialogueService RNG round-trip

- **GIVEN** a `DialogueService` with seed=42 that has consumed N draws
- **WHEN** snapshot → restore into a fresh service with a different seed
- **THEN** fresh service's next draw SHALL equal the original's (N+1)th

### Requirement: SHALL round-trip arbitrary named RNGs via rng_state field

Arbitrary named RNGs MUST round-trip through atomic write + read of the
SimulationCheckpoint rng_state field, preserving the exact RNG sequence
for non-service RNGs (e.g. orchestrator-owned). The capture_rng and
restore_rng helpers are the public API for this path.

#### Scenario: capture_rng + restore_rng via atomic write

- **GIVEN** an arbitrary `random.Random` with N draws consumed
- **WHEN** `capture_rng({"name": rng})` → assigned to `rng_state` →
  `write_atomic(path)` → `read(path)` → `restore_rng(loaded.rng_state,
  {"name": fresh_rng})`
- **THEN** fresh_rng's next draw SHALL equal the original's (N+1)th
