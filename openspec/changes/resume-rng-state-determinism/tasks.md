## 1. Tests

- [x] 1.1 `tests/test_resume_byte_identical_to_fresh.py`:
  - `TestAttentionRngRoundTrip` — 2 tests
  - `TestMemoryRngRoundTrip` — 1 test
  - `TestDialogueRngRoundTrip` — 1 test
  - `TestSnapshotRngFieldRoundtrip` — 1 test (capture_rng / restore_rng + atomic write)

## 2. Documentation

- [x] 2.1 Test docstring documents the snap-after-tick semantic finding
  as a known limitation (not in scope of this RNG-only change)

## 3. Validate

- [x] 3.1 `openspec validate resume-rng-state-determinism --strict` — passing
- [x] 3.2 backlog item 1.16 (snap-after-tick semantic) filed for follow-up
- [ ] 3.3 archive after merge
