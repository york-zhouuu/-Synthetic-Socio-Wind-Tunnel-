# multi-day-run — 多日 simulation 驱动

## Purpose

Phase 2 的单日 `Orchestrator` 每次只跑 1440 / tick_minutes 个 tick。要支撑
14 天协议与 30-seed × 4-variant × 14-day 全套 publishable 实验，需在
orchestrator 之上加一层"按天推进 + 每日 memory carryover + plan 重生"
的驱动器，同时保留单日路径零破坏。

`MultiDayRunner` 作为这层驱动器的入口：对每个 day 调一次
`Orchestrator.run()`，期间由注入的 `MemoryService` 产出 DailySummary、
由 `Planner` 基于 CarryoverContext 生成次日 plan。单日路径仍可通过
直接调 `Orchestrator.run()` 使用。

模块：`synthetic_socio_wind_tunnel/orchestrator/multi_day.py`
引入自：`multi-day-simulation`
## Requirements
### Requirement: MultiDayRunner 主入口

`MultiDayRunner` SHALL 是驱动 N 日 simulation 的主类，位于
`synthetic_socio_wind_tunnel/orchestrator/multi_day.py`。构造参数 SHALL
包含：
- `orchestrator: Orchestrator`（per-day 引擎；每日复用）
- `memory_service: MemoryService | None`（若提供，自动 wire 到 per-day hook）
- `planner: Planner | None`（若提供，自动 wire 到 on_day_start 生成次日 plan）
- `seed: int`

`MultiDayRunner` MUST NOT 直接调用 Ledger / Atlas；只通过 Orchestrator 的
公共 API 驱动 per-day 运行。

#### Scenario: 构造后 orchestrator 保持单日可用
- **WHEN** `MultiDayRunner(orchestrator=o, ...)` 构造之后
- **THEN** 直接调用 `o.run()` SHALL 继续可用（单日路径零破坏）

#### Scenario: 仅 orchestrator 必需
- **WHEN** 仅传 `orchestrator` 与 `seed`，不传 memory/planner
- **THEN** `MultiDayRunner` SHALL 仍能构造；多日 run 会跑但**不做** memory
  carryover 或 plan 重生成（适用于不需要 memory 的对照实验）

### Requirement: run_multi_day 主方法

`MultiDayRunner` SHALL 提供 `run_multi_day(start_date: date, num_days: int,
on_day_start: Callable | None = None, on_day_end: Callable | None = None)
-> MultiDayResult` 方法，按天推进 `num_days` 天的 simulation：

1. 对每个 day_index in range(num_days)：
   1a. 触发 `on_day_start(current_date, day_index)` hook（若提供）
   1b. 调用 `orchestrator.run()` 跑完一天 288 tick
   1c. 触发 `on_day_end(current_date, day_index, daily_summary_batch)` hook
      （若提供 memory_service，先 `memory_service.run_daily_summary` 产出
       batch 再传给 hook）
   1d. current_date += 1 天
2. 返回 `MultiDayResult(per_day_summaries, total_ticks, total_encounters,
   seed, started_at, ended_at)`

#### Scenario: 14 天协议执行
- **WHEN** `run_multi_day(start_date=date(2026,4,22), num_days=14)` 在
  100 agent 上运行
- **THEN** orchestrator.run() SHALL 被调用 14 次；per_day_summaries 长度 = 14;
  wall time SHALL ≤ 30 秒（100 agent 规模）

#### Scenario: hook 顺序保证
- **WHEN** 某天 run 过程中
- **THEN** 执行顺序 SHALL 为：on_day_start → orchestrator.run()（内含
  on_tick_start/end × 288）→ memory_service.run_daily_summary（若有）→
  on_day_end

### Requirement: MultiDayResult 数据结构

`MultiDayResult` SHALL 为 frozen Pydantic 模型，至少包含：
- `per_day_summaries: tuple[DayRunSummary, ...]`（每日一个 `DayRunSummary`，
  内含 day_index / date / tick_count / commit_counts / encounter_count /
  daily_summary_batch）
- `total_ticks: int`
- `total_encounters: int`
- `seed: int`
- `started_at: datetime` / `ended_at: datetime`
- `metadata: dict[str, Any]`（预留给 metrics change 填内容）

MultiDayResult SHALL 提供 classmethod `combine(results: list[MultiDayResult])
-> MultiDayAggregate`，聚合 cross-seed 结果。

#### Scenario: MultiDayResult 可序列化
- **WHEN** run_multi_day 返回 MultiDayResult
- **THEN** `result.model_dump()` SHALL 产出 JSON-safe 结构

#### Scenario: cross-seed 聚合
- **WHEN** 跑 30 个 seed 得到 30 个 MultiDayResult 并 `MultiDayResult.combine([...])`
- **THEN** 返回 `MultiDayAggregate` SHALL 包含 per-day / per-variant 的
  median / IQR / 95% CI 统计字段

### Requirement: 两档运行模式

`MultiDayRunner` SHALL 支持两档预设模式，对应 `experimental-design` spec：
- **publishable mode**：默认；允许任意 num_days + 调用方外部循环 30 seed
- **dev mode**：`MultiDayRunner(mode="dev")` 构造时 num_days 最大 3、
  提示 "dev mode—results not publishable"

#### Scenario: dev mode 对 14 天请求降级
- **WHEN** `MultiDayRunner(mode="dev").run_multi_day(num_days=14)` 被调用
- **THEN** SHALL 抛 `ValueError("dev mode limited to 3 days; use mode=
  'publishable' for 14-day protocol")`

#### Scenario: publishable mode 无限制
- **WHEN** `MultiDayRunner(mode="publishable").run_multi_day(num_days=14)`
- **THEN** SHALL 正常运行 14 天

### Requirement: CLI 入口

`tools/run_multi_day_experiment.py` SHALL 提供命令行入口：

```
python tools/run_multi_day_experiment.py \
  --start-date 2026-04-22 --num-days 14 --agents 100 --seeds 30 \
  --variant hyperlocal_lure --mode publishable
```

输出 SHALL 至少包含：
- per-seed MultiDayResult（JSON dump 到 data/runs/<timestamp>/<seed>.json）
- cross-seed aggregate（JSON dump 到 data/runs/<timestamp>/aggregate.json）

**不在本 change 范围内**：variant 的具体 feed generator（那是 `policy-hack`
change）；本 change 仅提供 `--variant` 参数 stub 接受 variant 名字串。

#### Scenario: CLI 基本运行
- **WHEN** 执行 `python tools/run_multi_day_experiment.py --num-days 3 --agents 10 --seeds 2 --mode dev`
- **THEN** 命令 SHALL 产出 2 个 per-seed JSON 文件 + 1 个 aggregate JSON；
  退出码 0

### Requirement: 性能约束

多日 run 性能 SHALL 满足：
- 14 天 × 100 agent × 1 seed wall time ≤ 30 秒（baseline: smoke demo
  1 天 = 1.2 秒；14 × 1.2 ≈ 17 秒 + 2× 余量）
- 30 seed × 4 variant × 14 day 全 suite wall time ≤ 60 分钟（单机 CPU）

#### Scenario: 14 天 100 agent 性能测试
- **WHEN** `tests/test_multi_day.py::test_14_day_100_agent_performance` 运行
- **THEN** wall time SHALL < 30 秒；超时 pytest fail

### Requirement: 向后兼容

`Orchestrator.run()` 单日路径 SHALL 保持 Phase 2 `orchestrator` change
归档时的行为不变；所有现有 single-day 调用方（含 smoke demo / phase1
测试）SHALL 零改动继续工作。

#### Scenario: 单日 smoke demo 仍通过
- **WHEN** 运行 `python tools/smoke_experiment_demo.py --agents 100`
- **THEN** SHALL 依然输出 "8/8 PASS" 报告；无需添加任何 multi-day 参数

#### Scenario: 现有 orchestrator 集成测试通过
- **WHEN** 运行 `pytest tests/test_orchestrator.py`
- **THEN** 所有已存在测试 SHALL 100% 通过（零回归）

### Requirement: 审计翻绿

`synthetic_socio_wind_tunnel.orchestrator.multi_day` 模块 SHALL importable；
`fitness-audit` 将增加 `phase2-gaps.multi-day-run` 探针自动翻绿。

#### Scenario: multi-day-run 审计
- **WHEN** 运行 `make fitness-audit`
- **THEN** `phase2-gaps.multi-day-run` AuditResult 的 `status` SHALL 为 `pass`

### Requirement: MultiDayRunner SHALL 在 on_day_end 写 per-day checkpoint

`MultiDayRunner.run_multi_day` SHALL 在每个 day 的 `on_day_end` hook 触发
**之前**（hook 链顺序：内部 checkpoint 写盘 → 调用方注入的 on_day_end
callback）通过 `DayCheckpointWriter.write_partial(...)` 把当日完成的状态
落盘到 `<output_dir>/seed_{seed}_day{day_index}.partial.json`。

写盘失败（I/O error / 磁盘满 / 权限问题）SHALL log warning 但不中断当前 run；
该 day 的损失会在下一次 `run_multi_day` 调用的 `--resume` 路径上从前一个
成功 partial 恢复。

`MultiDayRunner.__init__` SHALL 新增可选参数：

- `output_dir: Path | None = None`：partial 文件写盘根目录；为 None 时
  禁用 checkpoint（向后兼容 dev mode）
- `checkpoint_writer: DayCheckpointWriter | None = None`：可注入自定义 writer
  做测试/mock；为 None 时构造默认 `DayCheckpointWriter()`

整 variant 的最终 `seed_{seed}.json` + `aggregate.json` 落地之后，调用方
（`run_variant_suite.py` / `run_multi_day_experiment.py`）SHALL 调用
`DayCheckpointWriter.cleanup_partials(output_dir, seed)` 清理该 seed 的所有
partial 文件。

#### Scenario: 14 天 run 写出 14 个 partial（按天累加）
- **WHEN** `MultiDayRunner(orchestrator=o, seed=42, output_dir=<dir>).
  run_multi_day(start_date=date(2026,4,22), num_days=14)` 完成
- **THEN** `<dir>/seed_42_day0.partial.json` 到 `seed_42_day13.partial.json`
  SHALL 各自存在；每个 partial 的 `day_index` 字段 SHALL 等于文件名中的数字

#### Scenario: 写盘失败时 run 继续
- **WHEN** 模拟 `DayCheckpointWriter.write_partial` 在 day 5 抛 `OSError`
- **THEN** `run_multi_day` SHALL 不抛、继续跑到 day 13；日志 SHALL 含 day 5
  写盘失败的 warning；day 6-13 的 partial SHALL 正常写

#### Scenario: 无 output_dir 时禁用 checkpoint
- **WHEN** `MultiDayRunner(output_dir=None)` 构造、跑 3 天
- **THEN** SHALL 不写任何 partial 文件；行为与 multi-day-simulation 归档时
  一致；现有 dev mode 测试 SHALL 0 回归

### Requirement: MultiDayRunner SHALL 支持 resume_from 起点构造

`MultiDayRunner.__init__` SHALL 新增可选参数 `resume_from: int = 0`：

- `resume_from > 0` 时，`run_multi_day(start_date, num_days)` SHALL 把
  effective num_days 算作 `num_days - resume_from`，且第一个 day 的
  `day_index` 从 `resume_from` 开始（而非 0）
- 调用方负责在调 `run_multi_day` 之前把 partial 内容（RunMetrics 部分快照
  / ledger 状态 / memory）通过 `Orchestrator` + `MemoryService` 的标准
  load 路径还原到当前 in-memory 状态
- `resume_from > num_days` SHALL raise `ValueError`（请求恢复到超过总
  天数的位置）

#### Scenario: resume_from=5 跑 14 天，从 day 5 开始
- **WHEN** 构造 `MultiDayRunner(seed=42, resume_from=5)`、调
  `run_multi_day(start_date=date(2026,4,22), num_days=14)`
- **THEN** orchestrator.run() SHALL 被调用 9 次（day 5 到 day 13）；
  per_day_summaries 长度 SHALL == 9；第一个 DayRunSummary 的 day_index
  SHALL == 5

#### Scenario: resume_from=0 行为不变（向后兼容）
- **WHEN** 构造 `MultiDayRunner(seed=42, resume_from=0)` 或不传该参数
- **THEN** run_multi_day 行为 SHALL 与 multi-day-simulation 归档时完全一致；
  per_day_summaries[0].day_index == 0

#### Scenario: resume_from > num_days 抛
- **WHEN** 构造 `MultiDayRunner(resume_from=20)` 后调 `run_multi_day(num_days=14)`
- **THEN** SHALL raise `ValueError`，含 "resume_from (20) exceeds num_days (14)"

### Requirement: MultiDayRunner SHALL 在主循环每 tick 后检查 graceful-stop flag

`MultiDayRunner` SHALL 暴露公共 attribute `_graceful_stop_requested: bool`
（初始 False），供外部 `HotfixSignalHandler` 写入。

主循环 SHALL 在每个 tick 结束（每天 288 tick 中的任意一次）后检查
`_graceful_stop_requested`；若为 True SHALL：

1. 不再启动下一个 tick
2. 通过 `DayCheckpointWriter.write_partial(...)` 写一个**反映当前完成 tick
   数**的 partial（`day_index = <已完成的最近完整 day>`；当前 in-progress
   day 的部分 tick 数据**不**写入 partial——避免 partial 内部一致性问题）
3. 返回截断的 `MultiDayResult`（per_day_summaries 长度 = 已完成的 day 数）

主循环 SHALL 不主动调 `sys.exit`——退出由调用方（如 `HotfixSignalHandler.
install` 注册的额外 callback）决定。

#### Scenario: 中途 graceful-stop 写 partial 后返回
- **WHEN** 14 天 run 跑到 day 5 的 tick 100；外部把
  `runner._graceful_stop_requested = True`
- **THEN** runner SHALL 不启动 tick 101；写
  `seed_{seed}_day4.partial.json`（day 5 未完成，partial 只到 day 4）；
  返回的 MultiDayResult.per_day_summaries 长度 SHALL == 5（day 0 到 day 4）

#### Scenario: 未被打断的 run 不受 flag 影响
- **WHEN** 14 天 run 全程 `_graceful_stop_requested` 保持 False
- **THEN** 完整 14 天跑完；行为与 multi-day-simulation 归档时一致

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

