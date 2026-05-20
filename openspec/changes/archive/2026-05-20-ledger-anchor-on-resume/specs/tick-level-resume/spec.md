## ADDED Requirements

### Requirement: snapshot SHALL carry start_date anchor

`SimulationCheckpoint` SHALL include an optional field
`start_date_anchor_iso: str | None` carrying the ISO-format date
that was passed as `start_date` when `MultiDayRunner.run_multi_day`
was first invoked for this seed/variant. This anchor is preserved
across resume so any subsequent worker can detect whether the
`ledger.current_time` field has drifted away from the
`(start_date_anchor + day_index * 24h + tick_index * 5min)` expected
value.

Legacy snapshots that lack the anchor field SHALL be readable
without error (back-compat). When anchor is None, drift detection
SHALL be skipped.

#### Scenario: 写盘时填 start_date_anchor

- **GIVEN** `run_multi_day(start_date=date(2026,4,22))` is in progress
- **WHEN** `_write_snapshot` fires
- **THEN** the resulting `SimulationCheckpoint` SHALL have
  `start_date_anchor_iso == "2026-04-22"`

#### Scenario: 读老 snapshot 没 anchor 不报错

- **GIVEN** a v3 snapshot JSON file with NO `start_date_anchor_iso` key
- **WHEN** `SimulationCheckpoint.read(path)` is called
- **THEN** the object SHALL load successfully with
  `start_date_anchor_iso = None`

### Requirement: resume SHALL detect ledger drift and warn

`MultiDayRunner.run_multi_day` on the `restore_from` path SHALL
compute the expected `ledger.current_time` from
`(start_date_anchor + snap.day_index * 24h + snap.tick_index * 5min)`
and compare to the actual `snap.ledger_state.current_time`. If the
drift exceeds 1 hour, the runner SHALL log a WARNING with the
specific drift amount in hours/minutes — this gives the operator an
early signal of the calendar misalignment cascade observed in the
2026-05-20 scout.

The check is best-effort: missing fields → silently skip.
The check is purely detective (does NOT auto-correct).

#### Scenario: 23h drift 触发 warning

- **GIVEN** snapshot with day_index=0, tick_index=0,
  start_date_anchor_iso="2026-04-22",
  but ledger.current_time = "2026-04-22T23:00:00"
- **WHEN** MultiDayRunner.run_multi_day resumes from this snapshot
- **THEN** a WARNING log SHALL be emitted mentioning "ledger drift"
  (or equivalent) with the 23-hour drift amount

#### Scenario: 同步无 drift 不告警

- **GIVEN** snapshot with day_index=0, tick_index=12,
  start_date_anchor_iso="2026-04-22",
  ledger.current_time = "2026-04-22T01:00:00" (= 12 ticks × 5min)
- **WHEN** resume proceeds
- **THEN** NO drift warning SHALL be emitted
