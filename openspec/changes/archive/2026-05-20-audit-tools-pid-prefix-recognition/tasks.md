## 1. TDD red

- [x] 1.1 `tests/test_audit_resume_strategies_pid_prefix.py`:
  - `test_pid_prefixed_snapshots_detected` — drop
    `seed_42_pid100_tick12.snapshot.json` → audit reports
    latest_snapshot_tick=12
  - `test_legacy_snapshots_still_detected` — drop
    `seed_42_tick12.snapshot.json` (no PID) → audit still works
  - `test_mixed_legacy_and_pid_prefix_both_seen` — both → both detected
  - `test_tick_final_detected` — drop
    `seed_42_pid100_tick_final.snapshot.json` → audit treats as latest

## 2. Update audit_resume_strategies

- [x] 2.1 Replace glob+rsplit with regex
  `seed_<N>(_pid\d+)?_tick(\d+|_final).snapshot.json`
- [x] 2.2 Tick parsing: `_final` → special-cased (highest authority)

## 3. Regression

- [x] 3.1 existing audit_resume_strategies tests still pass

## 4. Validate + archive
