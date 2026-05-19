## 1. Dev deps（5 min）

- [x] 1.1 `pyproject.toml [project.optional-dependencies] dev` 加 `psutil`
- [x] 1.2 装 psutil 7.2.2 + verify API（this-process RSS = 16.5MB sanity）

## 2. TDD 红 — schema tests 先于 instrumentation 实现

- [x] 2.1 加 `tests/test_runtime_observability_schema.py`：3 个 DayRunSummary tests + 2 个 RSS schema handcrafted tests + 2 个 fixture present/valid tests
- [~] 2.2 mock-based tests 合并进 G6 fault injection（更聚焦）
- [~] 2.3 budget test 推迟到 G4
- [x] 2.4 跑 → 5/7 红（DayRunSummary 字段 + fixture 缺失），2/7 绿（handcrafted）

## 3. TDD 绿 — 实现 instrumentation

- [x] 3.1 `DayRunSummary` 加 8 个字段（rss_mb/vms_mb/event_count/dialogue_count/gc/p50/p95/max）+ `__slots__` 加 `_day_tick_latencies_ms`
- [x] 3.2 `MultiDayRunner._init_observability_hooks` + `_collect_day_end_observability`：per-tick latency hook + day_end snapshot；每个 metric 独立 try/except 不互相污染
- [x] 3.3 `run_multi_day` 调用 `_init_observability_hooks`（紧邻 memory_management）
- [x] 3.4 env `OBSERVABILITY_DISABLE=1` 跳过 hook（control 组）
- [x] 3.5 G2 DayRunSummary 字段测试 3/3 转绿；既有 multi_day 28/29 pass（1 skipped 不算）

## 4. TDD 绿 — Layer 4 budget test

- [x] 4.1 `test_runtime_observability_budget.py::test_instrumentation_overhead_within_budget` — 3 trials × 2 runs(off/on)，median ratio < 1.25× (dev scale)
- [x] 4.2 budget 绿。Per-tick hook 改成 sample-every-12-tick 把 overhead 从 37% 砍到 12.5%

## 5. RSS time-series harness（30 min）

- [x] 5.1 `tools/dump_runtime_observability.py` —— subprocess + psutil polling，~240ms 间隔采样
- [x] 5.2 fixture `tests/fixtures/rss_timeseries_dev_100agent_1day.json` 落 25 samples / 6s wall / 3KB
- [x] 5.3 schema tests 4/4 绿

## 6. Property-based + Fault injection

- [~] 6.1 property-based 跳过——`_collect_day_end_observability` 输出是 dict，不是 round-trip 候选；fault injection 覆盖度足
- [x] 6.2 `tests/test_runtime_observability_fault_injection.py` 9 tests：3 个 psutil 异常 / gc / memory_store / dialogue / 空 latency / 单 sample / normal path

## 7. 全量回归 + archive

- [ ] 7.1 `pytest tests/ --ignore=tests/test_hotfix_integration.py --ignore=tests/test_deepseek_tier_client.py -q --tb=line` 确认既有 1668+ 测试一个不少
- [ ] 7.2 `pytest tests/test_runtime_observability_*.py -v` 全绿
- [ ] 7.3 `openspec validate establish-observability-baselines` 通过
- [ ] 7.4 `openspec archive establish-observability-baselines`
- [ ] 7.5 commit（包括 1 个 RSS fixture + instrumentation 改动）
