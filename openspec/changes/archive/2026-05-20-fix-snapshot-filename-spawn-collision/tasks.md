## 1. TDD red — e2e bug-capture test

- [x] 1.1 `tests/test_snapshot_filename_no_collision.py`:
  - `test_two_spawns_dont_collide`: write snapshot from "spawn A" at
    tick 12, kill, then "spawn B" writes at its own internal tick 12 →
    assert both files exist + content distinguishable
  - `test_find_latest_picks_newest_mtime`: 3 files (mix of legacy + new
    format) → assert latest by mtime returned
  - `test_legacy_format_still_resumable`: write a legacy-named file →
    assert find_latest_snapshot returns it
  - `test_prune_by_mtime_keeps_newest`: 5 snapshots, keep=2 → assert 2
    newest-by-mtime remain
- [x] 1.2 Run tests → all RED (current code overwrites + selects by tick)

## 2. Implement filename change

- [x] 2.1 `state_snapshot.snapshot_path(output_dir, *, seed,
  tick_index_global, spawn_id=None)` — when spawn_id provided, output
  `seed_<N>_pid<spawn_id>_tick<T>.snapshot.json`; when None (back-compat
  default), output legacy `seed_<N>_tick<T>.snapshot.json`
- [x] 2.2 `find_latest_snapshot` parses BOTH formats — uses regex
  `seed_<N>(_pid<PID>)?_tick<T>.snapshot.json`; selection = latest mtime
- [x] 2.3 `prune_snapshots` selection = oldest mtime; keep newest K

## 3. Thread spawn_id through callers

- [x] 3.1 `MultiDayRunner.__init__` — store `self._spawn_id = os.getpid()`
- [x] 3.2 `MultiDayRunner._write_snapshot` — pass `spawn_id=self._spawn_id`
  to `snapshot_path()`
- [x] 3.3 `MultiDayRunner._write_final_snapshot_on_graceful_stop` — same
- [x] 3.4 Run G1 tests → green

## 4. Regression on existing tests

- [x] 4.1 `tests/test_run_resilience_*.py` — should pass without change
  (legacy callers still work since spawn_id defaults to None)
- [x] 4.2 `tests/test_simulation_checkpoint.py` — pass
- [x] 4.3 `tests/test_find_latest_snapshot_tick_final.py` — pass (tick_final
  handling preserved)
- [x] 4.4 `tests/test_multi_day.py` — pass

## 5. Spec validate + archive

- [x] 5.1 `openspec validate --strict`
- [x] 5.2 archive + commit + push
