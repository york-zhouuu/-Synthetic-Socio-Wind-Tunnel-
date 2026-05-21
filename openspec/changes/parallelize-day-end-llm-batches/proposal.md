## Why

2026-05-21 publishable seed-43 实测 baseline 单 worker day_end transition 跑了
**30+ min** (40 min observed at heartbeat 15:30) — 因为 day_end 有**两个 serial
for loop 串行调 LLM**：

| LLM batch | 位置 | 量级 (publishable) | 当前模式 | 串行耗时 |
|---|---|---|---|---|
| `maybe_reflect` per protag | `tools/run_variant_suite.py:970-985` | 500 calls | **🔴 SERIAL** | ~17 min (500 × 2s) |
| `run_daily_summary` per agent | `synthetic_socio_wind_tunnel/memory/service.py:940` | 1000 calls (有 event 的 ~500) | **🔴 SERIAL** | ~17 min |
| `_generate_plans_for_day` per protag | `synthetic_socio_wind_tunnel/orchestrator/multi_day.py:1075-1077` | 500 calls | 🟢 concurrent (gather) | ~30 sec |

每 day_end 约 1000-1500 LLM call 走 serial 路径。Publishable 14-day × 4 variant
× 4 seed × day_end overhead = **~28 hr 纯 LLM serial wait** 占 wall clock。

**历史原因（git blame 已查）**：
- `run_daily_summary` serial: 初次 commit `24b8044` (2026-04-21) 写就这样。agent
  数小时跑得快，没人觉得是瓶颈。`d89577d` (2026-05-19) 加 `wait_for(60s)` 防 hang，
  但保留了 serial。
- `maybe_reflect` loop serial: `2026-05-18 hotfix` (D2 attempt 4 reflection hang)
  注释明确说"60s × 500 protag = 50 min serially — but most return in 5-15s; the
  cap just bounds the pathological case"。说明作者**知道 serial 慢**，hotfix 时
  没改并发。

**已知 invariant 不变**：
- 每个 LLM call SHALL 仍然包 `asyncio.wait_for(60s)` (CLAUDE.md 1.9 不变量)
- LLM provider burst：tick loop 用 `OperationPool` 已经 200 concurrent 跑通，
  day_end 30 concurrent 远低于此

## What Changes

**两个 batch 同时改为 concurrent via `asyncio.gather` + `asyncio.Semaphore(N)`：**

1. `MemoryService.run_daily_summary` (memory capability):
   - 当前 `for agent_id in agents.items(): await llm.generate(...)`
   - 改为 `await asyncio.gather(*(_one(aid, a) for aid, a in agents.items()))` with
     `Semaphore(30)` 限并发
   - 保留所有现有行为：`asyncio.wait_for(60s)` per call, fallback summary on
     timeout/error, `daily_summary` event record per agent, identical
     `DailySummary` dict output

2. `tools/run_variant_suite.py` day-end `maybe_reflect` loop (multi-day-run capability):
   - 当前 `for rt in runtimes: if is_protagonist: await wait_for(maybe_reflect(...), 60s)`
   - 改为 `asyncio.gather(*(...))` with `Semaphore(30)`
   - 保留 timeout fallback ("skip and move on") per protag

**并发度 N=30 选择理由**：
- OperationPool tick loop 已经用 200 concurrent 跑通 → 30 远低于已知安全上限
- DeepSeek 服务端 p50 latency 与 concurrency 不成线性反比 — 30 比 50 安全很多
  且加速差距小
- macOS socket / asyncio task overhead trivial at 30

## Capabilities

### Modified Capabilities

- `memory`: `run_daily_summary` SHALL execute per-agent LLM calls concurrently
  (bounded by Semaphore), preserving all per-call timeout + fallback semantics
- `multi-day-run`: day-end `maybe_reflect` batch SHALL execute per-protagonist
  LLM calls concurrently (bounded by Semaphore)

## Impact

**Affected code**:
- `synthetic_socio_wind_tunnel/memory/service.py::run_daily_summary` (~30 line
  refactor)
- `tools/run_variant_suite.py:970-985` maybe_reflect loop (~25 line refactor)

**Affected behavior**:
- day_end transition wall time: ~30 min → **~2-3 min** (~10-15x speedup)
- Per-call hang isolation: serial 1-hang-blocks-all → concurrent 1-hang-only-
  blocks-1-slot (其他 29 个继续) — **strictly improves hang behavior**
- Identical metric outputs (DailySummary dict / reflection events): 应保证字段
  级 byte equal vs serial
- LLM provider burst risk: minimal, 30 << OperationPool 已测的 200 concurrent

**Non-goals**:
- 不改 `_generate_plans_for_day` (已经 concurrent via gather)
- 不改 importance scoring path
- 不改 wait_for(60s) 单 call timeout
- 不改 fallback / sentinel string 行为

**Test 策略 (real-artifact, 不 mock LLM)**:
- 单元 test 1: stub LLM client (returns fixed string immediately), 500 agent,
  assert duration < N seconds (vs serial would be > 500 × stub_latency)
- 单元 test 2: stub LLM with 1 hang (asyncio.sleep(120)) + 499 fast → assert
  finishes in < 70s (vs serial would block 60s + 499 × stub = ~17 min)
- 集成 test: 50 agent × 1 day smoke (publishable mini) → verify day_end completes
  + day_summary file written + no commit failures

**Risk mitigation**:
- 改完先跑 single-worker dev smoke 验证正确性
- Fork 4 variants 前用 baseline 数据当 baseline correctness reference
