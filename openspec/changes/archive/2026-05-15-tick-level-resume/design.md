## Context

`run-resilience`（2026-05-15 archive）解决了 "Gemini 连接池死锁导致 7h
全损" 这一类急性故障。但它的 checkpoint 粒度只到 **天**，且
`MultiDayRunner.resume_from` 实质上是"跳过前 N 天 + 从干净状态开始"——
**没有真正还原 in-memory state**。这导致两个剩余痛点：

1. **粒度问题**：14-day publishable 任何中断都丢一整天（最多 24h
   simulated time / ~5h wall time）。
2. **正确性问题**：resume 后的 state 与中断前不一致——day 5 起跑时
   Ledger / AgentRuntime / MemoryStore / AttentionService 都是 day-0 起始，
   不是 day-4-end。前后两段拼接有 seam，对依赖 cross-day carryover 的
   实验信号（memory accumulation、attention decay state、agent 位置长期
   演化）产生系统性偏差。

用户期望是 "任何中断都能从最后一次 tick / commit 接着跑，state 一致"。
对于 1000-agent × 14-day × DeepSeek 的 publishable run，这意味着：

- SIGKILL / 断电 / OOM / 物理 crash 时，最多损失 < 1 个 snapshot interval
  的进度（默认 24 tick = 2 hour simulated = ~10 min wall time）
- resume 时 in-memory state 与中断前 tick 边界**等价**——无 seam

`run-resilience` 已经把"是否丢"从 100% 降到 1 天；本 change 把这 1 天
进一步降到分钟级。两者层级化、不冲突。

## Goals / Non-Goals

**Goals**：

- 任何中断后，资料丢失 ≤ `snapshot_every_ticks` × tick_minutes（默认 24
  × 5min = 2h simulated / ~10min wall）
- resume 后 in-memory state（Ledger / AgentRuntime / MemoryStore /
  AttentionService）与中断前**严格等价**——不依赖 deterministic replay
- WAL 给运维"跑到哪一 tick 了"的实时可见性（独立于 snapshot）
- 磁盘占用可控：snapshot 滚动保留 K=2，不无限堆积
- 向后兼容：`snapshot_every_ticks=0` 退化到 run-resilience 旧行为；
  既有调用方零改动

**Non-Goals**：

- 不做 LLM response cache（让 replay 完全 deterministic）——LLM 路径下
  replay 必然 drift；本 change 用 **state 直接还原**避开 replay
- 不改 Atlas（只读、不变；不写入 snapshot 也能正确 resume）
- 不做 multi-machine snapshot 同步
- 不做 incremental / diff snapshot（首版全量）
- 不自动选 N——项目策略文档负责（默认 24 = 平衡选择）
- 不修改 `run-resilience` 既有 SHALL（per-day partial 仍 SHALL 写，作为
  低优先级 fallback）

## Decisions

### D1 · State 直接还原 vs Deterministic replay

**选**：state 直接还原（snapshot 写完整 in-memory state；restore_into
把 state 灌回）。

**Why over alternatives**：

- **alt A · Deterministic replay**：seed 已知 → 重跑 T 个 tick 重建 state。
  但 LLM 响应不可重现（即便 `temperature=0` 也有 ~0.1% drift），1000-agent
  × 几千 tick replay → drift 累积明显。**核心 violator**：本 change 的目标
  是 "state 与中断前一致"，replay 路径上做不到。
- **alt B · Hybrid（snapshot 之间 replay）**：snapshot 落地点严格还原；
  snapshot 与 crash 之间 replay。需要 LLM response cache 才能严格等价，
  落到 alt A 同样问题。
- **alt C · State 直接还原**（选）：每个子系统给 to_snapshot_state /
  from_snapshot_state 接口；snapshot 就是完整 state；restore_into 把
  state 灌回。**缺点**：snapshot 体积大（50-100 MB/次），需要滚动保留
  策略；但磁盘是廉价的，开发复杂度低，无 drift 风险。

**Trade-off**：snapshot 体积 → 用 N=24 tick / K=2 keep 控制总占用 ~100-200
MB / seed / 14 day（远小于 partial 总量）。

### D2 · Per-tick WAL + Per-N-tick snapshot 双层

**选**：每 tick 写一行 WAL（独立的 jsonl 文件）；每 N tick 写完整 snapshot。

**Why double layer**：

- WAL 仅 ~100 B / tick → 4032 行 × 100 B = ~400 KB / seed（可忽略）。给
  运维**实时可见**当前进度（`tail -f seed_42.wal.jsonl`），独立于 snapshot
  落盘频率
- snapshot 重，频率不能太高；WAL 轻，频率拉满
- WAL 还驱动 `audit_run_health` 的 `suspected_stuck` 判定（WAL mtime 老
  = worker 卡死）
- resume 时 WAL 告诉我们"中断前最后完成的 tick T_w"；snapshot 告诉我们
  "state 还原到 tick T_s"；若 T_w > T_s，**还是要 replay** T_s+1..T_w
  对吗？

**Replay vs 不 replay**：D1 选了 "不 replay"。那 WAL > snapshot 之间的
进度算什么？答：**那段进度其实已经丢了**——snapshot 是 state 真相来源；
WAL 之后没 snapshot 的 tick 数据无法还原。WAL 在这里只是"告诉运维我们
跑到哪了"的诊断信号，**不**参与状态还原。

所以 effective 损失 = `current_tick % snapshot_every_ticks` 个 tick，
最坏 = `snapshot_every_ticks - 1` = 23 tick = ~2h simulated。可接受。

### D3 · 默认 `snapshot_every_ticks = 24`

**选**：24 ticks（5-min tick 制下 = 2 simulated hours / ≈ 10 min wall
time 在 1000-agent × DeepSeek 配置下）。

**Why 24**：

- 太小（N=1 per-tick）→ snapshot 写盘开销吃 simulation 30%+
- 太大（N=288 per-day）→ 退化到 run-resilience，没新价值
- 24 的权衡：每天写 12 次 snapshot × 14 day × ~80 MB ≈ 13 GB 总写盘
  （但 keep K=2 → peak disk = 160 MB / seed），最坏丢 ~10 min wall
- 用户可由环境变量 `RESILIENCE_SNAPSHOT_EVERY_TICKS` 调，最低 1 / 最高 288

### D4 · Snapshot 滚动保留 K=2

**选**：保留最近 2 个 snapshot 文件，新 snapshot 落盘后立即清除更早的。

**Why K=2 而非 K=1**：

- K=1：一旦最近 snapshot 写盘到一半 crash（即使原子 rename 有保护），
  还有上一个能 fallback
- K=2 覆盖至少 ~1 整 day（默认 N=24 → 2 snapshot = 48 tick > 1 day 早期
  + 1 day 后期）
- K=3+ 收益边际递减

清理策略：`SimulationCheckpoint.write_atomic(...)` 写新 snapshot 后调
`_prune_snapshots(seed, keep=K)`——枚举 `seed_{S}_tick*.snapshot.json`
按 tick_index 排序、保留最大的 K 个、删除其余。

### D5 · RNG state 必须 snapshot

**选**：snapshot `rng_state` 字段记录所有 `random.Random` 实例的
`getstate()`，分组按使用方（orchestrator / policy_hack / collapse /
scripted_plan 等）。

**Why**：即使 state 直接还原避开 replay，restore 后**继续跑**的下一 tick
仍然依赖 RNG sequence。如果 RNG state 不还原，restore-then-continue 与
原本不中断会发散——这影响实验可重现性（项目核心要求 β=30 seed 严谨度）。

**实现风险**：要枚举所有 Random 实例。项目里 RNG 分散在多处（per-seed
全局 + per-day 局部 `random.Random(seed + day_index)`）。**策略**：

- orchestrator / collapse / memory / attention 等已实现的 service 接入
  `to_snapshot_state` 时各自负责自己持有的 Random
- 局部 RNG（如 scripted plan 每天 `random.Random(seed + day_index)`）
  不需 snapshot——day_index 已在 snapshot 中，restore 后照样重建
- 警告：第三方库（numpy.random / asyncio）暂不接入；本 change 不覆盖。
  实验信号路径目前都用 `random.Random`，covered

### D6 · Pending OperationPool ops：abandon-and-retry

**选**：crash / SIGUSR1 时在飞的 OperationPool ops（LLM call、reflection
等）全部 abandon；resume 后 agent 重新发起。

**Why over preserving**：

- ops 的内部 state machine（asyncio task + future + result-cache）很难
  完整序列化；强行 preserve 需要 ~1000 行支撑代码
- abandon 的代价：每 agent 重做 1-2 个 op = ~1-2 LLM call 重复。对
  1000 agent × 24 tick interval 最坏 = ~1000 个重复 call ≈ 几分钟 wall +
  几美分 API ——可接受
- snapshot 里记 `pending_ops_meta`（kind / agent / created_at）用于诊断
  + 可观察 abandon 比例

### D7 · 各子系统的 to/from snapshot 由子系统自己实现

**选**：Ledger / AgentRuntime / MemoryStore / AttentionService 各自
增加 `to_snapshot_state() -> dict` + `from_snapshot_state(state) -> None`
方法。state_snapshot 模块只做编排（调用 + 校验）。

**Why over centralized introspection**：

- 子系统**最知道**自己什么字段是 derived（可重建）vs primary（必须
  序列化）。集中式 introspection 会写一堆 special case 处理
- 接入点清晰可测：每个子系统有 round-trip test (`state = obj.
  to_snapshot_state(); new_obj = ...; new_obj.from_snapshot_state(state);
  assert new_obj.to_snapshot_state() == state`)
- 各 capability 演化时（如 MemoryService 加新字段），只需在自己模块
  内更新 to/from snapshot 方法、不动 state_snapshot 中心模块

**风险**：4 个子系统的 to/from 方法是新增"必须 maintain" 的契约面——
后续添加 mutable state 字段必须更新对应 snapshot 方法。**Mitigation**：

- to/from round-trip 测试 + monthly 跑一遍
- Pydantic `model_dump()` 兜底（MemoryStore / AttentionService 内部
  state 都是 Pydantic）
- 文档：CLAUDE.md 加一条 "新增 mutable 子系统字段时必须 update 对应
  `to_snapshot_state`"

### D8 · Schema versioning

**选**：`SimulationCheckpoint.schema_version: str = "1"`。read 时校验严格
相等（不兼容版本 raise `IncompatibleCheckpointError`）。

**Why over forward-compat**：

- snapshot 不是长期存储——publishable run 跑完 1 周内就归档为最终
  `seed_{S}.json`（不含 snapshot）。schema drift 跨周问题边界小
- 强校验避免 schema 变更后老 snapshot 静默 resume 到错误 state（数据
  污染）→ 明确报错 + 强制 restart

未来 schema 升级路径：写 migrator 从 "1" → "2"，or 直接 force restart
所有 in-flight run（简单）。

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| snapshot 体积超出预期（MemoryStore 增长不受限）| MemoryStore 已有 retention policy 限制 events ≤ N / agent；测一次 1000-agent × 14d 实际 dump 大小，若 > 200 MB 则触发"仅 dump 最近 7d memory"剪枝 |
| RNG state 漏 snapshot 某个 Random 实例 | 子系统 to_snapshot_state 强制要求列出所有持有的 Random；round-trip 测试 + 灰度测试在 D3 跑前用 100-agent × 3-day 验证 |
| Pending ops abandon 比例过高（resume 后大量重做）| `pending_ops_meta` 字段可观察；若实测 > 5% 触发优化（cache LLM response by prompt hash） |
| 写 snapshot 期间 SIGKILL 留下损坏文件 | atomic write（`.tmp` + `os.replace`）；K=2 keep 兜底 |
| Replay-induced drift（虽然 D1 选了不 replay，但 audit_run_health 可能误判） | WAL 只用于诊断 / suspected_stuck 判定，**不**参与 state 还原；明确文档 |
| 子系统 to/from snapshot 漏字段（silent corruption） | round-trip test：`from_state(to_state(obj)).to_state() == obj.to_state()`；新字段 PR 必须 update |
| snapshot 频率过高拖慢 simulation | N=24 默认 + perf test 验证 < 5% overhead；用户可调 N（trade-off explicit） |
| 多 worker 同时写盘 IO 抢占 | 每 worker 独立的 seed 目录；snapshot 写盘是 ~80 MB × 4 worker × 偶发 → 不构成瓶颈 |

## Migration Plan

### Phase 1（本 change 实施期间，~3-4 day）

1. 写 state_snapshot.py + 4 子系统 to/from 方法 + 单测
2. 改 MultiDayRunner：snapshot_every_ticks / wal_enabled / restore_from
3. 改 run_variant_suite.py：`--resume-strategy` flag + auto-detect
4. 改 audit_run_health.py：WAL mtime → suspected_stuck
5. 端到端 test：跑 3 day → 中途模拟 crash → restore → 跑完 → 与不中断
   等价
6. perf test：N=24 vs N=0 wall time 差 < 5%
7. openspec validate --strict

### Phase 2（archive 后）

1. 跑一次 100-agent × 3-day × DeepSeek 真 LLM 灰度，确认 snapshot 体积 +
   resume 行为
2. 在 D3 publishable 启动前用 `--resume-strategy=snapshot-only` 强制 path
3. 灰度后把 `RESILIENCE_SNAPSHOT_EVERY_TICKS=24` 写入 CLAUDE.md 不变量

### Rollback

- 环境变量 `RESILIENCE_SNAPSHOT_EVERY_TICKS=0` → 禁 snapshot，退化到
  run-resilience 旧行为
- 既有 `--resume` 不改语义；`--resume-strategy=partial-only` 显式走老路径

## Open Questions

1. **MemoryStore 体积上限**：1000-agent × 14d 三层 memory（events + daily
   summaries + reflections）实测多大？若超 200 MB 触发"仅 dump 最近 7d"
   剪枝。**P0**——需要在 implementation 期间测一次
2. **policy_hack / scripted_plan 是否有需要 snapshot 的 mutable state**：
   variant 状态机 / phase controller / replan counter 现在在 RunMetrics
   extensions 里，是 derived data 还是 primary state？需 audit。**P1**
3. **OperationPool 的 result_cache 是否需要 snapshot**：cache 用于跨
   tick 复用 LLM 响应（cost 优化）；丢了 → 重做 LLM call。若 cache 命中
   率高（> 30%），值得 snapshot。**P2**
4. **Atomic write 在某些 filesystem（NFS / tmpfs）的真实保证**：
   `os.replace` POSIX 承诺原子；NFS 上不一定。本 change 仅承诺 local
   filesystem。**P3**
5. **WAL 文件的 fsync 频率**：每 tick fsync 还是每 N tick？fsync 大约
   2-10 ms / 次，per-tick = 8-40 sec / day × 14d = 4-10 min 累计。
   折中：默认每 tick fsync；env `RESILIENCE_WAL_FSYNC_EVERY_TICKS` 可调。
   **P2**
