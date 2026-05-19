## 1. TDD red

- [x] 1.1 新建 `tests/test_check_publishable_integrity_glob.py`：
  - `test_glob_excludes_positions_file`
  - `test_glob_excludes_snapshot_file`
  - `test_glob_excludes_partial_file`
  - `test_glob_includes_seed_42_dot_json`
- [x] 1.2 跑 → 红

## 2. 实现

- [x] 2.1 改 `_load_seed_files` 把 `glob("seed_*.json")` 换成 regex
  filter `^seed_\d+\.json$`
- [x] 2.2 跑测试 → 转绿

## 3. 验证 + archive

- [x] 3.1 在真 D2 suite 上跑 checker → error 数大幅下降
- [x] 3.2 跑 regression
- [x] 3.3 `openspec validate --strict` + archive + commit + push
