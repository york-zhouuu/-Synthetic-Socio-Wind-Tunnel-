## ADDED Requirements

### Requirement: suite SHALL pin start_date via SUITE_ANCHOR.json

A publishable suite directory `<suite_dir>/` SHALL contain a
`SUITE_ANCHOR.json` file the FIRST time any variant in that suite
invokes `MultiDayRunner.run_multi_day`. The file's contents pin the
canonical start_date for ALL variants in the suite. Subsequent
variant spawns (and watchdog respawns) SHALL read this file and use
its `start_date_iso` as authoritative.

The anchor file format:
```json
{
  "start_date_iso": "2026-04-22",
  "num_days": 14,
  "created_at": "2026-05-21T01:23:45",
  "created_by_variant": "baseline"
}
```

#### Scenario: 第一次 spawn 写 SUITE_ANCHOR.json

- **GIVEN** `<suite_dir>` exists but contains no SUITE_ANCHOR.json
- **WHEN** `MultiDayRunner.run_multi_day(start_date=date(2026,4,22),
  num_days=14)` is called with `output_dir=<suite_dir>/variant_baseline`
- **THEN** `<suite_dir>/SUITE_ANCHOR.json` SHALL be created
- **AND** parsed JSON SHALL contain `start_date_iso == "2026-04-22"`
  and `num_days == 14`

#### Scenario: 第二个 variant 用同一 anchor 不报错

- **GIVEN** `<suite_dir>/SUITE_ANCHOR.json` exists with
  `start_date_iso = "2026-04-22"`
- **WHEN** `MultiDayRunner.run_multi_day(start_date=date(2026,4,22))`
  is called by `variant_hyperlocal_push`
- **THEN** no warning or error SHALL be logged about anchor mismatch

### Requirement: anchor 不匹配 SHALL log ERROR loud

`MultiDayRunner.run_multi_day` MUST log an ERROR-level message
identifying the discrepancy when a subsequent variant in the same
suite passes a `start_date` value that doesn't match the
SUITE_ANCHOR.json's `start_date_iso`. The runner SHALL continue
using the suite anchor's value (defensive: prevent the operator's
typo from breaking alignment).

#### Scenario: anchor 不匹配 → ERROR + 用 anchor 值

- **GIVEN** `<suite_dir>/SUITE_ANCHOR.json` has
  `start_date_iso = "2026-04-22"`
- **WHEN** `run_multi_day(start_date=date(2026,4,23))` is called
- **THEN** an ERROR-level log entry SHALL mention the mismatch
- **AND** internal `_start_date_anchor` SHALL be the SUITE_ANCHOR
  value (2026-04-22), NOT the caller's argument

### Requirement: corrupt anchor SHALL warn and proceed

`MultiDayRunner.run_multi_day` SHALL log a WARNING and treat the
anchor as absent (proceed with the caller's `start_date`) when
SUITE_ANCHOR.json exists but cannot be parsed (corrupted JSON,
missing fields). This avoids hard failure for one mis-written file.

#### Scenario: 损坏 anchor → 警告 + 继续

- **GIVEN** `<suite_dir>/SUITE_ANCHOR.json` contains garbage like
  "not json {{{"
- **WHEN** `run_multi_day(start_date=date(2026,4,22))` is called
- **THEN** a WARNING SHALL be logged about the unparseable anchor
- **AND** the runner SHALL proceed normally with the caller's start_date
- **AND** SHALL NOT overwrite the corrupt file (preserved for forensics)
