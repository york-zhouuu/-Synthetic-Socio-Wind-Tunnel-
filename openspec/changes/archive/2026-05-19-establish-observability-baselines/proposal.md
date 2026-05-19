## Why

之前几次内存优化（`RSS_RESTART_MB=2500`、`GC_EVERY_N_TICKS=200`、
DialogueService `2-day grace`）全是**拍脑袋设的参数**，从未量过：

- worker 实际 RSS 增长曲线是什么形状（线性？爆炸？平台期？）
- gc.collect 实际能释放多少 cycles / RAM
- DialogueService 后续访问的真实时间窗口

CPU profile 只跑过 dev scale 100 agent × 1 day，**publishable 1000 agent
× 14 day 的 hot-path 是插值推断**，不是测量。

下一波优化（`index-memory-events-by-tick` 等）继续无量化数据支持就还是
猜。**这次先建立"量化能力"作为前提**——下个 change 拿数据说话才不猜。

## What Changes

**Scope 收窄说明 (2026-05-19 update)**：原 5 件交付物里，**memray** 和
**line_profiler** 因为 overhead 太高（20%+ / 50%+）**不适合挂 publishable
run**——而用户接下来要做的"边续跑边收集"场景必须低开销。剔除这两件，
只保留 3 件**能挂 publishable** 的轻量交付。memray / line_profiler
fixture 留给**下一个 dev-only profile change** 做（见 Non-goals）。

**实际 scope**：建立**低开销** observability，**不优化任何 production
hot path**。具体：

1. **Runtime instrumentation** 进 `MultiDayRunner.on_day_end` 内置 hook：
   每天写下面进 `DayRunSummary`（向后兼容，类似 2026-05-19
   `llm_fallback_pct` 模式）：
   - `rss_mb` / `vms_mb` — `psutil.Process().memory_info()`
   - `memory_store_event_count` — Σ events across agents
   - `dialogue_count` — `len(_dialogues) + len(_dialogue_summaries)`
   - `gc_collections` — `gc.get_count()` 三代
   - `tick_latency_ms_p50` / `p95` / `max` — per-day tick wall-clock 分布
   - **overhead < 0.1%**（每 day 一次 psutil call）✓ 可挂 publishable

2. **RSS time-series harness**（`tools/dump_runtime_observability.py`）：
   - 跑 dev smoke 同时每 12 tick sample psutil RSS
   - 落 `tests/fixtures/rss_timeseries_dev_100agent_1day.json`
   - **overhead < 0.5%**（每 12 tick 一次 psutil call）✓ 也可挂 publishable

3. **psutil 加入 dev deps 显式**（其它 deps 留给 follow-up change）。

## Capabilities

### New Capabilities

- `runtime-observability`: instrumentation contract（DayRunSummary
  observability 字段）+ memory/CPU profiler fixture 格式 + regression
  guard 模式。本 capability 只交付 measurement + diff 能力，不携带任何
  production optimization 职责。

### Modified Capabilities

（无——不动既有 spec 行为。新字段进 `DayRunSummary` 是**向后兼容
扩展**（旧 JSON 缺新字段时 default 0/None，旧消费者读旧字段不受影响），
不进 spec 修订。）

## Impact

**新增文件**：
- `tools/dump_runtime_observability.py`
- `tests/fixtures/memray_top_allocators_summary.json`
- `tests/fixtures/line_profile_events_at_tick.json`
- `tests/fixtures/rss_timeseries_dev_100agent_1day.json`
- `tests/test_runtime_observability_*.py`（3 个 test 文件，schema +
  mock-based + integration）

**修改文件**：
- `pyproject.toml` — 加 4 个 dev deps
- `synthetic_socio_wind_tunnel/orchestrator/multi_day.py` — DayRunSummary
  新增字段；on_day_end hook 内部 instrumentation
- `.gitignore` — memray .bin 原始 dump（可能 5-20 MB）

**测试影响**：
- ≥10 个新 test（schema + mock-based + property-based + budget + smoke
  + fault injection）
- 既有 1668 tests SHALL 不回退

**依赖**：
- `memray` 在 macOS 上需要 system libunwind（brew install libunwind
  可能必需，标在 README 里）
- `pyinstrument` 0 system deps
- `line_profiler` 编译 C extension，wheel 已 prebuilt
- `psutil` 已经在 transitive deps

**Non-goals (explicit)**：
- 不优化任何 hot path（events_at_tick / DialogueService grace tuning 等
  全部留下一个 change）
- 不主动跑 1000-agent publishable profile（成本 14h；但
  instrumentation 一落地，下次 publishable run 自动留时间序列）
- **不引入 memray**（20-40% overhead，挂不上 publishable）— 留给
  follow-up dev-only change（建议名 `memray-allocation-baseline`）
- **不引入 line_profiler**（50%+ overhead，同上）— 留给 follow-up
  （建议名 `line-profile-events-at-tick`）
- 不引入 OpenTelemetry / 分布式 tracing
- 不集成 CI 内存预算 enforcement（先 manual diff）
- 不动既有 cProfile-based `hot-path-baseline` capability（complement 不
  replace）

**触发后续**：下一个 change `index-memory-events-by-tick` 启动时，把
本 change 落的 baseline fixture 作为"优化前后对比"的对照源：
- memray summary diff: dialogue/event allocations 是否下降
- line_profile diff: events_at_tick 第几行变快了
- RSS time-series diff: worker RSS 增长曲线是否变 sub-linear
