## 1. Schema 测试先于 harness 实现（TDD 红）

- [x] 1.1 加 `tests/test_hot_path_profile_schema.py` handcrafted validator + 2 个 handcrafted tests（valid case + reject unsorted）
- [x] 1.2 加 `TestFixturePresent::test_fixture_file_exists`（红——fixture 还没）
- [x] 1.3 加 `TestFixturePresent::test_fixture_satisfies_schema`（红——fixture 还没）
- [x] 1.4 跑 `pytest tests/test_hot_path_profile_schema.py -v` → 3 fail (fixture-related) + 2 pass (handcrafted) ← TDD 红阶段完成

## 2. Regression test 先于 fixture 落地（TDD 红）

- [x] 2.1 加 `tests/test_hot_path_baseline_regression.py::test_top_3_functions_match_baseline` (slow)
- [x] 2.2 加 hand-crafted `test_top_3_diff_yields_readable_error`（默认 CI 跑）
- [x] 2.3 加 `test_wall_clock_within_budget` (slow) + `test_wall_clock_*` 两个 logic tests
- [x] 2.4 `pyproject.toml [tool.pytest.ini_options]` 注册 `slow` marker

## 3. Harness 实现（TDD 绿）

- [x] 3.1 写 `tools/profile_publishable_smoke.py` CLI
- [x] 3.2 用 `pstats.Stats` 抽 cumulative + call_count + 降序 top-N
- [x] 3.3 归一化 qualname（module:fn，去 site-packages 噪音）
- [x] 3.4 输出 JSON 符合 schema + `cprofile_overhead_pct_estimate`
- [x] 3.5 50-agent dry-run 验证 harness 跑通

## 4. Fixture 生成 + commit（TDD 绿）

- [x] 4.1 跑 `--agents 100 --seed 42` 落 `tests/fixtures/hot_path_profile_baseline.json`（9.4s, 7KB）
- [x] 4.2 fixture <100KB ✓ schema 合法 ✓ top-3 meaningful 是 `process_tick / events_at_tick / <listcomp>` 信号合理
- [x] 4.3 `git add` 已规划在 commit phase
- [x] 4.4 schema tests 5/5 转绿 ← TDD 绿确认

## 5. 判读文档（人脑分析）

- [x] 5.1 top-10 每条写"为什么慢"
- [x] 5.2 每条评估优化 ROI：`yes-high-roi` / `yes-low-roi` / `unclear-need-more-data` 等
- [x] 5.3 三条明确结论：
  - ① backlog 1.14 KD-tree 假设**完全推翻**——encounter detection 非 Euclidean，scipy 用不上
  - ② 下一个候选：`memory.service:events_at_tick` O(N) → O(1) dict index
  - ③ unclear：dev 100 vs publishable 1000 hot-path 是否重排；process_tick self vs children time
- [~] 5.4 火焰图（py-spy 可选）跳过——3 条结论已经足够 narrow next-change scope

## 6. 全量回归 + archive

- [ ] 6.1 跑 `pytest tests/ -q --tb=line --ignore=...test_hotfix_integration.py` 确认既有 test 不回退
- [ ] 6.2 跑 `pytest -m slow` 验证 regression guard（slow path）
- [ ] 6.3 `openspec validate profile-publishable-hot-path` 通过
- [ ] 6.4 `openspec archive profile-publishable-hot-path`
- [ ] 6.5 commit message 引用 5.3 三条结论
