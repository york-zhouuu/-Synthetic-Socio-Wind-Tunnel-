## 1. TDD red — e2e tests

- [x] 1.1 `tests/test_ledger_anchor_drift.py`:
  - `test_snapshot_stores_start_date_anchor` — fresh write captures
    start_date in field
  - `test_legacy_snapshot_no_anchor_back_compat` — load v3 snapshot
    without anchor → no crash, no warning
  - `test_drift_detection_logs_warning` — write snapshot at
    ledger.current_time = day 0 23:00, anchor = day 0 00:00 →
    drift = 23h → resume SHALL log warning
  - `test_no_drift_no_warning` — ledger matches anchor + tick → silent
- [x] 1.2 Run → RED

## 2. Add `start_date_anchor_iso` to SimulationCheckpoint

- [x] 2.1 `state_snapshot.py:SimulationCheckpoint` add Field
  `start_date_anchor_iso: str | None = None` (back-compat)
- [x] 2.2 schema_version stays "3" (additive, optional field)

## 3. Populate on write + check on resume

- [x] 3.1 `MultiDayRunner._write_snapshot` thread start_date into
  SimulationCheckpoint constructor
- [x] 3.2 `run_multi_day` capture start_date in self for snapshot
  writer to access
- [x] 3.3 On resume (in restore_from branch), compute expected
  ledger.current_time and compare to actual; warn if diff > 1h

## 4. Regression

- [x] 4.1 Existing multi_day tests pass
- [x] 4.2 Existing snapshot tests pass

## 5. Validate + archive

- [x] 5.1 `openspec validate --strict`
- [x] 5.2 archive + commit + push
