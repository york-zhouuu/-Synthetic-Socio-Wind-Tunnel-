## 1. TDD red

- [x] 1.1 新建 `tests/test_find_latest_snapshot_tick_final.py`:
  - `test_tick_final_preferred_when_newer`
  - `test_numeric_wins_when_tick_final_is_stale`
  - `test_only_numeric_pick_highest_tick` (regression)
  - `test_only_tick_final_present_picks_it`
  - `test_no_snapshots_returns_none` (regression)
- [x] 1.2 跑 → 红

## 2. 实现

- [x] 2.1 `find_latest_snapshot` 加 tick_final 候选 + mtime tiebreak
- [x] 2.2 跑测试 → 转绿

## 3. Regression + archive

- [x] 3.1 跑既有 `tests/test_run_resilience_checkpoint.py` / 相关
- [x] 3.2 archive + commit + push
