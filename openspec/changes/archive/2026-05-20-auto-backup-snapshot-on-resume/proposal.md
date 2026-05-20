## Why

R1 (PID-prefixed filenames) prevents same-tick filename collision, but
doesn't protect against accidental overwrite when an operator runs a
diag/ad-hoc resume from production state. Belt-and-suspenders: on
`--resume`, automatically backup the existing snapshot dir contents
BEFORE any new snapshot writes.

2026-05-20 lesson: the baseline scout snapshot was lost when a manual
`--resume` from `seed_43_tick276.snapshot.json` ran for 30 min,
hitting tick 276 again internally and overwriting. Even though R1 fix
prevents same-PID collision, there is no mechanism that copies the
existing snapshots aside before a new run starts.

## What Changes

- `MultiDayRunner.run_multi_day` on resume (when `restore_from` is set
  OR `--resume` flag passed) SHALL invoke a backup routine BEFORE any
  new snapshot is written
- Backup copies all `seed_<N>*.snapshot.json` files from `output_dir`
  to `output_dir/.snapshot_backup_<timestamp>/`
- Backup is best-effort: failure logs warning but doesn't block resume
- A regression test verifies backup happens before tick 12's first
  snapshot write
- New env `RESILIENCE_SKIP_RESUME_BACKUP=1` lets ad-hoc tests bypass

## Capabilities

### Modified Capabilities

- `tick-level-resume`: resume path SHALL backup existing snapshots
  before any new write

## Impact

**Affected code**:
- `synthetic_socio_wind_tunnel/orchestrator/multi_day.py`
  (add `_backup_snapshots_before_resume` helper called in
  `run_multi_day` on restore_from path)

**Affected behavior**:
- Disk: each resume creates a backup dir ~600MB-1GB (size of all
  snapshots). Acceptable; auto-prune backups older than 7 days
  optional follow-up
- Resume time: +1-2s for backup cp before tick loop starts

**Non-goals**:
- Not automating backup of WAL / events / memstat (separate concern)
- Not implementing backup retention policy (manual cleanup)
- Not protecting against external `rm` (filesystem-level)
