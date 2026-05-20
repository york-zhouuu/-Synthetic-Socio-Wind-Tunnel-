# tick-level-resume Specification

## Purpose
TBD - created by archiving change tick-level-resume. Update Purpose after archive.
## Requirements
### Requirement: SimulationCheckpoint 数据结构

`SimulationCheckpoint` SHALL 是 Pydantic frozen 模型，位于
`synthetic_socio_wind_tunnel.run_resilience.state_snapshot`，含字段：

- `schema_version: str = "1"`
- `seed: int` / `tick_index: int` / `day_index: int` /
  `simulated_time: datetime`
- `ledger_state: dict[str, Any]`（完整 Ledger 可变 state：entity_states +
  item_states + door_states + door usage history）
- `agent_runtime_states: dict[str, dict[str, Any]]`（agent_id →
  current_location / current_plan / current_intent / emotional_state /
  current_tick_in_plan / movement_state）
- `memory_store_state: dict[str, Any]`（MemoryStore 全部 events /
  daily_summaries / reflections / per-agent identity / embeddings cache 元数据）
- `attention_service_state: dict[str, Any]`（per-agent pending / consumed
  notifications + decay state）
- `rng_state: dict[str, Any]`（所有 `random.Random` 实例的 `getstate()`，
  按使用方分组键，至少含 "orchestrator" / "collapse" / "policy_hack"）
- `pending_ops_meta: dict[str, Any]`（在飞 OperationPool ops 的元数据；
  仅诊断用，restore 时全部 abandon）
- `provider: str`（产生该 snapshot 的 LLM provider，与 partial JSON 同语义）
- `created_at: datetime`

#### Scenario: 默认构造与字段完整性
- **WHEN** 构造 `SimulationCheckpoint(seed=42, tick_index=100, day_index=0,
  simulated_time=datetime(2026,4,22,8,20), ledger_state={},
  agent_runtime_states={}, memory_store_state={}, attention_service_state={},
  rng_state={}, pending_ops_meta={}, provider="stub")`
- **THEN** 字段 SHALL 全部可读；`schema_version` SHALL == "1"；
  `model_dump()` SHALL 产 JSON-safe dict

#### Scenario: 字段不变量
- **WHEN** 构造后尝试 `snap.tick_index = 200`
- **THEN** SHALL raise（Pydantic frozen 行为）

### Requirement: 原子写盘与读取

`SimulationCheckpoint.write_atomic(path: Path) -> Path` SHALL 通过 tmp 文件
+ `os.replace` 模式原子写盘 JSON（与 `DayCheckpointWriter` 同模式）。SIGKILL
期间目标路径 SHALL 要么不存在、要么是合法 JSON——不允许写到一半的破损文件。

**多进程安全**：tmp 文件名 SHALL **不使用固定后缀**（既有
`path.with_suffix(path.suffix + ".tmp")` 已知会被并发 worker 互相覆盖
损坏 snapshot——见 2026-05-19 雪崩事故）。取而代之 SHALL 用以下方式
之一：

- `tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".",
  suffix=".tmp", delete=False)`（推荐——OS 保证唯一）
- 或显式 `f"{path}.{uuid.uuid4().hex}.tmp"`

任何启动 cleanup SHALL 只清扫**自己**这一轮产生的 tmp（按 PID 或 uuid
匹配），SHALL NOT 删除其它进程的 in-flight tmp（这正是当前固定后缀
方案踩雷的核心点）。

`SimulationCheckpoint.read(path: Path) -> SimulationCheckpoint` SHALL
反序列化 + 校验 `schema_version`；不兼容版本 SHALL raise
`IncompatibleCheckpointError`。

#### Scenario: 原子写无破损残留
- **WHEN** `write_atomic(path)` 期间进程被 SIGKILL
- **THEN** 目标路径 SHALL 要么不存在、要么是合法 SimulationCheckpoint
  JSON；不允许出现非法 JSON 残留

#### Scenario: 多进程并发 write_atomic 不互相损坏（新增）
- **WHEN** 进程 A 和进程 B 几乎同时调用 `write_atomic(p)` 到同一 path
  p（双胞胎 spawn 场景）
- **THEN** 最终 p 的内容 SHALL 是 A 或 B 之一的完整 JSON（取决于 os.replace
  顺序），**SHALL NOT** 是 A 与 B 部分内容混合或半截；A 和 B 的 tmp 文件
  名 SHALL 不冲突

#### Scenario: 不兼容 schema 抛
- **WHEN** `read(path)` 读到 `schema_version == "99"` 的文件
- **THEN** SHALL raise `IncompatibleCheckpointError`，含可读的版本号信息

#### Scenario: 序列化 round-trip 等价
- **WHEN** 构造 snap → `write_atomic(p)` → `read(p)` → 得到 snap2
- **THEN** `snap2.model_dump() == snap.model_dump()`

### Requirement: restore_into 把 state 灌回各子系统

`SimulationCheckpoint.restore_into(...)` SHALL 把 snapshot 完整还原到
所有 in-memory 子系统，签名 `restore_into(*, orchestrator, ledger, agents,
memory_service, attention_service) -> None`，按以下顺序还原：

1. `ledger.from_snapshot_state(snap.ledger_state)`
2. 对每个 agent in `agents.values()`：`agent.from_snapshot_state(
   snap.agent_runtime_states[agent.profile.agent_id])`（若 agent_id 不在
   snapshot 中，SHALL raise `ValueError` 并指出缺失 agent）
3. `memory_service.from_snapshot_state(snap.memory_store_state)`（若
   `memory_service` is None，跳过——dev mode）
4. `attention_service.from_snapshot_state(snap.attention_service_state)`
   （若 `attention_service` is None，跳过）
5. RNG 状态：按 `snap.rng_state` 的 key 调用对应模块的 RNG restore
   helper（详见 "RNG state 序列化与还原"）
6. `pending_ops_meta` 不还原——in-flight ops 全部 abandon

`restore_into` SHALL 不修改 Atlas（Atlas 只读、不变）。restore 失败
（任一子系统 raise）SHALL 让 ValueError / RuntimeError 直接传播给调用方，
不进入半还原状态。

#### Scenario: 完整 restore 与 in-memory state 等价
- **WHEN** 跑 N tick → 在该 tick 末 `to_snapshot_state` 提取 snap →
  构造一个空 ledger/agents/memory/attention → `snap.restore_into(...)`
- **THEN** 还原后各子系统的 `to_snapshot_state()` SHALL 与原 snap 字段
  byte-equal

#### Scenario: 缺失 agent 抛
- **WHEN** snapshot 含 agents `{a, b}`、当前 `agents` 字典只含 `{a}`
- **THEN** restore_into SHALL raise `ValueError`，含缺失 agent_id

#### Scenario: memory/attention 为 None 时跳过
- **WHEN** `restore_into(memory_service=None, attention_service=None, ...)`
- **THEN** SHALL 不抛；ledger / agents / rng SHALL 仍正常还原

### Requirement: 各子系统的 to/from snapshot 方法

以下 4 个 capability 的核心类 SHALL 提供
`to_snapshot_state() -> dict[str, Any]` 与
`from_snapshot_state(state: dict[str, Any]) -> None` 方法：

- `synthetic_socio_wind_tunnel.ledger.Ledger`
- `synthetic_socio_wind_tunnel.agent.runtime.AgentRuntime`
- `synthetic_socio_wind_tunnel.memory.service.MemoryService`（包装
  内部 `MemoryStore` 序列化）
- `synthetic_socio_wind_tunnel.attention.service.AttentionService`

每个 `to_snapshot_state()` 输出 SHALL 是 JSON-safe dict；
每个 `from_snapshot_state(state)` SHALL：

- 在调用前**清空** in-memory state（不是 merge）
- 校验 `state` 的 schema（关键字段缺失 SHALL raise `ValueError`）
- 不依赖未在 state 中显式记录的 derived data

每个子系统 SHALL 通过 round-trip 测试：
`s = obj.to_snapshot_state(); obj2.from_snapshot_state(s);
obj2.to_snapshot_state() == s`。

#### Scenario: Ledger to/from round-trip
- **WHEN** 已有非空 `ledger` 跑了若干 tick → `state = ledger.to_snapshot_state()`
  → 构造空 `ledger2 = Ledger(); ledger2.from_snapshot_state(state)`
- **THEN** `ledger2.to_snapshot_state() == state`；
  `ledger2.entity_states == ledger.entity_states`

#### Scenario: AgentRuntime to/from round-trip
- **WHEN** agent 跑过若干 plan step、有非默认 emotional_state →
  `state = agent.to_snapshot_state()` → 新 agent 同 profile +
  `from_snapshot_state(state)`
- **THEN** 新 agent 的 `current_location` / `current_plan` /
  `emotional_state` / `current_tick_in_plan` SHALL 与原一致

#### Scenario: MemoryService to/from round-trip
- **WHEN** memory 累积若干 events + 1 个 daily_summary → state →
  新 memory_service.from_snapshot_state(state)
- **THEN** 新实例 query 出的 events 数 / daily_summaries SHALL 与原一致

#### Scenario: AttentionService to/from round-trip
- **WHEN** attention 有若干 pending 与 consumed notifications → state →
  新 attention.from_snapshot_state(state)
- **THEN** 新实例 pending / consumed 数与每 agent decay state SHALL 与原一致

### Requirement: RNG state 序列化与还原

`SimulationCheckpoint.rng_state: dict[str, Any]` SHALL 至少包含以下 key：

- `"orchestrator"`：orchestrator 内部任何 `random.Random` 实例的 `getstate()`
- `"collapse"`：CollapseService 持有的 RNG state
- `"policy_hack"`：variant runner 的 RNG state（若存在）

子系统 SHALL 各自负责在 `to_snapshot_state` 里捕获自己持有的 RNG state；
state_snapshot 模块的 `restore_rng(rng_state)` SHALL 把 state 灌回对应
模块的 RNG 实例。

**Out-of-scope**：numpy.random / asyncio 等第三方 RNG 暂不接入；本 change
仅承诺 `random.Random` 系列 RNG 的 snapshot/restore。

#### Scenario: RNG round-trip 后下一次 random 输出一致
- **WHEN** orchestrator 跑过 N tick → 取 RNG state → 新 orchestrator
  从 RNG state 还原 → 双方分别再调 `_rng.random()`
- **THEN** 两个 `random()` 输出 SHALL byte-equal

#### Scenario: 缺失 RNG key 不抛但 warn
- **WHEN** snapshot 的 rng_state 缺失 "collapse" key、当前 CollapseService
  期待还原 RNG
- **THEN** SHALL log warning（不致命），CollapseService 用默认 RNG 起步

### Requirement: Per-tick WAL 写盘

`MultiDayRunner`（修改：见 multi-day-run delta）SHALL 在每 tick 末追加
一行到 `<output_dir>/seed_{seed}.wal.jsonl`，格式：

```json
{"tick_index": <int>, "day_index": <int>,
 "simulated_time": "<iso>",
 "wall_clock": "<iso utc>",
 "commits_succeeded": <int>, "commits_failed": <int>,
 "encounter_count": <int>,
 "snapshot_path": "<path or null>"}
```

WAL 文件 SHALL 是 append-only；旧行不修改。fsync 频率 SHALL 由
`RESILIENCE_WAL_FSYNC_EVERY_TICKS` 控制（默认 1=每 tick fsync）。

`wal_enabled=False` 时 SHALL 完全跳过 WAL 写盘（向后兼容 dev mode）。

#### Scenario: 14 day run 写出 4032 行 WAL
- **WHEN** `MultiDayRunner(output_dir=<dir>, wal_enabled=True).run_multi_day(
  start_date=..., num_days=14)`（288 tick/day）
- **THEN** `<dir>/seed_{seed}.wal.jsonl` SHALL 存在；行数 SHALL == 4032
  （最后一行 tick_index == 4031, day_index == 13）

#### Scenario: WAL 损坏不阻塞 run
- **WHEN** WAL 写盘 raise OSError（mock disk full）
- **THEN** runner SHALL log warning 但继续跑；当前 tick 不重写、不阻断

#### Scenario: wal_enabled=False 时不写
- **WHEN** `wal_enabled=False`、跑 3 day
- **THEN** 目录中 SHALL 不存在 `seed_{seed}.wal.jsonl`

### Requirement: Per-N-tick snapshot 写盘 + 滚动保留

`MultiDayRunner` SHALL 在每 tick 末检查
`tick_index_global % snapshot_every_ticks == 0`（`tick_index_global` 跨
day 累加，i.e., day*288 + tick）；条件为真且 `snapshot_every_ticks > 0`
SHALL 调 `SimulationCheckpoint.write_atomic(...)` 落到
`<output_dir>/seed_{seed}_tick{T_global}.snapshot.json`。

`snapshot_every_ticks=0` SHALL 完全禁用 snapshot（向后兼容
run-resilience partial-only 行为）。

写新 snapshot 后 SHALL 调 `_prune_snapshots(output_dir, seed, keep=K)`
保留最近 K 个 snapshot（默认 K=2，可由
`RESILIENCE_SNAPSHOT_KEEP_LAST` 覆盖）。

#### Scenario: N=24 时一天写 12 snapshot（首 tick + 12 个 N 整数倍）
- **WHEN** `snapshot_every_ticks=24`、跑 1 day（288 tick）
- **THEN** snapshot 文件数 SHALL ≤ K（默认 K=2，过去的被清理）；最后存留
  的 tick_index SHALL 是 288 的倍数（或最接近 288 的 24 整数倍）

#### Scenario: N=0 时不写 snapshot
- **WHEN** `snapshot_every_ticks=0`、跑 3 day
- **THEN** 目录中 SHALL 不存在 `seed_*_tick*.snapshot.json`；
  per-day partial（来自 run-resilience）SHALL 仍存在

#### Scenario: cleanup 删除超过 K 的旧 snapshot
- **WHEN** K=2、连续写出 tick 24/48/72/96 4 个 snapshot
- **THEN** 落盘后 SHALL 只剩 tick 72 + tick 96 两个文件

### Requirement: Graceful-stop 写 final snapshot

`MultiDayRunner` SHALL 在收到 SIGUSR1（或外部把
`_graceful_stop_requested=True`）时强写一次 final snapshot——在 break
主循环之前必落盘，**即使当前 tick 不是 `snapshot_every_ticks` 的整数倍**。

该 snapshot SHALL 与正常 snapshot 同 schema、同滚动保留策略下落盘。

#### Scenario: SIGUSR1 在 tick 100 触发 final snapshot
- **WHEN** `snapshot_every_ticks=24`、跑到 tick 100 时设
  `_graceful_stop_requested=True`
- **THEN** `<dir>/seed_{seed}_tick100.snapshot.json` SHALL 存在（即使
  100 % 24 != 0）；进程 SHALL 不再启动 tick 101

#### Scenario: graceful-stop 时 snapshot 体积大也要落
- **WHEN** memory_dump 在 1000 agent × 14 day 累积了 ~150 MB
- **THEN** final snapshot SHALL 完整落盘；可能延迟 1-5 秒但不能 abort

### Requirement: SnapshotPolicy 配置对象

`SnapshotPolicy`（Pydantic frozen）SHALL 暴露 snapshot 频率与保留参数：

- `every_ticks: int = 24`（0 = 禁用）
- `keep_last_k: int = 2`
- `wal_enabled: bool = True`
- `wal_fsync_every_ticks: int = 1`

`SnapshotPolicy.from_env()` SHALL 从 `RESILIENCE_SNAPSHOT_EVERY_TICKS` /
`RESILIENCE_SNAPSHOT_KEEP_LAST` / `RESILIENCE_WAL_ENABLED` /
`RESILIENCE_WAL_FSYNC_EVERY_TICKS` 读环境变量；不可解析值 SHALL log warning
并降级为默认。

#### Scenario: 默认值匹配 spec 默认
- **WHEN** 无 env、构造 `SnapshotPolicy.from_env()`
- **THEN** `every_ticks == 24`、`keep_last_k == 2`、`wal_enabled is True`、
  `wal_fsync_every_ticks == 1`

#### Scenario: env 覆盖
- **WHEN** `RESILIENCE_SNAPSHOT_EVERY_TICKS=48` + `from_env()`
- **THEN** `every_ticks == 48`

### Requirement: `tools/run_variant_suite.py` 新 `--resume-strategy` flag

`tools/run_variant_suite.py` SHALL 支持 `--resume-strategy` 取以下值：

| 值 | 行为 |
|---|---|
| `auto`（默认；等同既有 `--resume`）| 优先用最近 snapshot；找不到时降级到 run-resilience per-day partial；都找不到从 day 0 起 |
| `snapshot-only` | 只用 snapshot；无 snapshot 时 fail-fast 退出非 0 |
| `partial-only` | 忽略 snapshot，只用 per-day partial（run-resilience 旧路径） |
| `none` | 从 day 0 全新跑（覆盖既有 `--resume` 行为） |

`--resume`（既有 flag）= `--resume-strategy=auto`；二者不能同时指定不同
值（否则 fail-fast）。

publishable 模式（agents==1000 且 num_days==14）SHALL 默认 `auto`（即
强制启用 snapshot 检测）；`--resume-strategy=none` 在 publishable 模式下
SHALL 仍生效（用户显式覆盖）。

#### Scenario: auto 选 snapshot over partial
- **WHEN** variant 目录同时有 `seed_42_tick100.snapshot.json` +
  `seed_42_day0.partial.json`、调 `--resume-strategy=auto`
- **THEN** runner SHALL 构造 `restore_from = SimulationCheckpoint.read(
  ...tick100.snapshot.json)`；不从 partial 起

#### Scenario: snapshot-only 无 snapshot 时 fail-fast
- **WHEN** 仅有 partial、调 `--resume-strategy=snapshot-only`
- **THEN** suite SHALL 退出非 0；stderr 含 "no snapshot found"

#### Scenario: partial-only 走 run-resilience 旧路径
- **WHEN** 同时有 snapshot + partial、调 `--resume-strategy=partial-only`
- **THEN** runner SHALL 忽略 snapshot、按 partial 设 `resume_from = day+1`、
  从 fresh state 跑（已知的不一致 seam）

#### Scenario: none 覆盖既有 resume
- **WHEN** `--resume --resume-strategy=none`
- **THEN** SHALL fail-fast 退出非 0（冲突），stderr 含可 actionable 提示

### Requirement: `tools/audit_run_health.py` 新增 suspected_stuck 维度

`HealthAudit.audit(...)` SHALL 读取 `<run_dir>/<variant>/seed_*.wal.jsonl`
最后一行的 wall_clock timestamp。若距 `now`：

- ≥ 1 tick 期望耗时 × `stuck_warn_factor`（默认 10）且 < `stuck_deadlock_factor`
  （默认 30）：标 `rising_wal_silence`（warning 维度）
- ≥ 1 tick 期望耗时 × `stuck_deadlock_factor`：标 `suspected_stuck`（deadlock 维度）

"1 tick 期望耗时" 默认 = 5 sec（5-min tick 制下 1000 agent × DeepSeek 经验
值）；可由 `RESILIENCE_HEALTH_TICK_SECONDS_EXPECTED` 覆盖。warn / deadlock
factor 默认 10 / 30，可由 `RESILIENCE_HEALTH_STUCK_WARN_FACTOR` /
`RESILIENCE_HEALTH_STUCK_DEADLOCK_FACTOR` 覆盖。

`suspected_stuck` SHALL 与既有 `suspected_deadlock` 同等级，触发整体
overall_status = `suspected_deadlock`。

#### Scenario: WAL 10 min 无新行 → suspected_stuck
- **WHEN** WAL 最后一行 wall_clock 距 now 10 分钟、tick 期望耗时 5 sec、
  factor=30 → 阈值 150 sec、已超过
- **THEN** 该 worker 的 reasons SHALL 含 `suspected_stuck`；overall_status
  SHALL == `suspected_deadlock`

#### Scenario: WAL 5 sec 内新行 → 健康
- **WHEN** WAL 最后一行 wall_clock 距 now 3 sec
- **THEN** 该 worker reasons SHALL 不含 stuck 类标签

### Requirement: 公共 API re-export

`synthetic_socio_wind_tunnel/__init__.py` SHALL re-export 以下类型：

- `SimulationCheckpoint`
- `SnapshotPolicy`

使外部代码可 `from synthetic_socio_wind_tunnel import SimulationCheckpoint`。

`synthetic_socio_wind_tunnel/run_resilience/__init__.py` 同步 re-export。

#### Scenario: 顶层 import 成功
- **WHEN** `from synthetic_socio_wind_tunnel import SimulationCheckpoint,
  SnapshotPolicy`
- **THEN** SHALL 成功，无 ImportError

### Requirement: Fitness-audit 探针翻绿

`synthetic_socio_wind_tunnel.fitness.audits` SHALL 新增
`audit_tick_level_resume()`，含以下探针：

- `phase2-gaps.tick-level-resume.module` — `state_snapshot` 模块可 import
- `phase2-gaps.tick-level-resume.checkpoint-roundtrip` — 构造 dummy
  checkpoint、`write_atomic` + `read` 字段等价
- `phase2-gaps.tick-level-resume.subsys-ledger` — Ledger 有 `to_snapshot_state`
- `phase2-gaps.tick-level-resume.subsys-agent` — AgentRuntime 有
  `to_snapshot_state`
- `phase2-gaps.tick-level-resume.subsys-memory` — MemoryService 有
  `to_snapshot_state`
- `phase2-gaps.tick-level-resume.subsys-attention` — AttentionService 有
  `to_snapshot_state`

mitigation_change 全部 == `"tick-level-resume"`。

#### Scenario: 本 change 实施后 audit 全 PASS
- **WHEN** 本 change 所有 task 完成后跑 `make fitness-audit`
- **THEN** `phase2-gaps.tick-level-resume.*` 全部 status == `pass`

### Requirement: 性能约束

snapshot + WAL 启用 SHALL 满足以下性能与体积上限：

- `snapshot_every_ticks=24` + `wal_enabled=True` 相比
  `snapshot_every_ticks=0 + wal_enabled=False` 的总 simulation wall time
  SHALL 增加 ≤ 10%（100-agent × 3-day baseline）
- `snapshot_every_ticks=24` 时单 seed 在 disk 上的 snapshot 文件 total
  size SHALL ≤ 200 MB（默认 K=2 滚动保留）

#### Scenario: perf overhead ≤ 10%
- **WHEN** `tests/test_snapshot_perf.py` 跑 100 agent × 3 day × 2 配置
  （snapshot enabled vs disabled）
- **THEN** wall time delta SHALL ≤ 10%；超时 pytest fail

#### Scenario: disk usage ≤ 200 MB
- **WHEN** 跑 1000 agent × 14 day × `snapshot_every_ticks=24, K=2`
- **THEN** snapshot 目录 size SHALL ≤ 200 MB（即时；total churn 不计）

### Requirement: SimulationCheckpoint 必须包含 run_metrics_state

`SimulationCheckpoint` SHALL 在 schema_version 升级（"1" → "2"）后新增字段：

- `run_metrics_state: dict[str, Any]`（`TickMetricsRecorder` 的可序列化
  状态：per_day_summaries 累积、tick-level encounter / commit / position
  delta 累积、phase 切换历史）

`TickMetricsRecorder` SHALL 实现 `to_snapshot_state() -> dict[str, Any]`
返回 JSON-safe 累积状态（含所有已完成 day 的 `DayRunSummary`、累积
encounter count、phase 当前指针等），以及 `from_snapshot_state(state:
dict)` 把状态灌回（fresh recorder + restore）。两个函数 SHALL 严格
round-trip（`from_snapshot_state(to_snapshot_state())` 后 recorder 行为
等价于序列化前）。

`MultiDayRunner` 在 `restore_into` 之后 SHALL 调
`tick_metrics_recorder.from_snapshot_state(snap.run_metrics_state)`，
让 resume 后的 worker 在 final `MultiDayResult` 里能看到**resume 之前**
那些 day 的 metric 累积。

#### Scenario: snapshot 包含 run_metrics_state 字段
- **WHEN** 在 day 8 触发 snapshot write，TickMetricsRecorder 已累积
  day 0-7 的 DayRunSummary
- **THEN** 写出来的 SimulationCheckpoint JSON SHALL 含
  `run_metrics_state` key；reload 后 `snap.run_metrics_state["per_day_summaries"]`
  SHALL 含 8 个条目

#### Scenario: resume 后 round-trip metrics 等价
- **WHEN** worker A 跑 day 0-7 后写 snapshot 死掉，worker B 从该 snapshot
  resume 跑 day 8-13 自然完成
- **THEN** worker B 写出的 `seed_N.json` 的 `multi_day_result.per_day_summaries`
  SHALL 含 **14 个**条目（day 0-13 全部）；total_ticks / total_encounters
  SHALL 是 worker A 与 worker B 累积之和；SHALL NOT 仅反映 worker B 跑的
  6 天

#### Scenario: schema_version "1" 旧 snapshot 兼容读取
- **WHEN** `read(path)` 读到 schema_version "1" 的旧 snapshot（无
  `run_metrics_state` 字段）
- **THEN** SHALL 自动设 `run_metrics_state={}`（空 recorder），让
  resume 仍可启动；SHALL log warning "loaded legacy snapshot without
  run_metrics_state — earlier day metrics will be lost; consider
  re-running from scratch for clean publishable metrics"

### Requirement: snapshot 写盘前 cold-prune encounter events

`MultiDayRunner._write_snapshot` SHALL 在调用 `SimulationCheckpoint.write_atomic()` 之前先调用 `self._memory_service.evict_cold_encounter_events_across_agents(before_tick=cutoff)`，其中：

```
cutoff = max(0, day_index - grace) * ticks_per_day
```

`grace` 取自既有 env `MEMORY_EVENT_EVICT_GRACE_DAYS`（默认 2），与
day_end eviction 共享同一配置。

`cutoff <= 0` 时（早期 day，未到 grace window）SHALL 跳过 evict
直接写完整 snapshot。

env `SNAPSHOT_PRUNE_BEFORE_WRITE` 默认 `true`；设 `0` / `false` SHALL
完全禁用 pre-write evict，恢复旧行为（写完整 snapshot）。

evict 失败 SHALL 仅 log warning 不抛异常 — snapshot write 继续进行。

写盘后 SNAPSHOT_WRITE event SHALL 新增 `events_evicted_before_write`
字段反映本次 pre-write prune 释放的事件数（0 当 cutoff<=0 或 disabled）。

#### Scenario: snapshot 写盘前自动 prune

- **GIVEN** `MEMORY_EVENT_EVICT_GRACE_DAYS=2`，worker 当前 `day_index=10`，
  ticks_per_day=288，memory_store 含 day 0-10 累积的 encounter events
- **WHEN** `_write_snapshot(tick_index_global=2880, day_index=10, ...)`
  被调用（snapshot 触发点）
- **THEN** 调用前 SHALL 触发
  `evict_cold_encounter_events_across_agents(before_tick=8*288=2304)`；
  snapshot 文件落盘时 `memory_store_state` SHALL 不含 tick < 2304 的
  encounter events；day 8-10 的 encounter events 保留

#### Scenario: 早期 day 跳过 prune

- **GIVEN** `MEMORY_EVENT_EVICT_GRACE_DAYS=2`，worker 当前 `day_index=1`
- **WHEN** `_write_snapshot(tick_index_global=288, day_index=1, ...)` 被调用
- **THEN** `cutoff = max(0, 1-2) * 288 = 0`，SHALL 跳过 evict；
  snapshot 落盘时 `memory_store_state` 保留全部历史 encounter events

#### Scenario: env 关闭 prune 恢复旧行为

- **WHEN** `SNAPSHOT_PRUNE_BEFORE_WRITE=0` 设置，`day_index=10`
- **THEN** `_write_snapshot` SHALL NOT 调用 evict；snapshot 落盘时
  `memory_store_state` 含完整历史；events_evicted_before_write=0

#### Scenario: evict 失败不阻塞 snapshot write

- **GIVEN** `_memory_service.evict_cold_encounter_events_across_agents`
  抛 RuntimeError（mock）
- **WHEN** `_write_snapshot(day_index=10, ...)` 被调用
- **THEN** SHALL log warning 包含 "pre-write evict failed"；snapshot
  SHALL 仍然落盘（虽然没 prune，size 较大但写入完成）

#### Scenario: SNAPSHOT_WRITE event 包含 events_evicted_before_write

- **GIVEN** pre-write evict 释放 50000 events
- **WHEN** `_write_snapshot` 完成
- **THEN** instrumentation 写入的 SNAPSHOT_WRITE event SHALL 含字段
  `events_evicted_before_write: 50000`

### Requirement: find_latest_snapshot SHALL recognize tick_final

`synthetic_socio_wind_tunnel.run_resilience.state_snapshot.find_latest_snapshot` SHALL consider `seed_<N>_tick_final.snapshot.json` as a snapshot candidate (in addition to `seed_<N>_tick<int>.snapshot.json` files).

When both exist, the selection rule SHALL be:

1. If `tick_final.snapshot.json` exists AND its mtime is newer or equal to the highest-tick numeric snapshot's mtime → return `tick_final.snapshot.json` (graceful_stop's final state is more authoritative than the last periodic snapshot before it).
2. Otherwise, return the highest-tick numeric snapshot.
3. If only numeric snapshots exist, return the highest-tick one (current behavior preserved).
4. If only `tick_final.snapshot.json` exists, return it.
5. If no candidates exist, return None.

This invariant fixes the 2026-05-20 silent skip where `int("_final")` raised ValueError and the file was excluded from candidates, causing auto-resume to pick stale periodic snapshots over the authoritative graceful_stop final.

#### Scenario: tick_final preferred when newer

- **GIVEN** directory contains `seed_42_tick3444.snapshot.json` (mtime 2026-05-19 20:00) and `seed_42_tick_final.snapshot.json` (mtime 2026-05-20 02:54)
- **WHEN** `find_latest_snapshot(dir, seed=42)` called
- **THEN** SHALL return the `tick_final` path (mtime newer)

#### Scenario: numeric snapshot wins when tick_final is stale

- **GIVEN** `seed_42_tick_final.snapshot.json` (mtime 2026-05-18) and `seed_42_tick3984.snapshot.json` (mtime 2026-05-20)
- **WHEN** `find_latest_snapshot` called
- **THEN** SHALL return the `tick3984` snapshot (mtime newer; tick_final is stale from old graceful_stop)

#### Scenario: only numeric snapshots — pick highest tick

- **GIVEN** `seed_42_tick3000.snapshot.json` and `seed_42_tick3500.snapshot.json` only
- **WHEN** `find_latest_snapshot` called
- **THEN** SHALL return `tick3500` (highest numeric tick; current behavior preserved)

#### Scenario: only tick_final present

- **GIVEN** `seed_42_tick_final.snapshot.json` only
- **WHEN** `find_latest_snapshot` called
- **THEN** SHALL return `tick_final`

#### Scenario: no snapshots present

- **GIVEN** empty directory
- **WHEN** `find_latest_snapshot` called
- **THEN** SHALL return None (current behavior preserved)

### Requirement: DayRunSummary SHALL persist per-day across resume boundaries

`MultiDayRunner.run_multi_day` SHALL persist each day's `DayRunSummary` to disk at day_end as `seed_<N>_day<D>.summary.json` (atomic write via tempfile + rename). At run start, before entering the day loop, SHALL read all existing `seed_<N>_day<D>.summary.json` files in the output directory and hydrate the `per_day` list with them (sorted by day_index), so the final `MultiDayResult.per_day_summaries` contains every day's data, not only those days run in the current spawn.

This requirement closes the 2026-05-20 thesis-blocking bug where 14-day publishable runs that completed via multiple resumes had `seed_<N>.json` containing only the last resume's days (typically only post-phase, missing baseline + intervention phases).

`MultiDayResult.total_encounters` and `MultiDayResult.total_ticks` SHALL be computed as sums over the hydrated per_day list (already true; this requirement makes it sum over full 14 days instead of last-resume's days).

Day summary files SHALL NOT be cleaned up by `cleanup_partials` — they
serve as the canonical per-day record and remain on disk through cell
completion + audit.

#### Scenario: resume from mid-run loads prior day summaries

- **GIVEN** a previous worker spawn completed days 0, 1, 2 and wrote
  `seed_42_day0.summary.json`, `seed_42_day1.summary.json`,
  `seed_42_day2.summary.json` to disk
- **WHEN** a new worker spawn resumes from snapshot at day 3 and runs
  days 3 + 4 to completion
- **THEN** the final `seed_42.json`'s `multi_day_result.per_day_summaries`
  SHALL have 5 entries with `day_index` = [0, 1, 2, 3, 4] in order

#### Scenario: each day_end writes its summary atomically

- **WHEN** `MultiDayRunner.run_multi_day` completes day_index=N
- **THEN** before returning to next day's loop, SHALL write
  `seed_<seed>_day<N>.summary.json` to `_output_dir` containing the
  full DayRunSummary JSON (atomic — temp file then rename)

#### Scenario: summary files survive cleanup_partials

- **GIVEN** day_summary files exist alongside day_partial files
- **WHEN** `DayCheckpointWriter.cleanup_partials` runs after final
  `seed_N.json` write
- **THEN** SHALL only delete `seed_*_day*.partial.json` files; SHALL
  NOT delete `seed_*_day*.summary.json` files

#### Scenario: total_encounters reflects all 14 days post-resume

- **GIVEN** a 14-day publishable run completed via 3 resumes
  (day 0-4 in spawn 1, day 5-9 in spawn 2, day 10-13 in spawn 3)
- **WHEN** spawn 3 completes and writes seed_42.json
- **THEN** `multi_day_result.total_encounters` SHALL equal the sum of
  encounter_count across all 14 day summaries (not just spawn 3's 4 days)

### Requirement: snapshot 文件名 SHALL 含 spawn 唯一标识防覆写

Snapshot files MUST be named `seed_<N>_pid<PID>_tick<T>.snapshot.json`
where `<PID>` is the writing process's `os.getpid()` value. This
prevents a respawned worker from overwriting an earlier spawn's
snapshots at colliding internal tick numbers.

Backward compatibility: existing legacy-format files
`seed_<N>_tick<T>.snapshot.json` (no PID prefix) remain readable +
resumable. New writes use the PID-prefixed format.

#### Scenario: 两次 spawn 各自的 tick 12 snapshot 不互相覆写

- **GIVEN** worker A (PID 100) writes `seed_42_pid100_tick12.snapshot.json`
- **WHEN** worker A is killed; worker B (PID 200) starts as respawn and
  writes `seed_42_pid200_tick12.snapshot.json`
- **THEN** both files SHALL exist on disk simultaneously
- **AND** worker A's snapshot content SHALL remain readable (not corrupted
  by worker B's write)

#### Scenario: find_latest_snapshot 跨 spawn 选 mtime 最新

- **GIVEN** disk has `seed_42_pid100_tick120.snapshot.json` (mtime T1)
  AND `seed_42_pid200_tick12.snapshot.json` (mtime T2 > T1)
- **WHEN** `find_latest_snapshot(output_dir, seed=42)` is called
- **THEN** the result SHALL be `seed_42_pid200_tick12.snapshot.json`
  (latest mtime), NOT pid100's higher-numbered tick

#### Scenario: legacy 文件名仍 discoverable

- **GIVEN** disk has only `seed_42_tick120.snapshot.json` (legacy, no PID)
- **WHEN** `find_latest_snapshot(output_dir, seed=42)` is called
- **THEN** the legacy file SHALL be returned (back-compat)

### Requirement: snapshot 清理按 mtime 而非按 tick 编号

`prune_snapshots(output_dir, seed, keep=K)` MUST select the K
most-recently-written files (by mtime) to retain, and delete the rest.
Previous behavior (keep K highest tick numbers) is incompatible with
PID-prefixed naming because two spawns can have overlapping tick ranges.

#### Scenario: prune 用 mtime 排序，最新 K 个保留

- **GIVEN** 5 snapshots with mtimes T1 < T2 < T3 < T4 < T5
- **WHEN** `prune_snapshots(output_dir, seed=42, keep=2)` is called
- **THEN** files with mtimes T4 and T5 SHALL remain
- **AND** files with mtimes T1, T2, T3 SHALL be deleted

