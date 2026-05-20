## 1. TDD red — e2e test

- [x] 1.1 `tests/test_resume_auto_backup.py`:
  - `test_backup_dir_created_before_first_snapshot_write` —
    pre-existing snapshot file → resume → backup dir exists with
    copy of pre-existing file BEFORE any new snapshot written
  - `test_backup_failure_doesnt_block_resume` — backup helper raises
    OSError → resume still proceeds, warning logged
  - `test_env_skip_resume_backup_disables` — env=1 → no backup created
- [x] 1.2 Run → RED

## 2. Implement helper

- [x] 2.1 `MultiDayRunner._backup_snapshots_before_resume(output_dir)`:
  - if no `seed_*.snapshot.json` files → no-op
  - else: mkdir `output_dir/.snapshot_backup_<YYYYMMDD_HHMMSS>/`
  - cp all matching files (shutil.copy2 preserves mtime)
  - try/except OSError → log warning + return False (don't block)
  - check env `RESILIENCE_SKIP_RESUME_BACKUP=1` → early return

## 3. Wire into resume path

- [x] 3.1 In `run_multi_day`, when `restore_from is not None`, call
  `_backup_snapshots_before_resume` BEFORE entering tick loop /
  before any `_write_snapshot` could fire
- [x] 3.2 G1 tests → GREEN

## 4. Regression

- [x] 4.1 Existing multi_day tests pass
- [x] 4.2 Existing snapshot/checkpoint tests pass

## 5. Validate + archive
- [x] 5.1 `openspec validate --strict`
- [x] 5.2 archive + commit + push
