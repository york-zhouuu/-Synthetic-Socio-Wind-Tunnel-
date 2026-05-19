## Context

3 个 2026-05-19 优化 (cold prune / malloc relief / RSS cap) 在 dev
smoke 实测有效（50 agent × 3 day RSS −28%）。但 2026-05-20 凌晨实测
publishable resume（1000 agent，从 day11 snapshot 恢复）暴露：

1. **盲区**：worker 启动后 10+ 分钟 log 静默，外部只能 `ps` 看 RSS。
   `[gc]` 日志每 200 tick 才 1 行（10-15 min），snapshot 反序列化
   35GB 峰值阶段完全看不见。
2. **测量 bug**：`_self_rss_mb()` 用 `resource.getrusage().ru_maxrss`
   —— 生命周期峰值，不是当前 RSS。一次 35GB 峰值后 cap 永久 trip，
   重启循环死锁。
3. **测试盲点**：17 个 RSS cap test 全部 mock RSS 值，未验证测量正确性。

更根本：所有 instrumentation 集中在 tick-loop 后期，覆盖不到 setup /
snapshot load / LLM 路径 / eviction 实际效果 / 退出状态。要回答"优化
现在生效没有"，必须全面 instrument。

## Goals / Non-Goals

**Goals:**
- 覆盖 worker 全生命周期（启动 → setup → snapshot load → tick loop
  → day boundary → eviction → snapshot write → exit / crash）
- 真实测量当前 RSS（不是 ru_maxrss 峰值）
- 结构化 JSONL 输出，可被工具解析（不只是 stdout 文本）
- 配套人类可读 `[memstat]/[evict]/[retry]/[snapshot]` 日志行用于
  `tail -f`
- 真测试：用独立测量验证值（psutil RSS、perf_counter wall、字节数
  delta），不 mock 关键测量值
- 修复 `_self_rss_mb` bug，让 RSS cap 实际反映现状

**Non-Goals:**
- 不引入 OpenTelemetry / 分布式 tracing — 单 worker scope
- 不重写 DayRunSummary（既有 day-end 聚合保留）
- 不改 RetryPolicy / cold-prune / stagger 的核心逻辑
- 不增加新外部依赖（psutil 已在 dev extras）
- 不试图重做 OperationPool 的 dispatch（只 wrap 既有桩点）
- 不覆盖次要路径（ledger atomic write、cartography 等）

## Decisions

### D1: 三文件输出（memstat / events / llm），不混

**选定:** 三个独立 `.jsonl` 文件 + `worker_<v>.log` 里的 sparse 摘要

理由：
- 三类数据 cardinality 差异极大：memstat ~80 lines/cell，events ~1k
  lines/cell，llm ~600k-4M lines/cell（取决于 sample rate）
- 混在一起会让 memstat / event 流被 llm 流淹没，难以解析
- JSONL 一行一记录便于 `jq` / pandas 后处理
- log 行作为人类可读补充，方便 tail / grep

**替代:** 单 SQLite — 拒绝，因为 JSONL 简单 + 文本 friendly + 不需要
schema migration。

### D2: psutil 优先，ru_maxrss 仅作 fallback + 暴露为独立字段

```python
def _current_rss_mb() -> int | None:
    try:
        import psutil
        return psutil.Process().memory_info().rss // (1024 * 1024)
    except ImportError:
        # Fallback with warning
        try:
            import resource
            ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            logger.warning("[memstat] psutil unavailable; using ru_maxrss "
                           "(LIFETIME PEAK, not current)")
            import sys
            return ru // (1024 * 1024) if sys.platform == "darwin" else ru // 1024
        except (ImportError, OSError):
            return None
```

memstat sample 同时记 `memory.rss_mb`（当前）+ `memory.rss_peak_mb`
（ru_maxrss 用作历史参考，方便诊断 spike）+ `memory.uss_mb`（更精确
的 private memory）+ `memory.vms_mb`（virtual 含 swap）。

### D3: RuntimeInstrumentation 是 process-singleton

```python
_instrumentation: Optional[RuntimeInstrumentation] = None

def get_instrumentation() -> RuntimeInstrumentation:
    global _instrumentation
    if _instrumentation is None:
        _instrumentation = RuntimeInstrumentation.from_env()
    return _instrumentation
```

理由：跟 `LLMHealthTracker.get_tracker()` 同模式，process scope 单例
保证所有桩点共享同一组输出文件。tests 用 `reset_for_tests()`。

### D4: Sample cadence — 跟 latency hook 对齐每 12 tick

memstat 采样跟既有 `_on_tick_end_latency` 的 `OBSERVABILITY_LATENCY_
SAMPLE_EVERY_N_TICKS=12` 同步 —— 24 个 sample/day，14 day = 336 lines
/cell ≈ 50KB. 可 env override。

### D5: LLM call sampling — 每 100 call 1 条，错误 / retry 全记

llm.jsonl 高 volume（每 tick 1000 个 do_something LLM call × 4032
ticks = 4M call/cell）。默认 sample 1/100 = 40k lines = ~6MB。
但 **任何 fallback / retry / exception 100% 记录**（即使在 sample
之外）—— 这些是诊断信号，不能丢。env `LLM_SAMPLE_RATE`（默认 0.01）
+ `LLM_RECORD_ERRORS_ALL=true`（默认）。

### D6: Phase event 是 must-have，不 sample

PHASE / EVICT / RETRY / SNAPSHOT_WRITE / EXIT 事件全部 100% 记录到
events.jsonl —— 这些是 sparse 的（每 cell 通常 < 1000 个），完整
保留对诊断关键。

### D7: 桩点位置选择

| 桩点 | 模块 | 触发时机 |
|---|---|---|
| `PROCESS_START` | `instrumentation.py.from_env()` 第一次 call | 模块 import 第一次实例化 |
| `SETUP_START/DONE` | `tools/run_variant_suite.py` aitown wiring 前后 | 显式调用 |
| `SNAPSHOT_LOAD_START/DONE` | `MultiDayRunner.run_multi_day` snapshot load 前后 | resume 路径 |
| `TICK_LOOP_START` | `Orchestrator.run` 第一次 tick 前 | 显式调用 |
| `DAY_START/END` | `MultiDayRunner` on_day_start / on_day_end | hooks |
| `EVICT` | `MemoryService.evict_cold_encounter_events_across_agents` 返回前 | 调用包装 |
| `SNAPSHOT_WRITE` | `MultiDayRunner._write_snapshot` 前后 | 包装 |
| `RETRY` | `tools/tier_llm_factory._run_with_retry` 每次 except retryable | 既有 except 路径加 emit |
| `LLM_CALL` | tier client `generate()` 完成 | wrap or callback |
| `EXIT` | `MultiDayRunner.run_multi_day` finally + atexit | shutdown hook |
| `MEMSTAT` sample | `_on_tick_end_memory` 替代既有 hook | 现有 hook 改造 |

### D8: 测试策略 — 真测量优先

5 类 e2e test：

1. `test_memstat_rss_matches_real_alloc`: subprocess 内分配 N MB 后
   读 memstat，verify `memory.rss_mb` delta >= 0.8 × N MB
2. `test_phase_event_order_real_dev_smoke`: 跑 50 agent × 1 day，
   verify events.jsonl phase 顺序 = `PROCESS_START → SETUP_START →
   SETUP_DONE → ... → TICK_LOOP_START → ... → EXIT`
3. `test_eviction_event_matches_real_store_delta`: 跑 dev smoke 让
   eviction 触发，verify EVICT event 的 `events_evicted` 等于
   memory_store size 实际 delta
4. `test_retry_event_emits_per_real_attempt`: mock op 抛真
   `openai.APIConnectionError` 2 次后成功，verify events.jsonl 有
   恰好 2 个 RETRY events，每个带 attempt_idx + backoff_sec
5. `test_current_rss_not_lifetime_peak`: 分配 500MB → 读 RSS → 释放 +
   gc → 再读 RSS。新值 SHALL <= 旧值（psutil 当前）；与 ru_maxrss
   永远 >= 旧值形成对照

mock 测试只用于：JSONL 解析、文件 IO 错误处理、env override 等机制
层面。

### D9: env 配置

| env | 默认 | 含义 |
|---|---|---|
| `INSTRUMENTATION_DISABLE` | 未设 = 启用 | `1` = 完全禁用（生产救火） |
| `INSTRUMENTATION_OUTPUT_DIR` | `<suite_dir>/variant_<v>/` | JSONL 输出目录 |
| `INSTRUMENTATION_SAMPLE_EVERY_N_TICKS` | 12 | memstat 采样间隔 |
| `LLM_SAMPLE_RATE` | 0.01 | LLM call 采样比例（错误 100% 不受此限） |
| `LLM_RECORD_ERRORS_ALL` | true | 错误/retry 100% 记录 |

### D10: Failure isolation — 埋点 SHALL NOT crash 业务

每个 emit 用 try/except 包：
```python
def emit_event(self, kind, **kw):
    try:
        self._events_fh.write(json.dumps({...}) + "\n")
    except Exception as exc:  # noqa: BLE001
        # Best-effort. Don't crash worker on logging failure.
        logger.warning("[instrumentation] emit_event failed: %s", exc)
```

### D11: JSON schema 演进 — `version` 字段

每行 JSON 第一个字段 `"v": 1`。schema 改动时 bump version + tools
向后兼容旧版本。

## Risks / Trade-offs

**[R1] psutil.memory_info() 每 tick 调用太频繁**
→ Mitigation: 只在 `tick % sample_every_n_ticks == 0` 时采样，默认
  12 tick = 一次/min 在 publishable scale，开销 < 5ms × 1/12 = 0.4ms
  per tick = 可忽略

**[R2] llm.jsonl 文件爆大**
→ Mitigation: 默认 sample 1/100，错误 100% 记。14 day publishable
  cell ≈ 40k success + 几千 error rows ≈ 6-8MB. 可接受。可设 
  `LLM_SAMPLE_RATE=0` 完全关 success（只记 error）。

**[R3] 三 JSONL 文件 fd 长开**
→ Mitigation: line-buffered 模式（`buffering=1`），每行 flush。崩
  溃时数据保留到最后一行 atomic write。`atexit` 注册 close。

**[R4] Per-handler 累计 dict 内存增长**
→ Mitigation: 用滑动窗口（最近 N=1000 calls）而非全累计。env
  `INSTRUMENTATION_HANDLER_WINDOW=1000`。

**[R5] psutil 在 production env 未安装（runtime-only 用户）**
→ Mitigation: D2 的 fallback path + 日志警告。把 `psutil` 升到
  runtime extras（`[full]`），dev 仍可用。或：保持 dev-only + 警告。
  选项之后跟用户确认。**初版选择保持 dev-only + warning**（不强升
  runtime deps，避免 surprises）。

**[R6] Phase event 桩点错位（forget 一个 hook 点）**
→ Mitigation: D7 表 + test_phase_event_order_real_dev_smoke 顺序
  断言抓漏；并且 PROCESS_START / EXIT 用 `atexit` 兜底，保证至少
  能看到进程边界。

**[R7] 改 `_self_rss_mb` 影响既有 RSS cap 行为**
→ Mitigation: 17 个 mock-based tests 不动（它们测的是 cap 机制不是
  RSS 值），但**新加 `test_current_rss_not_lifetime_peak` 验证修复**
  + e2e `test_rss_cap_uses_current_not_peak` 验证 cap 不再被一次
  峰值永久 trip

## Migration Plan

1. **部署**：纯 in-process Python，无 DB / 外部状态。worker restart
   即生效。
2. **回滚**：env `INSTRUMENTATION_DISABLE=1` 完全关。`_self_rss_mb`
   旧实现保留为 `_legacy_self_rss_mb_ru_maxrss` 直到 v2，可通过
   env `RSS_USE_RU_MAXRSS_LEGACY=1` 切回（仅用于诊断对比）。
3. **验证**：跑 dev smoke 50 agent × 1 day 看 3 JSONL 文件 + log
   `[memstat]/[evict]/[retry]/[snapshot]` 行 → 真测试 5 个 e2e 全
   绿 → publishable resume single cell 实跑 30 min 观察。
4. **观察**：tail_memstat.py 实时看 memstat 流，analyze_memstat.py
   离线汇总。

## Open Questions

- (闭合) JSONL vs SQLite？答：D1 选 JSONL。
- (闭合) memstat 采样间隔？答：D4 选 12 tick。
- (闭合) LLM 采样比例？答：D5 选 1/100 + 错误全记。
- (闭合) psutil 升到 runtime 必需？答：R5 选 dev-only + warning。
- 还需用户决定：`tail_memstat.py` UI 风格 — 简单 print vs rich-table?
  默认选简单 print（rich 增加新依赖）。
