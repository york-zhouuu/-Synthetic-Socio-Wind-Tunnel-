## Why

R4 detects per-variant ledger drift. But thesis-grade contest needs
ALL variants in a seed to share the SAME `start_date` anchor.
Without a suite-level pinned anchor, each variant could be spawned
(by user error or watchdog respawn) with a slightly different
`--start-date` argument, leading to silent calendar misalignment
across variants — exactly what destroyed the β=1 scout.

## What Changes

- Suite-level anchor file: `<suite_dir>/SUITE_ANCHOR.json` written
  on first variant spawn within a suite, with `{start_date_iso,
  num_days, created_at, created_by_variant}` fields
- `MultiDayRunner.run_multi_day` SHALL:
  - on first variant spawn (no SUITE_ANCHOR.json) → write the anchor
  - on subsequent variants / resume → read SUITE_ANCHOR.json and
    verify the current `start_date` arg matches; if mismatch → log
    ERROR (loud) and proceed only after warning
- R4's drift check now ALSO cross-references the suite anchor, so a
  variant resumed via watchdog inherits the correct start_date for
  drift computation even if the caller passed a different value

## Capabilities

### Modified Capabilities

- `tick-level-resume`: suite-level anchor file SHALL be authoritative
  for cross-variant start_date alignment

## Impact

**Affected code**:
- `synthetic_socio_wind_tunnel/orchestrator/multi_day.py`
  (read/write SUITE_ANCHOR.json on run_multi_day entry)

**Affected behavior**:
- First variant spawn writes SUITE_ANCHOR.json (~1KB)
- Subsequent variants verify anchor match → silent if aligned, ERROR if not
- Watchdog respawn → resume inherits SUITE_ANCHOR's start_date even
  if caller's CLI arg differs (defensive)

**Non-goals**:
- NOT coordinating tick-level synchronization between variants (each
  still runs independently)
- NOT touching contest builder's existing alignment detection
  (that was added 2026-05-21)
