## Context

2026-05-19 真实 publishable single worker RSS 16↔37GB（py-spy + vmmap +
DayRunSummary instrumentation 三条独立证据交叉验证）。前一个 change
`accelerate-memory-snapshot-serialization` 假设可以 5× speedup CPU
serialize，**benchmark 实测 1.0× — 证伪**。Python-level dispatch 优化
天花板就在这里。

要砍 RSS 必须**减工作量**（不是加速做工作）。本 change 走 3 条数据驱动
路径：
1. 减 event 总量 (cold prune)
2. 把 pymalloc 碎片还回 OS (malloc_zone_pressure_relief)
3. 撞顶时自杀重启 (已有机制，default-enable)

## Goals / Non-Goals

**Goals:**
- 单 worker publishable 跑 14 day RSS **永不超 10 GB**（撞顶自杀+重启）
- empirical 验证：dev smoke with eviction RSS < without baseline
- 测试体系：6 层 test-first，**不再预设具体 speedup 数字**
- 既有 ~1700 测试全绿，新增 ≥ 15 测试

**Non-Goals:**
- 多核 partition — 独立 follow-up change，2-3 天架构改动
- 改 MemoryEvent 数据模型 — frozen dataclass 保留
- 重写 _event_to_json — 上一个 change 已证伪
- incremental snapshot — follow-up
- evict 非 encounter kind — 数量少 + 语义关键
- DialogueService eviction tuning — 已 landed
- Linux malloc_trim 完整支持 — macOS 优先，Linux 留 TODO

## Decisions

### 决策 1：encounter 完全删除而非 summary 化

**A**（采纳）: evict 是真删除，不保 summary。
**B**: 仿 DialogueService 留 DialogueSummary，保留 event_id + tick + actors。

选 A 因为：
- encounter 数量太大（6.88M），summary 仍占 GB 级
- 没有下游 retrieve query 跨远期 encounter 的真实用例
  （thesis 不依赖 day-10 之前的 raw encounter）
- DialogueService summary 有用是因为 dialogue 数量小（数万）；
  encounter 没这个 ROI

风险：将来若 thesis 加跨远期 encounter retrieve（unlikely），需重做。

### 决策 2：grace_days = 2 (与 DialogueService 一致)

DialogueService 也是 2 day grace。保持一致便于运维理解。env
`MEMORY_EVENT_EVICT_GRACE_DAYS` 可 override（=0 立刻 evict / =N 保留更长）。

不设 grace_ticks=0 默认——day_end hook 时刚结束的 events 还可能被
当 tick 的 retrieve 用，留 buffer。

### 决策 3：malloc_zone_pressure_relief 调用频率

**A**（采纳）: 跟 gc.collect 同频率（既有
`GC_EVERY_N_TICKS=200` env，~hourly）。
**B**: 仅在 day_end 触发。
**C**: 仅在 RSS 接近 cap 时 emergency 触发。

选 A 因为：
- 与既有 hook 同位置，代码简单
- macOS pressure_relief 调用成本不高（~10ms），200 tick 一次开销可忽略
- B 间隔太长（24 day_end / 14 day），不够及时
- C 复杂度高，premature optimization

### 决策 4：RSS_RESTART_MB=10000 default for publishable mode only

**A**（采纳）: 仅 publishable mode 自动设。dev mode 仍 default=0（不
启用，方便开发测试不被打断）。
**B**: 全局 default。
**C**: 加新 mode 参数 `--rss-cap-mb`。

选 A 因为：
- dev mode 用户在跑测试 / 小 smoke / 临时实验，撞 cap 会困扰
- publishable mode 是 production-like 长跑，必须有 cap
- env override 仍允许：`RSS_RESTART_MB=20000 python tools/run_variant_suite.py`
- C 增加 CLI 复杂度，env 已经够用

### 决策 5：性能测试不设 speedup floor

之前 `accelerate-memory-snapshot-serialization` 设 5× floor 后 benchmark
1×证伪 → revert。**学到了**：

- 本 change spec 不写"5× speedup"或类似数字
- Layer 4 测试断言 "with-eviction RSS **<** without-eviction RSS"
  （任何 amount）+ "wall-clock 不增 > 20%"
- 写 absolute 数字到 docs 作为参考（"day10 时 6.88M → ~700k events
  预期"）但不进 spec assertion

不预设减少 review 时的过度承诺，empirical 兜底。

## Risks / Trade-offs

- **[Risk] thesis 真要 day-10 之前 encounter retrieve** → 现 codebase
  grep 显示 `MemoryService.retrieve()` 都只 query 近 7 day window，
  不依赖远期。**Mitigation**: 加 retrieve test，覆盖 query day-3 之前
  事件——若 thesis 真用，本 change 提议 abort + 改 ❶ 为 summary 化
- **[Risk] malloc_zone_pressure_relief 在某些 macOS 版本 SEGV** →
  历史 bug 报告罕见但存在。Mitigation: try/except + 失败时 1 次警告
  后**禁用本进程后续调用**（state 标志）
- **[Risk] RSS_RESTART_MB=10000 撞顶过频** → 若 evict 不够狠（比如
  thesis 验证后扩 grace_days），可能反复 graceful_stop。Mitigation:
  既有 watchdog 巡检防雪崩 (monitor-as-control-plane invariant)
- **[Trade-off] evicted encounter 无法 retrieve** → 上面 mitigation
  覆盖；语义降级换实用 RSS cap

## Migration Plan

1. Layer 1-3 unit tests 写完（red）
2. 实现 MemoryStore.evict_cold_encounter_events
3. 实现 MemoryService.evict_cold_encounter_events_across_agents
4. MultiDayRunner.run_multi_day 加 day_end eviction hook
5. _init_memory_management_hooks 加 malloc_zone_pressure_relief
6. tools/run_variant_suite.py 设 publishable default RSS_RESTART_MB
7. Layer 4-5 集成测试
8. Layer 6 fault injection 测试
9. dev smoke RSS 实测验证
10. archive

**Rollback**: env `MEMORY_EVENT_EVICT_GRACE_DAYS=999` 实质禁 evict；
`RSS_RESTART_MB=0` 禁 cap；malloc_zone_pressure_relief 失败已 fallback。
都可一行 env 关。

## Open Questions

- grace_days 真的 2 够吗？跑一次 publishable 看实际 retrieve pattern
  调（DayRunSummary 已 instrumented `memory_store_event_count`）
- malloc_zone_pressure_relief 在 Linux 真正等价是 `malloc_trim(0)`？
  Linux 上 jemalloc / tcmalloc 也常见，那些不响应 `malloc_trim`。
  跨平台留 TODO，本 change macOS 优先
- 是否需要 evict 触发后 emit 一个 metric (evicted_count_today) 写进
  DayRunSummary？— yes，加 task
