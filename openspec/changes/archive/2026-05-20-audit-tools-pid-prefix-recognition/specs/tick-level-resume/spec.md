## ADDED Requirements

### Requirement: audit tools SHALL recognize PID-prefixed snapshot filenames

`tools/audit_resume_strategies.py` MUST recognize both legacy and
PID-prefixed snapshot filename formats when scanning cell state:

- Legacy: `seed_<N>_tick<T>.snapshot.json`
- PID-prefixed: `seed_<N>_pid<PID>_tick<T>.snapshot.json`
- Graceful-stop final (both formats):
  `seed_<N>_tick_final.snapshot.json` and
  `seed_<N>_pid<PID>_tick_final.snapshot.json`

The recommended strategy + snapshot_ticks reporting SHALL include both
formats. Tick number extraction SHALL handle the `_pid<PID>_tick<T>`
pattern correctly (no false negatives).

#### Scenario: PID-prefixed snapshot detected

- **GIVEN** `<variant_dir>/seed_42_pid12345_tick120.snapshot.json` exists
- **WHEN** `audit_resume_strategies.py <suite> 42` runs
- **THEN** the JSON output for variant SHALL include
  `latest_snapshot_tick=120` (NOT null / missing)

#### Scenario: 混合 legacy + PID-prefixed 都被识别

- **GIVEN** `<variant_dir>` has both `seed_42_tick60.snapshot.json` and
  `seed_42_pid100_tick120.snapshot.json`
- **WHEN** audit runs
- **THEN** `snapshot_ticks` list SHALL contain both 60 AND 120
- **AND** `latest_snapshot_tick` SHALL be 120

#### Scenario: tick_final 也识别

- **GIVEN** `<variant_dir>/seed_42_pid100_tick_final.snapshot.json` exists
- **WHEN** audit runs
- **THEN** the audit SHALL detect it as the latest snapshot
  (treated as highest authority for graceful_stop semantics)
