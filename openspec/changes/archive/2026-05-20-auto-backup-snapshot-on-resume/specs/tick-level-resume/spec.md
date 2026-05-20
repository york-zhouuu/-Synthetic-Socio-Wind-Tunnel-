## ADDED Requirements

### Requirement: resume SHALL auto-backup existing snapshots

`MultiDayRunner.run_multi_day` SHALL copy all existing
`seed_<N>*.snapshot.json` files in `output_dir` to a subdirectory
`output_dir/.snapshot_backup_<YYYYMMDD_HHMMSS>/` when invoked with
`restore_from` set, before the tick loop begins (and therefore before
any `_write_snapshot` could fire).

Backup MUST be best-effort: if `mkdir` or `cp` fails for any reason
(disk full, permissions, etc.), the resume proceeds with a logged
warning. Backup failure SHALL NOT abort the resume.

The env var `RESILIENCE_SKIP_RESUME_BACKUP=1` MAY override and
disable the backup (for ad-hoc tests / known-clean environments).

#### Scenario: backup 在第一次 snapshot 写盘前完成

- **GIVEN** `output_dir` has `seed_42_pid100_tick120.snapshot.json`
- **WHEN** a new MultiDayRunner is constructed with restore_from set
  pointing to that snapshot, and `run_multi_day` starts
- **THEN** before any tick processing, a subdirectory matching
  `.snapshot_backup_*` SHALL exist in `output_dir`
- **AND** that subdirectory SHALL contain a copy of
  `seed_42_pid100_tick120.snapshot.json`
- **AND** the original file SHALL remain in `output_dir`

#### Scenario: backup 失败不阻塞 resume

- **GIVEN** `output_dir` is on a read-only filesystem (cannot mkdir)
- **WHEN** `MultiDayRunner.run_multi_day` is invoked with restore_from set
- **THEN** a warning SHALL be logged
- **AND** the run SHALL proceed normally (not abort)

#### Scenario: env override 关闭 backup

- **GIVEN** env `RESILIENCE_SKIP_RESUME_BACKUP=1` is set
- **WHEN** resume proceeds
- **THEN** no `.snapshot_backup_*` directory SHALL be created
