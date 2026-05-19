## 1. TDD red — pre-write evict 触发

- [x] 1.1 新建 `tests/test_snapshot_pre_write_prune.py`:
  - `test_evict_called_before_snapshot_write_at_grace_threshold`
    (mock `_write_snapshot` 内部 + 真 MemoryService 含 100 events，
    断言 evict 调用顺序 < write_atomic 调用)
  - `test_evict_skipped_when_day_below_grace`
    (day_index=1, grace=2 → cutoff=0 → 不 evict)
  - `test_env_disable_snapshot_prune_skips_evict`
    (SNAPSHOT_PRUNE_BEFORE_WRITE=0 → 旧 behavior)
  - `test_evict_failure_does_not_block_snapshot_write`
    (mock evict 抛 RuntimeError → snapshot 仍落盘)
- [x] 1.2 跑 → 红

## 2. TDD red — snapshot 文件大小验证 (真实测量)

- [x] 2.1 新建 `tests/test_snapshot_size_reduction.py`:
  - `test_pre_write_prune_reduces_snapshot_size_real_dev_smoke`
    (跑 50 agent × 4 day dev smoke 两次：env=on vs env=0；
    比较 final snapshot size，on < off)
  - `test_pruned_snapshot_resumable_correctly`
    (跑 dev smoke → spawn 新 worker resume → 验证 tick advance)
- [x] 2.2 跑 → 红

## 3. TDD red — SNAPSHOT_WRITE event 含 events_evicted_before_write

- [x] 3.1 新建 `tests/test_snapshot_event_evict_count.py`:
  - `test_snapshot_event_includes_evict_count`
    (mock events.jsonl 读取 → 验证 SNAPSHOT_WRITE 含
    events_evicted_before_write 字段)
- [x] 3.2 跑 → 红

## 4. 实现 _write_snapshot pre-write evict

- [x] 4.1 在 `synthetic_socio_wind_tunnel/orchestrator/multi_day.py::
  _write_snapshot` 添加：
  - 读 `MEMORY_EVENT_EVICT_GRACE_DAYS` (默认 2)
  - 读 `SNAPSHOT_PRUNE_BEFORE_WRITE` (默认 true)
  - 计算 `cutoff = max(0, day_index - grace) * ticks_per_day`
  - 若 enabled 且 cutoff > 0 且 `_memory_service` 有
    `evict_cold_encounter_events_across_agents` 方法 → 调用，
    捕获 evicted count
  - try/except 包裹，失败 log warning 不抛
- [x] 4.2 把 evicted_before_write count 传给 emit_snapshot_write
- [x] 4.3 跑 G1 测试 → 转绿

## 5. 实现 SNAPSHOT_WRITE event 字段扩展

- [x] 5.1 在 `synthetic_socio_wind_tunnel/observability/instrumentation.py::
  emit_snapshot_write` 加可选参数
  `events_evicted_before_write: int = 0`，传递到 event payload
- [x] 5.2 修改 multi_day.py 调用 emit_snapshot_write 时传入实际 evict 数
- [x] 5.3 跑 G3 测试 → 转绿

## 6. E2E 真实 dev smoke 验证

- [x] 6.1 dev smoke 50 agent × 4 day (default grace=2)：
  - 跑一次默认（pre-write prune ON）
  - 跑一次 SNAPSHOT_PRUNE_BEFORE_WRITE=0
  - 比较最后一个 snapshot 文件大小 → on 应显著 < off
- [x] 6.2 跑 G2 测试 → 转绿

## 7. Regression

- [x] 7.1 跑既有 `tests/test_run_resilience_*.py` 全绿
- [x] 7.2 跑既有 `tests/test_memory_service_cross_agent_evict.py` 全绿
- [x] 7.3 跑全量 1856+ test 不退化

## 8. 文档

- [x] 8.1 修改 CLAUDE.md `runtime-instrumentation` 或新加段：
  - 加 "snapshot pre-write prune" 不变量
  - 标注 grace 配置共享、env 一键 disable
- [x] 8.2 修改 `tools/resume_publishable.py` docstring 提到
  新 snapshot 自然 lean（不需要手动 prune）

## 9. Spec validate + archive

- [x] 9.1 `openspec validate prune-before-snapshot-write --strict`
- [x] 9.2 tasks.md 全 checkbox → [x]
- [x] 9.3 `openspec archive prune-before-snapshot-write --yes`
- [x] 9.4 commit + push
