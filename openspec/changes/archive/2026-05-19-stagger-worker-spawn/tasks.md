## 1. TDD 红 — spawn-stagger guard unit tests

- [x] 1.1 新建 `tests/test_spawn_stagger_guard.py`：
  - `test_first_spawn_allowed_when_no_timestamp_file`
  - `test_second_spawn_within_window_deferred`
  - `test_second_spawn_after_window_allowed`
  - `test_corrupted_timestamp_file_falls_back_to_allow`
  - `test_clock_backward_resets_timestamp`
  - `test_env_zero_disables_guard`
- [x] 1.2 跑 → 红（guard 函数还不存在）

## 2. TDD 红 — multi-cell serial selection unit tests

- [x] 2.1 新建 `tests/test_resume_publishable_multi_cell_order.py`：
  - `test_4_interrupted_cells_only_first_spawned_dict_order`
  - `test_deferred_cells_get_correct_report_action`
  - `test_deferred_cells_logged_with_next_eligible_time`
  - `test_subsequent_run_picks_up_remaining_cells`
- [x] 2.2 跑 → 红

## 3. TDD 红 — ThreadPool staggered submit integration test

- [x] 3.1 新建 `tests/test_run_variant_suite_staggered_submit.py`：
  - `test_4_workers_submitted_with_spacing` (mock subprocess.Popen，
    断言 4 个 call 的时间差 ~ spacing)
  - `test_env_zero_threadpool_no_sleep`
  - `test_threadpool_sleep_chunks_check_graceful_stop`
- [x] 3.2 跑 → 红

## 4. TDD 红 — timestamp atomic write fault injection

- [x] 4.1 新建 `tests/test_spawn_timestamp_atomic_write.py`：
  - `test_atomic_write_via_tempfile_rename` (mock OSError on rename →
    fallback gracefully)
  - `test_concurrent_read_during_write_sees_old_or_new_never_partial`
    (用 threading.Barrier 模拟并发，verify 读到的总是 valid JSON)
  - `test_disk_full_during_write_logs_and_continues` (mock OSError
    on write → spawn 不被卡死)
- [x] 4.2 跑 → 红

## 5. 实现 stagger guard 核心

- [x] 5.1 在 `tools/resume_publishable.py` 加 helper:
  - `_read_last_spawn_timestamp() -> dict | None`
  - `_write_last_spawn_timestamp(cell: dict) -> None` (atomic via
    tempfile + rename)
  - `_spawn_allowed_now(min_spacing_secs: int) -> tuple[bool,
    float, str]` (returns (allowed, seconds_until_next_eligible,
    reason))
- [x] 5.2 修改 `_spawn_resume_worker` 调用前先查 guard；deferred
  时返回 special sentinel (e.g. `("deferred", next_eligible_iso)`)
  而不是 PID
- [x] 5.3 修改主循环遇到 INTERRUPTED cell 时：
  - 检查 spacing → 若 deferred，entry["action"] =
    "deferred_due_to_stagger" + entry["next_eligible_iso"]
  - 若 allowed，spawn + 写 timestamp → entry["action"] = "spawn_resume"
- [x] 5.4 argparse 加 `--min-spawn-spacing-secs INT` (默认 300)
- [x] 5.5 跑 G1-G2 tests 转绿

## 6. 实现 run_variant_suite ThreadPool stagger

- [x] 6.1 修改 `tools/run_variant_suite.py` worker pool 路径
  (`_run_worker` submit 循环):
  - 读 `RESILIENCE_MIN_SPAWN_SPACING_SECS` (默认 300, ad-hoc 用户
    可设 0)
  - 在 `for i, v in enumerate(variants): pool.submit(...)` 间插入
    chunked `time.sleep` (1s × spacing)
  - sleep chunk 内检查 graceful_stop flag (复用 multi_day.py
    现有 pattern)
- [x] 6.2 跑 G3 tests 转绿

## 7. 文档更新

- [x] 7.1 修改 `CLAUDE.md` `snapshot-resume-ram-peak` 段：
  - 加 "LLM API burst self-DDoS" 视角，标注 2026-05-19 23:00+ 二次
    取证发现
  - 把 "current implementation does NOT stagger" 改成 "stagger now
    enforced in `_spawn_allowed_now()`, default 5 min, env
    `RESILIENCE_MIN_SPAWN_SPACING_SECS`"
- [x] 7.2 修改 `tools/resume_publishable.py` 顶部 docstring 反映
  stagger 已实施 + 移除 "Current implementation does NOT stagger"
  那段警告

## 8. Regression: 全量测试不回退

- [x] 8.1 跑 `pytest tests/ -q --ignore=tests/test_event_to_json_performance.py`
- [x] 8.2 验证 D2 attempt 6 reproduce 工具（如果有）—— 至少手动
  验证：spawn 4 cell 时序 staggered

## 9. E2E 验证

- [x] 9.1 `python tools/resume_publishable.py --dry-run` 模拟 4
  INTERRUPTED cell → log 应看到 1 spawn + 3 deferred
- [x] 9.2 `RESILIENCE_MIN_SPAWN_SPACING_SECS=0
  python tools/run_variant_suite.py --workers 4 --variants
  baseline,hyperlocal_push,phone_friction,global_distraction
  --seeds 1 --num-days 1 --agents 50 --mode dev` smoke run，验证
  rollback path 有效（env=0 → 立刻 spawn）

## 10. Spec validate + archive

- [x] 10.1 `openspec validate stagger-worker-spawn --strict`
- [x] 10.2 tasks.md 全部 checkbox 改为 [x]
- [x] 10.3 `openspec archive stagger-worker-spawn --yes`
- [x] 10.4 commit + push (retry-network-blip-tolerance proposal 已
  改 framing，一并 stage)
