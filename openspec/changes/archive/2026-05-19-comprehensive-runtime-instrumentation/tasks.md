## 1. TDD red — RuntimeInstrumentation module + JSONL output

- [x] 1.1 新建 `tests/test_runtime_instrumentation_basic.py`:
  - `test_get_instrumentation_creates_3_jsonl_files`
  - `test_instrumentation_disable_returns_noop_stub`
  - `test_reset_for_tests_closes_files`
  - `test_failure_isolation_emit_event_does_not_raise_on_io_error`
- [x] 1.2 跑 → 红（module 不存在）

## 2. TDD red — memstat schema + RSS correctness

- [x] 2.1 新建 `tests/test_memstat_real_measurement.py`（不 mock 关键值）:
  - `test_rss_mb_uses_psutil_current_not_ru_maxrss` (核心 bug 修复
    验证：alloc 500MB → free + gc → 再 sample, rss_mb SHALL < rss_peak_mb)
  - `test_rss_mb_matches_psutil_independently` (独立读 psutil 比对)
  - `test_memstat_schema_has_all_documented_top_level_keys`
  - `test_sample_cadence_respects_env_n_ticks`
- [x] 2.2 跑 → 红

## 3. TDD red — phase event ordering

- [x] 3.1 新建 `tests/test_phase_events_order.py`:
  - `test_phase_events_fire_in_correct_order_dev_smoke` (50 agent ×
    1 day 真跑，verify events.jsonl 顺序)
  - `test_atexit_emits_exit_on_crash` (mock crash + verify EXIT event
    在 events.jsonl 最后一行)
  - `test_no_duplicate_phase_events_single_run`
- [x] 3.2 跑 → 红

## 4. TDD red — eviction event values

- [x] 4.1 新建 `tests/test_eviction_event_real.py`:
  - `test_evict_event_values_match_real_store_delta` (构造 memory_store
    含 100 encounter，触发 eviction with cutoff → 30 events evicted →
    EVICT event 的 events_evicted == 30 且 before-after delta == 30)
  - `test_evict_event_rss_delta_recorded`
- [x] 4.2 跑 → 红

## 5. TDD red — retry event per-attempt

- [x] 5.1 新建 `tests/test_retry_event_per_attempt.py`:
  - `test_retry_event_emits_per_failed_attempt_not_at_exhaustion`
    (mock op 抛真 openai.APIConnectionError 2 次 + 成功 → 恰好 2 个
    RETRY events，每个带 backoff_sec)
  - `test_no_retry_event_on_first_success`
  - `test_exhausted_emits_max_attempts_minus_1_retry_events`
- [x] 5.2 跑 → 红

## 6. TDD red — LLM event sampling

- [x] 6.1 新建 `tests/test_llm_event_sampling.py`:
  - `test_success_calls_sampled_at_default_rate` (10000 success →
    100 ± 30 rows in llm.jsonl)
  - `test_error_calls_100_percent_recorded_regardless_of_sample_rate`
    (LLM_SAMPLE_RATE=0.001 + 1000 fallback → 1000 rows)
  - `test_llm_event_schema_has_documented_fields`
- [x] 6.2 跑 → 红

## 7. TDD red — snapshot write event

- [x] 7.1 新建 `tests/test_snapshot_write_event.py`:
  - `test_snapshot_write_event_captures_size_and_rss_delta` (真写一个
    snapshot，verify SNAPSHOT_WRITE event 的 size_bytes == os.path.getsize
    + rss_peak_during_mb >= rss_before_mb)
  - `test_snapshot_write_event_duration_positive`
- [x] 7.2 跑 → 红

## 8. 实现 RuntimeInstrumentation 核心

- [x] 8.1 新建 `synthetic_socio_wind_tunnel/observability/__init__.py`
  (re-export RuntimeInstrumentation + get_instrumentation +
  reset_for_tests)
- [x] 8.2 新建 `synthetic_socio_wind_tunnel/observability/instrumentation.py`:
  - `RuntimeInstrumentation` dataclass / class
  - `from_env()` 静态构造（读 INSTRUMENTATION_* env）
  - `_open_files()`: 3 JSONL files line-buffered
  - `emit_event(kind, **kw)`: append events.jsonl，try/except 兜底
  - `emit_llm_call(...)`: sampling logic (success vs error)
  - `sample_metrics(tick_global, day_index, tick_in_day)`: memstat
    sample using psutil + gc + handler stats
  - `shutdown(reason)`: final EXIT event + close files
  - atexit register
  - `_NoOpStub` class for INSTRUMENTATION_DISABLE=1
  - module-level `_GLOBAL` + `get_instrumentation()` +
    `reset_for_tests()`
- [x] 8.3 跑 G1 测试 → 转绿

## 9. 实现 memstat sampling + 修 _self_rss_mb

- [x] 9.1 在 `synthetic_socio_wind_tunnel/orchestrator/multi_day.py`:
  - 重命名 `_self_rss_mb` → `_current_rss_mb`，改用 psutil
    `memory_info().rss`，ru_maxrss 仅 fallback
  - 更新既有 2 个调用点 (`[gc]` log line + RSS cap check)
  - 在 `_init_memory_management_hooks` hook 内调用
    `get_instrumentation().sample_metrics(tick_global, day_index, tick_in_day)`
    每 `INSTRUMENTATION_SAMPLE_EVERY_N_TICKS=12` tick
- [x] 9.2 跑 G2 测试 → 转绿
- [x] 9.3 跑既有 `tests/test_run_resilience_*.py` → regression 不动

## 10. 实现 phase event 桩点

- [x] 10.1 在 `synthetic_socio_wind_tunnel/observability/instrumentation.py`
  module level: `from_env()` 第一次调用时 emit `PROCESS_START` event
  + register atexit `EXIT` hook
- [x] 10.2 在 `tools/run_variant_suite.py::_setup_aitown_stack` 前后
  emit `SETUP_START` / `SETUP_DONE`
- [x] 10.3 在 `MultiDayRunner.run_multi_day` 内：
  - resume from snapshot 前 emit `SNAPSHOT_LOAD_START` + 后
    `SNAPSHOT_LOAD_DONE`（含 rss_before/after + duration）
  - 第一个 tick 前 emit `TICK_LOOP_START`
  - 每 day_start/day_end hook emit `DAY_START` / `DAY_END`
  - finally + atexit emit `EXIT`
- [x] 10.4 跑 G3 测试 → 转绿

## 11. 实现 eviction event 桩点

- [x] 11.1 在 `synthetic_socio_wind_tunnel/memory/service.py::
  evict_cold_encounter_events_across_agents` 调用前后量 size +
  emit EVICT event
- [x] 11.2 跑 G4 测试 → 转绿

## 12. 实现 retry event 桩点

- [x] 12.1 在 `tools/tier_llm_factory.py::_run_with_retry` 每次 except
  retryable 时 emit RETRY event（含 tier / provider / key_id /
  attempt / exc_class / backoff_sec）
- [x] 12.2 跑 G5 测试 → 转绿

## 13. 实现 LLM call 桩点 + sampling

- [x] 13.1 在 `tools/tier_llm_factory.py` 每个 tier client (`generate`
  方法) 调用 `_run_with_retry` 完成后 emit_llm_call (success path) +
  捕捉 `_run_with_retry` exhausted 时也 emit_llm_call (status=
  "exhausted")。do_something handler 内的 fallback 路径 emit
  status="fallback".
- [x] 13.2 跑 G6 测试 → 转绿

## 14. 实现 snapshot write event 桩点

- [x] 14.1 找到 snapshot 写盘代码（`MultiDayRunner` 内
  `_write_snapshot` 或等价），wrap with timing + rss before/after
  measure + emit SNAPSHOT_WRITE event
- [x] 14.2 跑 G7 测试 → 转绿

## 15. 工具：tail_memstat + analyze_memstat

- [x] 15.1 新建 `tools/tail_memstat.py`:
  - 实时 tail memstat.jsonl + 滚动统计（最近 N=5 min）：rss avg/max,
    cpu avg, events/min, llm fallback rate
  - 简单 print 格式（不引 rich/textual 依赖）
- [x] 15.2 新建 `tools/analyze_memstat.py`:
  - 离线读 memstat.jsonl + events.jsonl + llm.jsonl
  - 输出 Markdown report：phase timeline, RSS 曲线 ascii sparkline,
    LLM 失败率分布, eviction 释放总量, handler 耗时分布
- [x] 15.3 新建 `tests/test_tail_analyze_tools.py`:
  - construct synthetic memstat.jsonl/events.jsonl + run tools
  - assert tool outputs key signals

## 16. Regression: 既有测试不退化

- [x] 16.1 跑既有 1812+ test suite → 全绿
- [x] 16.2 既有 17 个 RSS cap mock-tests 不动（测的是机制不是值）
- [x] 16.3 既有 `test_runtime_observability_*.py` 不退化

## 17. E2E 验证（真跑）

- [x] 17.1 dev smoke 50 agent × 1 day 跑通：3 JSONL 文件存在 + log
  里有 `[memstat]` / `[evict]` / `[retry]` 行
- [x] 17.2 publishable resume single cell (s42/phone_friction)
  spawn 60s 后停（手动测试，不全跑完）：events.jsonl 应有
  PROCESS_START、SETUP_START、SETUP_DONE，SNAPSHOT_LOAD_START 出现；
  memstat.jsonl 至少有 1 个 sample；EXIT event 在 final line
- [x] 17.3 实测 `tail_memstat.py` 在 dev smoke 期间能看到 rolling
  stats

## 18. 文档

- [x] 18.1 更新 CLAUDE.md：加 `runtime-instrumentation` 不变量段
  （JSONL schema + 桩点位置 + env vars）
- [x] 18.2 更新 `tools/resume_publishable.py` docstring 提到
  instrumentation 输出

## 19. Spec validate + archive

- [x] 19.1 `openspec validate comprehensive-runtime-instrumentation --strict`
- [x] 19.2 tasks.md 全部 checkbox → [x]
- [x] 19.3 `openspec archive comprehensive-runtime-instrumentation --yes`
- [x] 19.4 commit + push
