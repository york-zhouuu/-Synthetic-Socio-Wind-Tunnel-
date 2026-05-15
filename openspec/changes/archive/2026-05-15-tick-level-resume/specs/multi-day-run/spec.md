## ADDED Requirements

### Requirement: MultiDayRunner SHALL 支持 snapshot/wal/restore_from 构造参数

`MultiDayRunner.__init__` SHALL 新增以下可选参数：

- `snapshot_every_ticks: int = 24` — per-N-tick snapshot 频率；0 时禁用
- `wal_enabled: bool = True` — per-tick WAL 写盘开关
- `restore_from: SimulationCheckpoint | None = None` — 调用方传入恢复点
- `snapshot_policy: SnapshotPolicy | None = None` — 完整 policy 注入；
  非 None 时优先于上面 3 个独立参数

`restore_from` 与 `resume_from: int` 并存：`restore_from` 非 None 时
**优先**使用（且忽略 `resume_from`）；`restore_from` 为 None 时按
`resume_from` 行为（run-resilience 既有路径）。

snapshot 文件写盘到 `output_dir`（既有参数，run-resilience 已要求；
本 change 复用同一目录、不引入新目录参数）。`output_dir` 为 None 时
SHALL 跳过 snapshot 写盘（向后兼容 dev mode）。

#### Scenario: 默认参数与既有调用方零回归
- **WHEN** 旧调用 `MultiDayRunner(orchestrator=o, seed=42)` 无任何新参数
- **THEN** runner SHALL 构造成功；`snapshot_every_ticks` 默认 24、
  `wal_enabled` True；既有 multi-day-run / run-resilience 测试 SHALL 0 回归

#### Scenario: snapshot_every_ticks=0 禁用快照
- **WHEN** `MultiDayRunner(snapshot_every_ticks=0, output_dir=<dir>)` 跑 3 day
- **THEN** `<dir>` 目录中 SHALL 不存在 `seed_*_tick*.snapshot.json`；
  既有 per-day partial（run-resilience）SHALL 仍正常落

#### Scenario: restore_from 优先 resume_from
- **WHEN** 同时传 `restore_from=<snap at day=5,tick=100>` + `resume_from=10`
- **THEN** runner SHALL 调 `snap.restore_into(...)` 然后从 day=5,tick=101
  起步；resume_from=10 SHALL 被忽略并 log warning


### Requirement: MultiDayRunner SHALL 在每 tick 末写 WAL + 视频率写 snapshot

`run_multi_day` 主循环 SHALL 在每 tick `on_tick_end` 之后、graceful-stop
检查之前执行：

1. 若 `wal_enabled=True` 且 `output_dir is not None`：append 一行到
   `<output_dir>/seed_{seed}.wal.jsonl`（schema 见 tick-level-resume spec）
2. 若 `snapshot_every_ticks > 0` 且 `tick_index_global %
   snapshot_every_ticks == 0`：构造 SimulationCheckpoint → `write_atomic`
   到 `<output_dir>/seed_{seed}_tick{T_global}.snapshot.json` → 调
   `_prune_snapshots(keep=K)` 删旧
3. 若 `_graceful_stop_requested`：在 break 之前强写一个 snapshot（不论
   N 整数倍），然后 break

`tick_index_global` 跨 day 累加：`day_index * ticks_per_day + tick_index`。

写盘失败（WAL 或 snapshot）SHALL log warning 但不中断 run——损失止于
下一次成功的 snapshot 写盘。

#### Scenario: 1 day × snapshot_every_ticks=24 → 滚动保留 ≤ K
- **WHEN** 跑 1 day（288 tick）、N=24、K=2、output_dir 提供
- **THEN** day 结束时 `<dir>` SHALL 含 ≤ K=2 个 snapshot 文件；最后留下
  的 tick_index_global SHALL 是 288 的最近 K 个 24 整数倍（i.e., 264 + 288，
  或仅 288 视 boundary 情况）

#### Scenario: WAL 行计数 == tick 数
- **WHEN** 跑 14 day × 288 tick、wal_enabled=True
- **THEN** `seed_{seed}.wal.jsonl` 行数 SHALL == 4032；最后一行 tick_index
  == 4031、day_index == 13

#### Scenario: graceful-stop 触发 final snapshot
- **WHEN** N=24，跑到 tick_index_global=100 时设
  `_graceful_stop_requested=True`
- **THEN** `<dir>/seed_{seed}_tick100.snapshot.json` SHALL 存在（即使 100
  不是 24 整数倍）；主循环 SHALL break；返回的 MultiDayResult
  per_day_summaries 长度 < num_days


### Requirement: MultiDayRunner SHALL 在构造时按 restore_from 还原 state

若 `restore_from is not None`，`run_multi_day` 主循环启动时 SHALL：

1. 调 `restore_from.restore_into(orchestrator=self._orchestrator,
   ledger=<orch ledger>, agents=<orch agents>, memory_service=
   self._memory_service, attention_service=<wherever it lives>)`
2. 主循环起步的 `(day_index, tick_index)` SHALL 是
   `(restore_from.day_index, restore_from.tick_index + 1)`
3. 若 `restore_from.day_index >= num_days` SHALL raise `ValueError`

`pending_ops_meta` 不还原；in-flight LLM ops 全部 abandon，相关 agent
在下一 tick 通过正常 op 触发路径自然重做。

#### Scenario: restore + 继续跑 14 天
- **WHEN** 构造 snap at (day=7, tick=100)、新 runner.run_multi_day(num_days=14)
- **THEN** restore_into SHALL 被调用；首个 day_index SHALL == 7、首个
  tick_index_global SHALL == 7*288+101 = 2117；之后跑完到 tick_index_global
  = 14*288-1 = 4031

#### Scenario: restore_from 超出 num_days 抛
- **WHEN** snap.day_index=20、runner.run_multi_day(num_days=14)
- **THEN** SHALL raise `ValueError` 含 "exceeds num_days"
