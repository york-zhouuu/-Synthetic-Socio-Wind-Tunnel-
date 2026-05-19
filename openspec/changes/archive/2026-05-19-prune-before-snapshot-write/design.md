## Context

`MultiDayRunner._write_snapshot()` (multi_day.py:1048) writes a
`SimulationCheckpoint` containing `memory_store_state` =
`memory_service.to_snapshot_state()`. The memory_store has been
accumulating encounter events all day; at day 11 it has 6M+ events,
93.5% of which are `kind="encounter"` from days 0-9 (cold data with
grace=2).

The `_init_memory_management_hooks` day_end hook already runs
`evict_cold_encounter_events_across_agents(before_tick=...)` at
end-of-day. But snapshot writes fire every `RESILIENCE_SNAPSHOT_EVERY_TICKS`
ticks (default 12 → twice per day at 24 ticks/snap, but typically every
12 ticks for publishable runs = every ~2-3 minutes). So between
day_end events, snapshots still contain hot+cold data.

If we prune **immediately before** snapshot write, the snapshot file
is bounded by the same grace window — every snapshot is lean.

## Goals / Non-Goals

**Goals:**
- snapshot 文件大小约束在 last `grace_days` 的 encounter 事件容量内
- 复用既有 cold-prune 逻辑 + grace 配置，无新参数
- resume 加载峰值 RAM 大幅下降
- 不影响 retrieval semantics（agent.do_something 看不到的事件 evict 掉）
- env 一键回退

**Non-Goals:**
- 不改 cold-prune 算法本身
- 不改 partial 文件
- 不改 snapshot 序列化格式
- 不改 day_end eviction（保留 — 现在变成 redundant safety net）
- 不引入新依赖

## Decisions

### D1: Evict 在 snapshot write **前** 而不是 **后**

理由：
- evict 后立刻写 → 写出的 snapshot 就是 lean 的
- evict 后 → memory_store.to_snapshot_state() 看到的是 prune 之后的数据
- 反之"先写后 evict"等价于今天不变（snapshot 还是大）

### D2: Grace 配置复用既有 `MEMORY_EVENT_EVICT_GRACE_DAYS` (默认 2)

不引入新 env。day_end eviction 和 snapshot-time eviction 用**同一个**
grace window，确保不变量"任何时刻 memory_store 持有的 encounter
events SHALL ≤ last `grace` days"始终成立。

### D3: 边界 — 当 day_index < grace 时不 evict

```python
cutoff = max(0, day_index - grace) * ticks_per_day
if cutoff <= 0:
    # First `grace` days: no eviction yet
    return  # skip evict, write whole snapshot
```

理由：early-day snapshot 量小（前几 day events 累积少），不需要 prune。

### D4: env 回退 `SNAPSHOT_PRUNE_BEFORE_WRITE`

默认 `true`（自动 prune）。设 `0`/`false` 关闭，恢复旧行为（写完整
snapshot）。用于：
- 旧 snapshot 格式回放对照
- 调试需要看完整历史 events 的场景

### D5: 不阻塞 snapshot write — evict 失败不影响写盘

```python
try:
    evicted = self._memory_service.evict_cold_encounter_events_across_agents(
        before_tick=cutoff,
    )
except Exception as exc:  # noqa: BLE001
    logger.warning(
        "[snapshot] pre-write evict failed: %s — snapshot will be "
        "larger than ideal but write will proceed", exc,
    )
    evicted = 0
# Continue to snapshot write
```

### D6: SNAPSHOT_WRITE event 新增 `events_evicted_before_write` 字段

让 instrumentation 能直接展示"这次 prune 释放了多少 events"，
post-mortem 时一目了然看到优化效果。

## Risks / Trade-offs

**[R1] retrieval-time 访问已 evict 的 event**
→ agent.do_something 内的 MemoryRetriever 只检索近 N day（具体由
  CarryoverContext window 控制，默认 ~3 day）。grace=2 → evict tick <
  (day-2)*288，所以 last 2 day events 完整。retrieval window ≤ grace
  时安全。这是 cold-prune 设计假设，不变。

**[R2] evict 失败时 snapshot 还是大**
→ Mitigation: D5 fail-safe，evict 异常时 log warning 但仍写 snapshot
  （仍然有数据但是大）。

**[R3] 早期 day（day_index < grace=2）snapshot 依然完整大小**
→ Acceptable — 早期 day 累积少，size 本来就小。

**[R4] 调试时需要完整历史 events**
→ Mitigation: D4 env 一键关。

**[R5] 单元测试 memory_service mock 不一定 expose evict 方法**
→ Mitigation: 调用前 `hasattr` 检查。

## Migration

1. **新代码部署**：worker restart 即生效，下一个 snapshot 自动 prune
2. **旧 snapshot 继续可用**：旧的"胖"snapshot 仍能 load（但仍然慢）；
   一旦 resume 进入 tick loop + 下一次 snapshot 就是新瘦版
3. **回退**: env `SNAPSHOT_PRUNE_BEFORE_WRITE=0` 立即 disable

## Open Questions

- (闭合) grace 用既有还是新加？答：D2 复用既有
- (闭合) evict 在前还是后？答：D1 在前
- 还需用户决定：是否在 `--resume-strategy=auto` 也加一次 startup
  evict（resume 加载后先 evict 一次再继续）？**建议先不做，等观察
  新瘦 snapshot 实测效果后再说**。
