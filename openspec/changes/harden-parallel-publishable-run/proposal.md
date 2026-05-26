## Why

2026-05-21 整晚 seed-43 publishable run（4-worker 并行 → baseline-prefix
day 0-3 + fork day 4-13）暴露 4 类阻塞问题。本次 run 之后 commit `51e0e90` +
`6c89938` 修了其中 3 个表层（plan_gen wait_for / aggregate empty-list /
parallelize daily_summary）但**根因没修**——cold-prune evict 实际无效，
snapshot 永远不缩，进而 fork resume RSS peak 撞 cap。

**下次 4-worker 并行 publishable 跑之前 SHALL 修的事情**（按 ROI 排序）：

### 阻塞项（必修）

1. **backlog 1.20: cold-prune evict 0 events 根因 audit + 修**

   2026-05-21 实测 EVICT event 显示：
   ```json
   {"kind":"EVICT","before_day_index":1,"events_evicted":0,
    "memory_store_total_before":4426274,
    "memory_store_total_after":4426274}
   ```

   evict 函数 walk 4.43M events 一个没动。3 个 hypothesis（需 audit 定位）：
   - encounter events 都打了错的 day_index（全用 record time 的 current_day）
   - kind 字段不是 `"encounter"`（ai-town port 改名了？）
   - schema 升级后 day_index 字段 None / 缺失

   修这个之后，**backlog 1.6 (snapshot-resume-ram-peak) 才真正算解决**。

2. **streaming snapshot serialization**

   即使 evict 修好，4+ day 累积的 memory_store 仍有 1-2M events。当前
   `SimulationCheckpoint.write_atomic` 用 `json.dumps(self.model_dump(...))`
   先 build 整个字符串再 write → **2× RSS peak during write**。改用 orjson +
   streaming 输出（不 build 整个 string）。

3. **publishable e2e memory profile test**

   real-artifact 测试：跑 1000 agent × 4 day × 1 seed dev smoke，断言：
   - 每 day_end 后 EVICT event 的 `events_evicted > 0`（当 day_index >= grace）
   - snapshot 文件 size 不单调增长（day 4 末 ≤ day 3 末）
   - RSS day 4 末 < day 0 末 × 2

   这是 backlog 1.20 + 1.6 修复的产品级 guard。**没这个 test，下次"修了"的 bug 还会回来**。

### 推荐项（如果有时间）

4. **backlog 1.7 encounter event aggregation**

   encounter events 是 memory_store 90%+ 体积。但 99% 用例只需 "A 跟 B 当天见
   了 N 次" counter，不需要每次的 location/tick/text。

   ```
   当前: 每对相遇 → 1 个完整 MemoryEvent
   改: encounter_counter = dict[(A, B, day), int]
       只在升级为 dialogue 时才写完整 event
   ```

   → memory_store 体积 10× 降。但工程量大（1-2 day）。

5. **fork suite 一站启动脚本固化**

   2026-05-21 用了 ad-hoc `/tmp/swt-v5-fork-day4to13.sh`。固化为
   `tools/spawn_fork_variants.py`，参数化 BASE_SUITE + GRACE override + stagger
   时长。

6. **审计 LLM_RECORD_ERRORS_ALL=true 真的 100% 记录吗**

   2026-05-21 发现 events.jsonl 字段经常 null（ts、day_index）。可能 ts_iso
   不是 expected schema。需要 verify。

## What Changes

### Modified Capabilities

- **memory-event-eviction**: `evict_cold_encounter_events` SHALL evict events
  matching expected kind + day_index criteria; SHALL log diagnostic counts
  (total / encounter_count / with_day / old_enough) on each invocation; new test
  SHALL verify `events_evicted > 0` when day_index >= grace_days.

- **tick-level-resume**: `SimulationCheckpoint.write_atomic` SHALL use
  streaming JSON serialization (orjson) to avoid 2× RAM peak during write.

- **runtime-instrumentation**: events.jsonl SHALL preserve all schema fields
  (ts, day_index, etc.) — null-safe write path with field validation.

### New Capabilities (optional, if time allows)

- **encounter-aggregation**: encounter events aggregated to per-(A, B, day)
  counter instead of full MemoryEvent. Only upgraded events (dialogue / share)
  store full event.

## Impact

**Affected code (required items)**:
- `synthetic_socio_wind_tunnel/memory/store.py::evict_cold_encounter_events`
  — audit + fix root cause
- `synthetic_socio_wind_tunnel/memory/service.py::record` — verify encounter
  events get correct day_index + kind
- `synthetic_socio_wind_tunnel/run_resilience/state_snapshot.py::write_atomic`
  — streaming serialization
- `tests/test_publishable_memory_profile.py` (new) — e2e RAM guard
- `synthetic_socio_wind_tunnel/observability/instrumentation.py` — schema
  validation

**Affected behavior**:
- snapshot file size: 1-2GB → ~200-500MB after evict fix
- fork resume RSS peak: 10-20GB → 2-5GB per worker
- 4-worker parallel sustainability: marginal → comfortable
- Day 0-3 cumulative wall: similar (no change)
- Day 4-13 fork wall: ~17-25h → ~10-15h (less restart pressure)

**Non-goals**:
- 不重写 memory_store 架构（仅 evict + serialization 修复）
- 不改 cold-prune grace 默认值（保持 GRACE_DAYS=2 in CLAUDE.md，spawn template）
- 不改 LLM provider routing
- 不动 parallelize-day-end-llm-batches (已 ship)

**Test 策略 (real-artifact, 不 mock)**:
- 单测 1: evict_cold_encounter_events on 100-agent fixture with day_index spread,
  verify expected evict counts (not 0)
- 单测 2: streaming snapshot vs current json.dumps — same output bytes
- 集成 test (1000 agent × 4 day smoke): EVICT events show > 0 evicted at day 3+
- 集成 test: snapshot file size at day 0 vs day 4 — day 4 smaller

**Risk mitigation**:
- 改 evict 时不要破坏 backward compat — 老 snapshot 仍要 load 得了
- streaming JSON SHALL produce byte-identical output to verify no data loss
