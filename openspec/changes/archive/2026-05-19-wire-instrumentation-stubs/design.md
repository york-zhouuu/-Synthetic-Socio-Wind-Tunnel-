## Context

`comprehensive-runtime-instrumentation` (commit 8fedc2d) defined a
RuntimeInstrumentation API with 9 phase events + periodic memstat
sampling, and shipped 22 tests verifying the emit API works in
isolation. But the actual wiring — i.e., **calls to those APIs at the
documented sites in `multi_day.py` and `run_variant_suite.py`** —
was not implemented. Only:

- `PROCESS_START` fires when `get_instrumentation()` is first called
  (we put a lazy-init emit in `get_instrumentation`)
- `EXIT` fires via `atexit.register`
- `EVICT`, `SNAPSHOT_WRITE`, `RETRY` fire because their桩点 are inline
  with the code I edited for the respective changes

But the lifecycle phase events `SETUP_START`/`SETUP_DONE`/
`SNAPSHOT_LOAD_START`/`SNAPSHOT_LOAD_DONE`/`TICK_LOOP_START`/
`DAY_START`/`DAY_END` and the `sample_metrics()` periodic call were
left as "spec says they fire, no impl asks the API to emit them."

The 2026-05-20 02:08 publishable spawn's events.jsonl revealed this:
8 lines (PROCESS_START + 4 EVICT + 3 SNAPSHOT_WRITE + EXIT) for a
3-minute worker run; memstat.jsonl was empty.

## Goals / Non-Goals

**Goals:**
- 7 missing phase events fire at correct sites in real worker runs
- memstat sampler fires every N tick from `_on_tick_end_memory`
- e2e test using subprocess catches future "spec'd but not wired" gaps
- No new dependencies; reuse existing `get_instrumentation()` singleton

**Non-Goals:**
- 不重构 `RuntimeInstrumentation` API
- 不改 schema / phase names
- 不动 PROCESS_START + EXIT 路径 (working)
- 不改 EVICT / SNAPSHOT_WRITE / RETRY emit 位置 (working)

## Decisions

### D1: 桩点位置（与 spec 表一致）

| Phase | Site |
|---|---|
| `SETUP_START` | `tools/run_variant_suite.py` 进入 `_setup_aitown_stack` 之前 |
| `SETUP_DONE` | `_setup_aitown_stack` 返回之后 |
| `SNAPSHOT_LOAD_START` | `MultiDayRunner.run_multi_day` 内 snapshot restore 调用之前 |
| `SNAPSHOT_LOAD_DONE` | snapshot restore 完成之后 |
| `TICK_LOOP_START` | 第一个 `self._orchestrator.run(...)` 之前 |
| `DAY_START` | day 循环开始（after on_day_start callback fires） |
| `DAY_END` | day 循环结束（after on_day_end callback fires） |

每个 emit_event 传必要 context：duration_sec（从 monotonic 计算）+
rss_before_mb / rss_after_mb（psutil）+ phase-specific fields。

### D2: memstat sampling 寄生在既有 _on_tick_end_memory hook

`_init_memory_management_hooks` 已经注册了 on_tick_end hook 用于 gc /
RSS cap。在同一 hook 里加 sample_metrics 调用：

```python
sample_every = int(os.environ.get(
    "INSTRUMENTATION_SAMPLE_EVERY_N_TICKS", "12",
))
def _on_tick_end_memory(tick_result):
    ...  # existing gc / cap logic
    if sample_every > 0 and tick_global % sample_every == 0:
        try:
            get_instrumentation().sample_metrics(
                tick_global=tick_global,
                day_index=day_idx,
                tick_in_day=tick_idx,
                memory_service=self._memory_service,
                dialogue_service=self._dialogue_service,
                llm_tracker=_lazy_get_tracker(),
                sim_time_iso=...,
            )
        except Exception:
            pass  # never crash worker on instrumentation failure
```

理由：复用既有 hook 注册，不增加 hook 数量；同步触发减小代码复杂度。

### D3: subprocess e2e test 必要性

之前的 mock-based tests 没抓到 wiring 缺口因为他们直接 call emit API
**不经过 worker 启动路径**。新 test 必须：
1. 跑真 `tools/run_variant_suite.py --mode=dev` subprocess
2. 等 subprocess 完成（dev smoke 50 agent × 1 day ~30 sec）
3. 读输出目录的 `seed_<N>.events.jsonl`
4. assert 9 个 PHASE event 按顺序出现
5. assert memstat.jsonl 至少有 N 行（dev smoke 288 tick / 12 = 24 sample）

代价：每次 CI ~30-60 sec 额外，可接受。可以 mark `@pytest.mark.slow` 让
local dev 跳过。

### D4: failure isolation 不变

emit_event / sample_metrics 内部已有 try/except 兜底（既有 design D10）。
新桩点不需要额外保护——失败时 log warn 不抛。

### D5: 不在 `MultiDayRunner.__init__` 触发 PROCESS_START

PROCESS_START 由 `get_instrumentation()` lazy init 自动触发（已 work）。
不在 `__init__` 强制 call get_instrumentation() — 让 lazy 行为保持。

## Risks / Trade-offs

**[R1] memstat sampling 在 setup phase 不 fire（hook 没注册）**
→ Mitigation: 这是接受的 — setup phase 的内存轨迹由 SETUP_START /
  SETUP_DONE phase events 的 rss_before/after delta 覆盖。如果未来
  需要 setup 期内更细粒度采样，可加新 capability。

**[R2] tick_loop_start 在 resume 路径上的精确点**
→ Mitigation: snapshot restore 完成之后、第一个 orchestrator.run 之前。
  emit 顺序：SNAPSHOT_LOAD_DONE → TICK_LOOP_START → first tick。
  这是 spec D7 表的语义。

**[R3] DAY_START / DAY_END 多 day 时多次 emit**
→ Acceptable — 这是设计意图。spec 已写"每 day 一对"。

**[R4] subprocess test 占用 CI 时间**
→ Mitigation: pytest mark `@pytest.mark.slow` 让 local 默认跳过；CI
  full 路径才跑。

## Migration

1. 改完代码 + 跑 unit + subprocess e2e 全绿
2. archive + commit + push
3. 下次 spawn worker 立即受益

## Open Questions

- (闭合) memstat 嵌入既有 hook 还是新加 hook？答：D2 嵌入既有
- (闭合) subprocess test 必要性？答：D3 必要
