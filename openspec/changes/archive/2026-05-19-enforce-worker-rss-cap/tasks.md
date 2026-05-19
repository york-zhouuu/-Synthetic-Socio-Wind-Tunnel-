## 1. TDD 红 — encounter eviction unit tests 先于实现

- [x] 1.1 新建 `tests/test_memory_store_encounter_eviction.py`：
  - test_evict_only_encounter (其它 kind 保留)
  - test_evict_full_empty_legal (全删后 store 合法)
  - test_evict_empty_store_no_op
- [x] 1.2 新建 `tests/test_memory_service_cross_agent_evict.py`：
  - test_cross_agent_accumulates_count
  - test_idempotent_same_cutoff
- [x] 1.3 跑 → 红（方法不存在，AttributeError）

## 2. TDD 红 — bounded growth property test

- [x] 2.1 新建 `tests/test_memory_event_eviction_property.py`：
  - hypothesis 生成 random (N agents, N events / agent / tick) sequence
  - 跑 N simulated days，每 day_end evict
  - assert total event_count never > (cap_days × ticks_per_day × agents)
  - assert eviction monotone (一旦 evict 永不复活)
- [x] 2.2 跑 → 红

## 3. TDD 红 — malloc_zone_pressure_relief fault injection

- [x] 3.1 新建 `tests/test_malloc_pressure_relief.py`：
  - macOS 真实调一次：no exception
  - mock ctypes.CDLL → side_effect=OSError：run 不 crash
  - non-macOS 平台 skip + warn
- [x] 3.2 跑 → 红（调用代码不存在）

## 4. 实现 cold prune

- [x] 4.1 在 `synthetic_socio_wind_tunnel/memory/store.py` 加
  `evict_cold_encounter_events(before_tick: int) -> int` 方法
  - 遍历 `self._events`, 用 list-comprehension 重建只保留 (kind != encounter or tick >= before_tick) 的 events
  - 维护可能存在的 reverse index（重建 from filtered list）
- [x] 4.2 在 `synthetic_socio_wind_tunnel/memory/service.py` 加
  `evict_cold_encounter_events_across_agents(before_tick: int) -> int`
- [x] 4.3 在 `synthetic_socio_wind_tunnel/orchestrator/multi_day.py`
  day_end hook 链加 cold-prune trigger：
  - env `MEMORY_EVENT_EVICT_GRACE_DAYS` default 2
  - `before_tick = max(0, day_index - grace_days) * ticks_per_day`
  - 调用 + 累加进 day_run.evicted_encounter_count（DayRunSummary 新字段）
- [x] 4.4 DayRunSummary 加 `evicted_encounter_count: int = 0` 字段
  + `model_dump()` 输出

## 5. 实现 malloc_zone_pressure_relief

- [x] 5.1 在 `_init_memory_management_hooks` 加 helper
  `_call_malloc_pressure_relief()`:
  - macOS: ctypes.CDLL("libc.dylib").malloc_zone_pressure_relief(None, 0)
  - Linux: ctypes.CDLL("libc.so.6").malloc_trim(0) (TODO 标注)
  - 第一次 fail → log warning + 标志 `_pressure_relief_disabled=True`
- [x] 5.2 在既有 `_on_tick_end_memory` hook 内 `gc.collect()` 之后调用
- [x] 5.3 跑 G3 tests 转绿

## 6. 实现 publishable mode RSS cap default

- [x] 6.1 在 `tools/run_variant_suite.py` argparse 之后检测：
  - if args.mode == "publishable" and not os.environ.get("RSS_RESTART_MB"):
  - os.environ["RSS_RESTART_MB"] = "10000"
  - log "[publishable] auto-set RSS_RESTART_MB=10000 (override via env)"
- [x] 6.2 新加 `tests/test_run_variant_suite_publishable_rss_default.py`:
  - mock argparse with --mode publishable, env clean → RSS_RESTART_MB
    set to "10000"
  - with --mode dev → unset
  - with explicit env override → user value preserved

## 7. G1-G6 测试转绿

- [x] 7.1 跑 `pytest tests/test_memory_store_encounter_eviction.py tests/test_memory_service_cross_agent_evict.py tests/test_memory_event_eviction_property.py tests/test_malloc_pressure_relief.py tests/test_run_variant_suite_publishable_rss_default.py`
- [x] 7.2 既有 1700+ 测试不回退

## 8. E2E RSS 实测验证

- [x] 8.1 跑 dev smoke 100 agent × 1 day 两次（with vs without eviction
  via env `MEMORY_EVENT_EVICT_GRACE_DAYS=999`）
- [x] 8.2 记录两次 DayRunSummary[-1].rss_mb（既有 observability instrumentation）
- [x] 8.3 写 `docs/eviction-rss-measurement-2026-05-19.md`：absolute
  numbers + ratio + 判读

## 9. E2E RSS cap enforcement 验证

- [x] 9.1 跑 dev smoke 100 agent × 5 day with env `RSS_RESTART_MB=2000`
  (test cap = 2GB, 容易撞顶)
- [x] 9.2 验证 graceful_stop 路径被触发（log line "[memory] RSS XMB >
  threshold 2000MB"）
- [x] 9.3 验证 partial 文件写出 + sentinel 没出现（既有 cell 已 run）

## 10. Spec validate + archive

- [x] 10.1 全量 `pytest tests/ --ignore=tests/test_hotfix_integration.py --ignore=tests/test_deepseek_tier_client.py -q --tb=line`
- [x] 10.2 `openspec validate enforce-worker-rss-cap`
- [x] 10.3 `openspec archive enforce-worker-rss-cap`
- [x] 10.4 commit + push
