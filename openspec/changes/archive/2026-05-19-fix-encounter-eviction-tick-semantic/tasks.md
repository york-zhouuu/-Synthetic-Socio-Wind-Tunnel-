## 1. TDD red — integration test 真跑 dev smoke 验证 encounter 留存

这是关键 — 这个 test 就是之前漏掉的"读真 artifact 验证 product invariant"。

- [x] 1.1 新建 `tests/test_encounter_eviction_integration.py`:
  - `test_encounter_events_present_after_4day_smoke`
    (真跑 50 agent × 4 day dev smoke → 读 final snapshot.json →
    aggregate encounter event 数量 > 0)
  - `test_encounter_events_evicted_outside_grace_window`
    (day_index < (4-2) 的 encounter 全被 evicted)
  - `test_encounter_events_within_grace_present`
    (day_index >= 2 的 encounter SHALL 在 final snapshot 里存在)
- [x] 1.2 跑 → 红（当前 bug 让全部 encounter 被 evict）

## 2. TDD red — unit test signature 转 before_day_index

- [x] 2.1 改既有 `tests/test_memory_store_encounter_eviction.py` 把
  `before_tick=N` 改为 `before_day_index=N`，event 构造 explicit
  `day_index` 字段
- [x] 2.2 改既有 `tests/test_memory_service_cross_agent_evict.py`
  同步
- [x] 2.3 跑 → 红（API signature 不匹配）

## 3. 实现 MemoryStore.evict_cold_encounter_events 改 signature

- [x] 3.1 `synthetic_socio_wind_tunnel/memory/store.py`:
  - 参数 `before_tick: int` → `before_day_index: int`
  - filter `ev.tick < before_tick` → `ev.day_index < before_day_index`
  - 更新 docstring 反映修复
- [x] 3.2 跑 G2 改后的 unit test → 转绿

## 4. 实现 MemoryService.evict_cold_encounter_events_across_agents

- [x] 4.1 `synthetic_socio_wind_tunnel/memory/service.py` 参数同步
- [x] 4.2 instrumentation EVICT event 字段 `before_tick_cutoff` →
  `before_day_index`（schema 改动，但 events.jsonl 是诊断用，向后
  不兼容可以接受）

## 5. 实现 MultiDayRunner 2 个调用点

- [x] 5.1 `multi_day.py` day_end hook:
  - 旧: `encounter_cutoff_tick = max(0, day_index - grace) * ticks_per_day`
  - 新: `before_day_index = max(0, day_index - grace)`
  - 调用 `evict_cold_encounter_events_across_agents(
    before_day_index=before_day_index)`
- [x] 5.2 `multi_day.py` `_write_snapshot` pre-write hook 同步
  （`prune-before-snapshot-write` 引入的那段）
- [x] 5.3 跑 G1 integration test → 转绿

## 6. Regression

- [x] 6.1 跑既有 `tests/test_memory_*.py` → 全绿
- [x] 6.2 跑既有 `tests/test_snapshot_pre_write_prune.py` →
  改 signature 后仍绿
- [x] 6.3 跑全量 1872+ test → 不退化

## 7. 文档 + CLAUDE.md

- [x] 7.1 CLAUDE.md `snapshot-pre-write-prune` 段更新 — `before_tick`
  → `before_day_index`
- [x] 7.2 CLAUDE.md 新加段 **"端到端 integration test 强制"** 
  capability 创建时的不变量（永远 add 1 个 real-artifact-reading
  test），承接 backlog 1.15 preflight 思路

## 8. Spec validate + archive

- [x] 8.1 `openspec validate fix-encounter-eviction-tick-semantic --strict`
- [x] 8.2 tasks.md 全 [x]
- [x] 8.3 `openspec archive fix-encounter-eviction-tick-semantic --yes`
- [x] 8.4 commit + push
