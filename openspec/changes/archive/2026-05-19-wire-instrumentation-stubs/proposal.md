## Why

2026-05-20 02:08 实际 spawn 暴露 `comprehensive-runtime-instrumentation`
(commit `8fedc2d`) 的实施漏洞：spec 里写了 9 个 PHASE event 和 memstat
周期采样，**`emit_event` / `sample_metrics` API 完整实现 + 单测 pass**，
但**实际代码路径里只有 PROCESS_START（lazy init 触发）和 EXIT (atexit)
被自动触发**。其余 7 个桩点（SETUP_START/DONE, SNAPSHOT_LOAD_START/DONE,
TICK_LOOP_START, DAY_START/END）**和 memstat sample 调用本身**都没有
在 `run_variant_suite.py` / `multi_day.py` 里实际插入调用。

→ 2026-05-20 02:08 spawn 的 events.jsonl 只有 8 条（4 个 EVICT + 3 个
SNAPSHOT_WRITE + 1 个 EXIT），memstat.jsonl **0 行**，看不到 setup /
snapshot load 阶段的内存轨迹——这是当时反复诊断的盲区。

测试盲点：之前 22 个 instrumentation test **全部直接调用 emit API**
验证它工作，**没一个测真实 worker 启动后端到端 events.jsonl 含 9 个
PHASE event**。这次教训：测 API 不等于测 wiring。

backlog 1.15 (preflight checklist) 已经记录了这个根因；本 change 是把
wiring 缺口实际修掉的执行 PR。

## What Changes

- **`MultiDayRunner._init_memory_management_hooks`** 内的
  `_on_tick_end_memory` hook 增加 `get_instrumentation().sample_metrics()`
  调用，每 `INSTRUMENTATION_SAMPLE_EVERY_N_TICKS=12` tick 一次（与现有
  latency hook 共享 cadence env）；传递 `memory_service` / `dialogue_service`
  / `llm_health_tracker` / handler_times 参数让 sample 字段填充完整。
- **`MultiDayRunner.run_multi_day`** 显式 emit phase events：
  - `SNAPSHOT_LOAD_START` 在 resume 路径 snapshot load 之前
  - `SNAPSHOT_LOAD_DONE` snapshot load 之后（含 duration_sec + rss delta）
  - `TICK_LOOP_START` 在第一个 orchestrator.run 之前
  - `DAY_START` / `DAY_END` 在每天循环边界（已有 hook 点，加 emit 即可）
- **`tools/run_variant_suite.py::_setup_aitown_stack`** 函数前后 emit
  `SETUP_START` / `SETUP_DONE`（含 duration_sec + rss delta）。
- **新 e2e test**：`tests/test_phase_events_real_subprocess.py` 真跑
  dev smoke 50 agent × 1 day subprocess，读 events.jsonl，断言 9 个
  PHASE event 按 spec 顺序出现。**用 subprocess 是因为单 worker 单
  process 路径才能覆盖真实 wiring**——in-process test 的 fixture 会
  把 instrumentation reset 干扰。
- **新 e2e test**：`tests/test_memstat_real_subprocess.py` 同样跑
  subprocess dev smoke，验证 memstat.jsonl 在 tick loop 结束后有
  ≥ N 条 sample（按 INSTRUMENTATION_SAMPLE_EVERY_N_TICKS 计算）。

NOT in scope:
- 不改 `RuntimeInstrumentation` API 本身
- 不改 schema 字段
- 不改 phase 名称 / 顺序定义
- 不动 PROCESS_START / EXIT（已 wired）

## Capabilities

### Modified Capabilities

- `runtime-instrumentation`: 把 spec 已 documented 但未 wired 的 phase
  event 桩点 + memstat sampling 调用真实插入 worker 代码路径；新增
  subprocess-level e2e test 验证 wiring（不只测 emit API）。

## Impact

**Affected code**:
- `synthetic_socio_wind_tunnel/orchestrator/multi_day.py` (~40 lines
  added in `_init_memory_management_hooks` + `run_multi_day`)
- `tools/run_variant_suite.py` (~20 lines added wrapping
  `_setup_aitown_stack`)
- 2 new test files using subprocess

**Affected behavior (positive)**:
- 续跑 worker 日志里 events.jsonl 真有 9 个 PHASE event
- memstat.jsonl 每分钟有 1 行（默认 sample_every=12, ~每 12s 一行 in
  publishable wall）
- post-mortem 工具（`analyze_memstat.py`）现在能看到 SETUP / SNAPSHOT_LOAD
  duration → 直接量化"启动期开销"

**Affected behavior (negative)**:
- 每 12 tick 多 1 次 `psutil.memory_info()` + `psutil.cpu_percent()`
  + 写 JSONL → estimate < 10 ms/sample，<0.5% overhead at default cadence
- emit_event 多几次 → I/O 量小（events.jsonl 一行 ~200 bytes × 几十次/run）

**Test impact**: 2 个新 e2e subprocess test (~60 sec total runtime).
既有 22 个 emit-API 单测**保留不动**（mock-based，测 API 契约）。

**Migration**: 纯 in-process 改动，下次 spawn 立刻生效。`INSTRUMENTATION_DISABLE=1`
仍然能完全关。
