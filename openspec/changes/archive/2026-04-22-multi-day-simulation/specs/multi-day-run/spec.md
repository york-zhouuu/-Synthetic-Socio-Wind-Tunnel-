## ADDED Requirements

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
- **THEN** orchestrator.run() SHALL 被调用 14 次；per_day_summaries 长度 = 14；
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
