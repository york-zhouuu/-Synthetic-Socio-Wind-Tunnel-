## 1. TDD 红 — corpus fixture + round-trip tests 先于 fast path 实现

- [ ] 1.1 写 `tests/fixtures/memory_event_round_trip_corpus.json` — 50 个手工 MemoryEvent 序列化字典覆盖：
  - 6 个 kind 各 ≥ 5 case (conversation / reflection / observation / encounter / daily_summary / life_history)
  - 边界：embedding=() / 1536-dim / unicode / emoji / control char / epoch / future / None importance / nested metadata
- [ ] 1.2 写 `tests/test_event_to_json_round_trip.py`：
  - load corpus → MemoryEvent → fast_path & legacy_path 都跑 → 断言 dict 相等 + key 顺序相等
  - 失败 error 含 event index + 不等字段
- [ ] 1.3 跑 → 红（fast path 还没实现）

## 2. TDD 红 — performance benchmark test

- [ ] 2.1 写 `tests/test_event_to_json_performance.py` (slow marker):
  - 构造 10_000 个 MemoryEvent (随机字段)
  - 跑 baseline 3 trial，fast path 3 trial，median ratio assert ≤ 0.2
  - 失败 error 含 absolute timings + ratio + 哪个实现 (A/B/none)
- [ ] 2.2 跑 → 红（fast path 不存在）

## 3. TDD 红 — fault injection (env fallback)

- [ ] 3.1 写 `tests/test_event_to_json_fallback.py`：
  - env `MEMORY_SNAPSHOT_USE_FAST=0` → 调 `_event_to_json` SHALL 走 legacy
  - module-level patch 跟踪调用哪个 branch
- [ ] 3.2 跑 → 红

## 4. 实现两个 fast path 候选 (A & B)

- [ ] 4.1 实现 A: `_event_to_json_asdict` 用 `dataclasses.asdict(ev)` + post-process datetime / tuple
- [ ] 4.2 实现 B: `_event_to_json_typed` 手工字段 dispatch (硬编码 field name → coerce rule)
- [ ] 4.3 用 Layer 3 benchmark 实测两者 ratio，选 winner 作为 production `_event_to_json_fast`
- [ ] 4.4 公共 entrypoint `_event_to_json` 由 env `MEMORY_SNAPSHOT_USE_FAST` (default 1) 切换 fast/legacy
- [ ] 4.5 legacy 路径 rename 为 `_event_to_json_legacy` 保留

## 5. 转绿 — 跑 Layer 1-3 tests

- [ ] 5.1 round-trip tests 全绿（byte-equivalent for all 50 corpus events）
- [ ] 5.2 performance benchmark 绿 (median ratio ≤ 0.2)
- [ ] 5.3 fault injection 绿（env 切换走对路径）

## 6. E2E differential test

- [ ] 6.1 跑 dev smoke 100 agent × 1 day with `MEMORY_SNAPSHOT_USE_FAST=0`，dump seed_42.json_legacy
- [ ] 6.2 跑同样 smoke with `MEMORY_SNAPSHOT_USE_FAST=1`，dump seed_42.json_fast
- [ ] 6.3 写 `tests/test_seed_json_byte_equal.py` (slow): 加载两 JSON, deep-compare `memory_store_state.agent_events`. 任一 event 不等 → error 标 agent_id + event_index + 哪个字段不等
- [ ] 6.4 全绿（含既有 1680 + 新增 11+ tests）

## 7. py-spy 二次采样 + 写 baseline 文档

- [ ] 7.1 起 dev smoke worker（独立测试 PID），跑到 day boundary 附近
- [ ] 7.2 `sudo py-spy record -o /tmp/post.svg --pid <pid> -d 30`
- [ ] 7.3 从 SVG 提取 `_event_to_json` cumulative %，断言 < 10%
- [ ] 7.4 写 `docs/post-optimization-flamegraph-2026-05-19.md` 含 SVG screenshot + new top hot path identification

## 8. Spec validate + archive

- [ ] 8.1 既有 `tests/test_subsystem_snapshot.py::MemoryService` 仍绿 (round-trip 总等价)
- [ ] 8.2 `openspec validate accelerate-memory-snapshot-serialization` 通过
- [ ] 8.3 `openspec archive accelerate-memory-snapshot-serialization`
- [ ] 8.4 commit + push（建议拆 2 个 commit：tests+fixture 一个、impl+archive 一个）
