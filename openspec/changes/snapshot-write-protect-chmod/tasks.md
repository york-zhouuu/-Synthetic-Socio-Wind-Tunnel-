## 1. TDD red

- [x] 1.1 `tests/test_snapshot_write_protect.py`:
  - `test_snapshot_chmod_0444_after_write` — write → check mode
  - `test_snapshot_overwrite_blocked_by_chmod` — open(w) → PermissionError
  - `test_prune_still_works_on_readonly_files` — prune deletes read-only files
  - `test_day_summary_chmod_0444` — same for day summary files
  - `test_partial_chmod_0444` — same for partial files

## 2. Implement chmod

- [x] 2.1 `SimulationCheckpoint.write_atomic` after rename: `os.chmod(path, 0o444)`
- [x] 2.2 `DayCheckpointWriter.write_partial` after rename: chmod 0o444
- [x] 2.3 `DayCheckpointWriter.write_day_summary` after rename: chmod 0o444
- [x] 2.4 `prune_snapshots`: `os.chmod(p, 0o644)` before unlink (defensive)

## 3. Regression
- [x] 3.1 existing snapshot / partial / summary tests pass — 5/5 new + 164/167 broader pass (3 pre-existing failures unrelated, MagicMock R5 start_date_anchor_iso)
- [x] 3.2 atomic write + prune e2e still works

## 4. Validate + archive

- [ ] 4.1 `openspec validate snapshot-write-protect-chmod --strict` — passing
- [ ] 4.2 archive after merge
