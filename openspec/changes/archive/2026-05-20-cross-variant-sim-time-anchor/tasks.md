## 1. TDD red — tests

- [x] 1.1 `tests/test_suite_anchor.py`:
  - `test_first_variant_writes_anchor` — fresh suite + first
    run_multi_day call → SUITE_ANCHOR.json exists with right fields
  - `test_second_variant_with_matching_anchor_silent` — anchor exists
    matching → no warning/error logged
  - `test_second_variant_with_mismatched_anchor_logs_error` — anchor
    says 2026-04-22, caller passes 2026-04-23 → ERROR logged
  - `test_corrupt_anchor_logs_warning_proceeds` — anchor.json broken →
    warning + proceed (treat as no anchor)
- [x] 1.2 Run → RED

## 2. Implement helper

- [x] 2.1 `MultiDayRunner._read_or_write_suite_anchor(suite_dir,
  start_date, num_days)`:
  - if anchor file exists + parseable → return its date + compare
    to caller's; if mismatch → log ERROR; return anchor's date
  - if absent → write anchor + return caller's date
  - if corrupt → log warning + return caller's date (no fail)
- [x] 2.2 Call at top of `run_multi_day` (suite_dir = output_dir.parent
  since output_dir is `<suite>/variant_<v>/`)

## 3. Wire

- [x] 3.1 `run_multi_day` invokes the helper; use returned canonical
  start_date for `_start_date_anchor` (so R4 drift uses suite anchor)

## 4. Regression

- [x] 4.1 multi_day + anchor + drift tests all pass

## 5. Validate + archive
