## 1. TDD red — integration test

- [x] 1.1 新建 `tests/test_per_day_summary_across_resume.py` (5 tests:
  full_per_day_after_simulated_resume / summary_file_written_per_day /
  summary_survives_cleanup_partials / total_metrics_aggregate /
  malformed_summary_skipped). In-process two-runner pattern (faster,
  exercises same code path as subprocess).
- [x] 1.2 跑 → 红（hydration 没接前 5 tests 全红）

## 2. 实现 DayCheckpointWriter.write_day_summary

- [x] 2.1 在 `synthetic_socio_wind_tunnel/run_resilience/checkpoint.py`
  加 `write_day_summary(*, day_index, summary_dict, output_dir, seed)` —
  atomic JSON write to `seed_<N>_day<D>.summary.json` (tempfile +
  os.rename + fsync)
- [x] 2.2 加 `load_day_summaries(*, output_dir, seed)` —
  glob + load + sort by day_index; malformed file → log warning + skip

## 3. 实现 MultiDayRunner.run_multi_day hydrate + write

- [x] 3.1 在 run_multi_day after restore_from snapshot 之后、day loop
  之前 调用 `load_day_summaries`；reconstruct DayRunSummary
  via `_day_run_summary_from_dict`；filter `day_index <
  effective_start_day` 防止 double-append；同时 bump
  total_ticks / total_encounters
- [x] 3.2 在每个 day_end 之后 (after eviction patch on per_day[-1])
  调用 `write_day_summary(day_index, summary_dict=
  _day_run_summary_to_dict(per_day[-1]), output_dir, seed)`
- [x] 3.3 跑 G1 测试 → 全 5 转绿

## 4. 保护 cleanup_partials 不删 .summary.json

- [x] 4.1 `DayCheckpointWriter.cleanup_partials` glob 已经是
  `seed_*_day*.partial.json`（行为本来就对，加了 docstring 声明
  invariant）。tests/test_per_day_summary_across_resume.py 的
  `test_summary_survives_cleanup_partials` 守护这条不变量。

## 5. Regression

- [x] 5.1 既有 `tests/test_multi_day.py` (24/24) +
  `test_run_resilience_checkpoint.py` (10/10) +
  `test_dialogue_*.py` (13/13) 全绿
- [x] 5.2 全量 regression 暴露 2 个 false-positive failures:
  `test_run_variant_suite.py::test_two_variant_suite_produces_all_artifacts`
  和 `test_suite_wiring.py::test_seed_json_has_replan_extensions` —
  原因：naive `glob("seed_*.json")` 现在多匹配
  `seed_<N>_day<D>.summary.json`。Fix: 同步更新两个 test 用
  `^seed_\d+\.json$` regex 过滤，并对所有产线 `tools/*.py`
  audit / dashboard 脚本（preflight_full_smoke, audit_dwell,
  audit_realism_systemic, visualize_run, build_3d/2d/viz/evidence
  dashboards）做同样的修复——否则 publishable 跑完 audit 数据会
  错把 day-summary 当 seed 文件读。修复后两 test 转绿。

## 6. Spec validate + archive

- [x] 6.1 `openspec validate --strict` → "is valid"
- [ ] 6.2 archive + commit + push (待最终全量 regression 绿)
