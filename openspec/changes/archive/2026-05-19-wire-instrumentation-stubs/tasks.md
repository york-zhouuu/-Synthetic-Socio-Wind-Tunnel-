## 1. TDD red — subprocess e2e dev smoke phase event order

- [x] 1.1 新建 `tests/test_phase_events_real_subprocess.py`:
  - `test_dev_smoke_emits_all_phase_events_in_order` (subprocess
    run + read events.jsonl + assert 7 phase events in correct order)
  - `test_setup_done_has_duration_and_rss_delta`
- [x] 1.2 跑 → 红 (wiring 缺失)

## 2. TDD red — subprocess e2e memstat sampling

- [x] 2.1 新建 `tests/test_memstat_real_subprocess.py`:
  - `test_dev_smoke_produces_memstat_samples`
    (subprocess dev smoke → memstat.jsonl 行数 ≥ 20)
  - `test_memstat_total_events_reflects_live_service`
  - `test_instrumentation_disable_skips_memstat`
- [x] 2.2 跑 → 红

## 3. 实现 memstat sampling wiring

- [x] 3.1 在 `synthetic_socio_wind_tunnel/orchestrator/multi_day.py::
  _init_memory_management_hooks._on_tick_end_memory` 加 sample_metrics
  调用：
  - 读 `INSTRUMENTATION_SAMPLE_EVERY_N_TICKS=12`
  - `if tick_global % sample_every == 0`: call
    `get_instrumentation().sample_metrics(...)`
  - 传 memory_service / dialogue_service / llm_tracker / sim_time
  - try/except 兜底
- [x] 3.2 跑 G2 测试 → 转绿

## 4. 实现 phase event wiring (SETUP_START / DONE)

- [x] 4.1 在 `tools/run_variant_suite.py` `_setup_aitown_stack`
  函数定义前后加 emit:
  - SETUP_START: emit 在调 _setup_aitown_stack 之前
  - SETUP_DONE: emit 在返回之后，含 duration_sec + rss delta
- [x] 4.2 跑 G1 子集 → SETUP 部分转绿

## 5. 实现 SNAPSHOT_LOAD_START / DONE wiring

- [x] 5.1 找到 `MultiDayRunner.run_multi_day` 内 snapshot restore 调用
  （StateSnapshotPolicy or similar）
- [x] 5.2 加 SNAPSHOT_LOAD_START emit 之前 + SNAPSHOT_LOAD_DONE emit
  之后（含 duration / rss delta / snapshot path / size）
- [x] 5.3 跑 G1 SNAPSHOT_LOAD 部分（仅 resume path）

## 6. 实现 TICK_LOOP_START wiring

- [x] 6.1 在第一个 `self._orchestrator.run(...)` call 之前加
  TICK_LOOP_START emit
- [x] 6.2 跑 G1 子集

## 7. 实现 DAY_START / DAY_END wiring

- [x] 7.1 在 `MultiDayRunner.run_multi_day` 每 day 循环开始 / 结束
  加 emit（DAY_START / DAY_END，含 day_index）
- [x] 7.2 跑 G1 完整

## 8. Regression

- [x] 8.1 跑既有 22 个 instrumentation test → 不退化
- [x] 8.2 跑既有 `tests/test_multi_day.py` → 不退化
- [x] 8.3 跑全量 1866+ test → 不退化

## 9. 文档更新

- [x] 9.1 CLAUDE.md `runtime-instrumentation` 段加注："9 个 PHASE event
  实际 wire 位置 + 验证方法"
- [x] 9.2 backlog 1.15 标记"phase wire 部分已修复"

## 10. Spec validate + archive

- [x] 10.1 `openspec validate wire-instrumentation-stubs --strict`
- [x] 10.2 tasks.md 全 [x]
- [x] 10.3 `openspec archive wire-instrumentation-stubs --yes`
- [x] 10.4 commit + push
