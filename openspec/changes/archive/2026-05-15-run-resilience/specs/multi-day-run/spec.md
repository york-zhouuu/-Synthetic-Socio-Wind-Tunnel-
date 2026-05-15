## ADDED Requirements

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
