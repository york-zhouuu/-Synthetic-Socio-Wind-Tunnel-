## Why

2026-05-20 实测 publishable resume 复盘暴露：所有 RAM 优化（cold-prune
encounter / malloc_zone_pressure_relief / RSS cap）**都触发在 tick loop
内部**，覆盖不到 **worker 启动期 snapshot 反序列化 35GB 峰值**。worker
在进入 tick loop 之前就 OOM 风险拉满。

但这个峰值的根源是**snapshot 文件本身太大**——seed_42_tick3444.snapshot.json
6GB，Python 反序列化 5-10× 膨胀 = 30-60GB。

**snapshot 大是因为 `memory_store_state` 含 6M+ 个 encounter events
（93.5% of snapshot bytes）**——这些 events 99% 是 day_index < (current - 2)
的冷数据，按 cold-prune grace 本来就应该被 evict 掉，**只是 evict 只在
day_end 触发，没在 snapshot write 之前触发**。

→ snapshot 写盘前先 evict 一次，snapshot 文件直接砍 90%（6GB → 600MB），
下次 resume 反序列化峰值从 35GB 砍到 3-6GB，**远低于 10GB cap**。

修复成本：在 `MultiDayRunner._write_snapshot` 前加 1 次 evict 调用
（复用现有 `evict_cold_encounter_events_across_agents`）+ 2-3 个 test。

## What Changes

- **`MultiDayRunner._write_snapshot`** 在写盘前 SHALL 调用
  `_memory_service.evict_cold_encounter_events_across_agents(
  before_tick=max(0, day_index - grace) * ticks_per_day)`，复用既有
  cold-prune 逻辑 + grace 配置（env `MEMORY_EVENT_EVICT_GRACE_DAYS`，
  默认 2）。
- 写盘后 emit 既有 SNAPSHOT_WRITE event（已由 comprehensive-runtime-
  instrumentation 记录），新增 `events_evicted_before_write` 字段反映
  本次 prune 释放的事件数。
- env override `SNAPSHOT_PRUNE_BEFORE_WRITE`（默认 `true`）允许关闭
  此行为（仅用于诊断 / 旧 snapshot 格式回放）。

NOT in scope:
- 不改 cold-prune 逻辑本身
- 不改 day_end eviction 触发（保持既有，作为 redundancy）
- 不改 snapshot 文件格式 / msgpack 等架构改动
- 不改 partial 文件（不含 memory_store_state）

## Capabilities

### Modified Capabilities

- `tick-level-resume`: snapshot 写盘前 SHALL 先 evict 冷 encounter 事件，
  确保落盘 snapshot 文件大小被 grace window 上限约束。

### New Capabilities

无。

## Impact

**Affected code**:
- `synthetic_socio_wind_tunnel/orchestrator/multi_day.py::_write_snapshot`
  +5 lines 调用 evict
- 既有 `_collect_day_end_observability` / day_end hook 保持不变

**Affected behavior (positive)**:
- 每个 snapshot 文件落盘前自然瘦身 90%（实测 6GB → 600MB 估算，
  基于 enforce-worker-rss-cap eviction 实测 −37.5% events × 多 day
  累积）
- 下次 resume 加载时间 ~10 min → ~1 min
- Resume 时 RAM 峰值 35GB → 3-6GB，远低于 10GB cap
- 不再需要 `partial-only` 等绕行方案，`auto` 自然安全

**Affected behavior (negative)**:
- 每次 snapshot write 多花 ~0.3-1 sec（eviction 调用本身）—— 在
  snapshot write 本身 ~10 sec 的占比里可忽略
- 如果某代码逻辑依赖 snapshot 里的"完整历史 encounter events"
  （我们查过，**没有**——agent.do_something 只看近 2 day 的 retrieve），
  会受影响。但这本来就是 cold-prune 设计假设。

**Dependencies**: 无新依赖。

**Test impact**: 3 个新 test（snapshot 写盘前 evict 调用 / snapshot
文件大小确实变小 / resume 仍然成功）。既有 1856 不动。

**Migration**:
- 旧 snapshot 文件（reusme 来源）不动，仍然能 load（但慢）
- 新生成的 snapshot 自然瘦
- env `SNAPSHOT_PRUNE_BEFORE_WRITE=0` 可一键关闭新行为回退
