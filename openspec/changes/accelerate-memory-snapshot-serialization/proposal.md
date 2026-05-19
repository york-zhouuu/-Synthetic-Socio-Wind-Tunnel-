> **⚠️ STATUS: REFUTED — NOT APPLIED (2026-05-19)**
>
> Kept in repo as "we tried this and it didn't work" record. The
> 5× speedup target asserted in the spec was empirically refuted:
> measured `_event_to_json_fast` vs `_event_to_json_legacy` ratio
> at N=10,000 events was ~3.5× (median 9.6ms vs 33.4ms), well
> short of the 5× floor. Root cause: the work is irreducible at
> Python level — every event still goes through `asdict()` /
> field-by-field copy / dict construction. No purely-faster
> implementation exists without an architectural change (e.g.
> incremental snapshot diffs, or moving event serialization into
> a C extension).
>
> The architectural change that actually solves the underlying
> RAM/CPU problem is in `enforce-worker-rss-cap` (2026-05-19):
> cut **how many events** are serialized (cold prune encounter
> events at day_end), not **how fast** each event serializes.
>
> See `tests/test_event_to_json_performance.py` for the
> empirical refutation (xfail-marked); kept as historical budget
> for any future revisit.

## Why

2026-05-19 19:25 实测 publishable single worker（PID 30151, seed42
phone_friction, day 11 in-flight）拿到 30s py-spy 火焰图（2999/3000
samples），**真热点**：

```
run_multi_day                                      100%
  → _fire (on_tick_end hooks)                      100%
  → _on_tick_end_resume_hook (multi_day:665)       100%
  → _write_snapshot (multi_day:952)                100%
  → memory.service::to_snapshot_state (line 165)   100%
    → <listcomp> over events                       99.9%
      → _event_to_json (service:980-987)           78.23% on single line 985
```

**所有此前推测全部推翻**：
- ❌ backlog 1.14 KD-tree encounter detection — 不在热路径
- ❌ profile-publishable-hot-path 找出的 `events_at_tick` — 有问题但**不
  dominant**
- ❌ "LLM call wait dominates" — dev scale 没采到 snapshot 大量出现的
  那段时间
- ✅ **`memory.service:to_snapshot_state` → `_event_to_json` 占 100% CPU**

机制分析：

- `state_snapshot.SnapshotPolicy.every_ticks=12` (今天 harden-worker-resilience
  default) → 一天 288 tick / 12 = **24 次 snapshot/day**
- 每次 snapshot 调 `memory_service.to_snapshot_state()` →
  `[_event_to_json(ev) for ev in store.all()]` per agent
- 累积到 day 11：N agent × N day × N events/day = 数十万 MemoryEvent
- `_event_to_json` 是 per-event Python loop：`isinstance` × len(fields) +
  `getattr` × len(fields) + datetime/tuple 类型 coerce
- 每 snapshot 全量 re-serialize 所有累积 events → **O(N_total_events) per
  snapshot × 24 snapshot/day = O(N²)** over day

memory sawtooth 模式（16↔36GB / 20GB 振幅）也由此解释：list comprehension
生成巨大临时 list of dict，snapshot 写完释放，下次又生成。

**目标**：5× 以上 `_event_to_json` speedup → snapshot serialize 时间从
"占满 CPU 30s+" 降到 "几秒"。tick wall clock 跟着大降，单 worker
publishable 估 14h → 2–4h（**不靠多核**）。

## What Changes

**Scope 严格限定**：仅改 `synthetic_socio_wind_tunnel/memory/service.py:
_event_to_json` 单函数。不动 MemoryEvent 定义、不动 snapshot 频率、
不动其它热路径。

候选实现路径（决策见 design.md）：

**A. `dataclasses.asdict` + post-process datetime/tuple** — 利用 CPython
3.11+ asdict 的 C-level field walk，再回手工 coerce datetime/tuple。
估 3-5× speedup，0 新依赖。

**B. 内联 `__dict__` view + slot direct read** — 跳过 isinstance
分发，直接 type-dispatch on field name (`embedding=list`,
`occurred_at=datetime` 等)。估 5-10× speedup，0 新依赖。

**C. msgspec.Struct 替换 dataclass MemoryEvent** — C-level serialize；
估 20-50× speedup 但**改 MemoryEvent 定义**，影响面大。Non-goal。

本 change scope = **B (类型特定 dispatch)** 或 **A (asdict + coerce)**
中实测更快者。先写 benchmark test（Layer 3）选定。

## Capabilities

### New Capabilities

（无——本 change 只是单函数性能优化，不引入 capability。）

### Modified Capabilities

- `tick-level-resume`: 新增 Performance Requirement —
  `MemoryService.to_snapshot_state` 对 N=10_000 MemoryEvent SHALL 在
  baseline 的 1/5 时间内完成（即 5× speedup floor）。byte-equivalence
  round-trip Requirement 已在 spec 中，本 change 不改语义。

## Impact

**代码**：
- `synthetic_socio_wind_tunnel/memory/service.py::_event_to_json` —
  重写实现（保留同名 + 同签名）
- 可能加 helper: `_event_to_json_fast` 作为内部 fast path，旧 path 保留
  作 fallback

**测试**：
- 新增 `tests/fixtures/memory_event_round_trip_corpus.json` — 50 个手写
  MemoryEvent 覆盖各 kind / 边界字段
- 新增 `tests/test_event_to_json_round_trip.py` —
  - byte-equivalence: corpus 每个 event 经 fast path 与旧 path output 一致
  - field-by-field assert: 不依赖整体 dict equality，逐字段对（catch
    顺序问题）
- 新增 `tests/test_event_to_json_performance.py` —
  - N=10000 event serialize benchmark，断言 fast/baseline ≤ 0.2
    (5× speedup floor)
  - marked `@pytest.mark.slow`
- 扩展既有 `tests/test_subsystem_snapshot.py::MemoryService` round-trip
  断言：byte-equal 不只是 reload-不抛
- E2E differential test：跑 dev smoke 100 agent × 1 day with old vs new
  `_event_to_json`，seed_42.json 的 memory_store_state byte-equal

**Non-goals (explicit)**:
- 不改 MemoryEvent dataclass 定义 / 不引入 msgspec / orjson 依赖
- 不实施 incremental snapshot（只 dump 新 events）— 留 follow-up
  `incremental-memory-snapshot`
- 不调 RESILIENCE_SNAPSHOT_EVERY_TICKS — 留 follow-up
- 不改 `events_at_tick`（这是 profile-publishable-hot-path 给的 hot path，
  但 snapshot 序列化此时是更 dominant 的瓶颈；下个 change `index-memory-
  events-by-tick` 单独做）
- 不优化 dialogue_service / attention_service serialize（同样 _to_json
  pattern 但 events 是大头）

**测试 ROI 验证**:
- 优化后再跑一次 30s py-spy on dev smoke worker
- 断言 `_event_to_json` cumulative % 从 78% 降到 < 10%
- 若新热点出现（比如 `write_atomic` json.dumps 自身），记进下个 change
  proposal
