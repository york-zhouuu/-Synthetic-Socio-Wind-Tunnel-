## Why

2026-05-20 凌晨实测 publishable resume 暴露**两个独立严重问题**：

1. **Worker 启动期完全无埋点**：spawn s42/phone_friction 后 10+ 分钟
   log 静默，外部只能通过 `ps` 看 RSS 数字。`[gc]` 日志每 200 tick 才
   1 行（10-15 min），snapshot 反序列化 35GB 峰值阶段**完全暗箱**。
2. **`_self_rss_mb()` 使用 `resource.getrusage(RUSAGE_SELF).ru_maxrss`**
   —— 这是**进程生命周期 RSS 峰值**，不是当前 RSS。后果：worker
   snapshot 反序列化峰值打到 35GB 后，即使 GC + malloc_relief 把当前
   RSS 降到 8GB，`ru_maxrss` 永远停在 35GB。下次 RSS_CHECK 必然 trip
   cap → graceful_stop → 重启 → 又 35GB → 永远循环。

→ enforce-worker-rss-cap 的 17 个 tests **全部 mock RSS 值**测"机制"，
未测"RSS 测量值是否反映现实"——这是真的测试盲点。修这 2 个问题需要
**全面重新设计 instrumentation**，不是补丁。

更广泛的观察：3 个 2026-05-19 optimization (cold prune / malloc relief
/ RSS cap) 在 tick-loop steady state 是有效的（昨日 dev smoke 50 agent
× 3 day 实测 RSS 1425MB → 1021MB，−28%），但**所有埋点都集中在
tick-loop**，覆盖不到：
- snapshot 反序列化阶段
- setup phase 各步耗时 / 内存增量
- LLM 每 call 的真实路径（tier / key / latency / retry attempt）
- snapshot 写盘期 RSS 抖动
- eviction 实际释放量
- 退出 / 崩溃时的 last state

要回答"内存/CPU 优化在这个 worker 里到底生效没有"，**必须**有覆盖全
phase 的结构化埋点。

## What Changes

- **新 module** `synthetic_socio_wind_tunnel/observability/instrumentation.py`
  —— `RuntimeInstrumentation` 类，process-wide 单例，emit 三类输出：
  - `seed_<N>.memstat.jsonl` — 周期采样的 memory + CPU + 子系统 metric
    （每 N tick）
  - `seed_<N>.events.jsonl` — 离散事件（phase 转移 / eviction / retry /
    snapshot write / exit）
  - `seed_<N>.llm.jsonl` — 每个 LLM call 一行（success + fallback 都记）
  - 配套 sparse 人类可读 log 行（`[memstat]` / `[evict]` / `[retry]` /
    `[snapshot]`）写到既有 `worker_<v>.log`
- **修 `_self_rss_mb` bug**：改用 `psutil.Process().memory_info().rss`
  （当前 RSS），保留 `ru_maxrss` 仅作 `rss_peak_mb` 参考字段。重命名为
  `_current_rss_mb`，更新 2 个调用点。
- **Phase boundary 桩**：`PROCESS_START` / `SETUP_START` / `SETUP_DONE` /
  `SNAPSHOT_LOAD_START` / `SNAPSHOT_LOAD_DONE` / `TICK_LOOP_START` /
  `DAY_START` / `DAY_END` / `EXIT` 全部 emit 到 `events.jsonl`，附带
  RSS before/after delta + duration。
- **Eviction 桩**：`MemoryService.evict_cold_encounter_events_across_agents`
  调用前后 emit EVICT event（events_evicted / memory_store delta /
  rss delta）。
- **Retry 桩**：`_run_with_retry` 每次 attempt 失败 emit RETRY event
  （tier / provider / key_id / attempt / exc_class / backoff_sec）。
- **LLM call 桩**：tier client 每次 `generate()` 完成 emit LLM event
  （tier / provider / model / latency / status / exc_class 等）。
- **Snapshot write 桩**：snapshot 写盘前后 emit SNAPSHOT_WRITE event
  （duration / size / rss delta）。
- **Per-tick handler timing**：OperationPool 已记录 wall_sum，扩展到
  emit per-handler 累计 + p50/p95 进 memstat 采样。
- **新 tools**：
  - `tools/tail_memstat.py` — 实时 tail memstat.jsonl + rolling stats
  - `tools/analyze_memstat.py` — 离线分析（phase timeline、RSS 曲线、
    LLM 失败率 over time、handler 耗时分布）

NON-goals:
- 不改 `RetryPolicy` / 不改 cold-prune 行为 / 不改 stagger guard 行为
- 不引入新外部依赖（psutil 已在 dev extras）
- 不改 LLM client 调用 API（只 wrap retry & call sites with桩）
- 不重写 DayRunSummary（既有 day-end 聚合保留为 backward compat）
- 不增加 tracing / OpenTelemetry / 分布式 trace —— 单 worker scope
- 不试图覆盖 ledger atomic write 等次要路径

## Capabilities

### New Capabilities

- `runtime-instrumentation`: process-wide 结构化埋点能力。定义
  `RuntimeInstrumentation` API + 三类 JSONL 输出 schema（memstat /
  events / llm）+ phase 边界 contract + 每类 event 的字段契约 + 真测量
  验证（不 mock）。

### Modified Capabilities

- `run-resilience`: `_self_rss_mb` → `_current_rss_mb` 改用 psutil 当前
  RSS；既有 `RSS_RESTART_MB` cap 现在用真实当前 RSS 判定，不再被
  生命周期峰值误触发。

## Impact

**Affected code**:
- 新文件: `synthetic_socio_wind_tunnel/observability/instrumentation.py`
  + `__init__.py` 顶层 re-export
- 修改: `synthetic_socio_wind_tunnel/orchestrator/multi_day.py`
  （`_self_rss_mb` 修复 + phase 桩点 + memstat 采样 hook）
- 修改: `synthetic_socio_wind_tunnel/memory/service.py`
  （eviction 桩点）
- 修改: `tools/tier_llm_factory.py`
  （`_run_with_retry` retry 桩点 + tier client `generate` LLM 桩点）
- 新文件: `tools/tail_memstat.py` / `tools/analyze_memstat.py`

**Affected tests**:
- 5+ 新真测试（每个 metric 用独立测量验证值正确性，不 mock）
- 既有 17 个 RSS cap tests 不动（mock 路径仍合法 — 测的是 cap 机制）
- 既有 1812 regression baseline 不能回退

**Affected behavior (positive)**:
- 续跑时**可见每 N tick 的真实 RSS / CPU / event count / LLM 健康**
- 崩溃时**可见死前最后状态**（events.jsonl 最后 EXIT 事件）
- `_self_rss_mb` 修复后**RSS cap 实际生效**（不再被一次峰值误触发）
- 优化效果**可量化验证**（events.jsonl EVICT 事件 RSS before/after
  delta 直接显示 cold prune 释放了多少）

**Affected behavior (negative)**:
- 每 N tick 多 1 次 `psutil.memory_info()` + `psutil.cpu_percent()`
  + 写 JSONL —— 估 ~5ms overhead，sample_every_n=12 时占 < 0.5%
- JSONL 文件可能大（estimate: memstat 80 行/cell ~50KB, events 1k
  行/cell ~500KB, llm 4M 行/cell ~600MB —— llm.jsonl 默认 sample
  rate 1/100 降到 ~6MB）

**Dependencies**: 无新依赖（psutil 在 dev extras 已可用）。

**Migration**:
- 续跑 worker 直接受益（重新 spawn 后立即有结构化日志）
- 已有 cell 的 worker_<v>.log 历史数据不受影响
- 新 JSONL 文件与既有 partial/snapshot/WAL 共存
