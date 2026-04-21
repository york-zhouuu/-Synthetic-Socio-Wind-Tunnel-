## MODIFIED Requirements

### Requirement: TickResult / SimulationSummary 数据结构

Orchestrator SHALL 定义两个不可变数据结构用于 hook 契约：

- `TickResult(tick_index, simulated_time, simulated_date, day_index,
  commits: tuple[CommitRecord, ...],
  encounter_candidates: tuple[EncounterCandidate, ...])`
  其中 `CommitRecord(agent_id, intent, result: SimulationResult,
  simulated_date, day_index)`
- `SimulationSummary(total_ticks, total_encounters, total_commits_succeeded,
  total_commits_failed, seed, started_at, ended_at, day_index, simulated_date)`

两者 SHALL 为 frozen Pydantic 模型或 frozen dataclass，字段可哈希，
不引用 Ledger / Atlas（避免订阅者持住大对象）。

`simulated_date` SHALL 派生自 `simulated_time.date()`；`day_index` 默认 0，
代表当前 run 的第一天（0-based）；单日调用方无需传入，由 orchestrator
填充。

#### Scenario: TickResult 可序列化
- **WHEN** 某 on_tick_end callback 收到 TickResult
- **THEN** `TickResult.model_dump()` / 类似导出 SHALL 产出 JSON-safe 结构；
  订阅者可安全保存或跨进程传输

#### Scenario: 单日调用 day_index 默认为 0
- **WHEN** 调用 `Orchestrator.run()` 未显式指定 `day_index`
- **THEN** 所有产出的 TickResult.day_index SHALL 为 0；simulated_date SHALL
  为 `Ledger.current_time.date()`

#### Scenario: 多日调用 day_index 递增
- **WHEN** `MultiDayRunner.run_multi_day` 调用 orchestrator.run() 于 day 5
- **THEN** orchestrator.run() 产出的所有 TickResult.day_index SHALL 为 5；
  simulated_date SHALL 为 start_date + 5 天


### Requirement: 生命周期 Hook

Orchestrator SHALL 暴露四个 per-day hook 注册点：

- `register_on_simulation_start(cb)` — 传 `SimulationContext` 参数
- `register_on_tick_start(cb)` — 传 `TickContext` 参数
- `register_on_tick_end(cb)` — 传 `TickResult` 参数
- `register_on_simulation_end(cb)` — 传 `SimulationSummary` 参数

- Hook 同步调用；多个 callback 按注册顺序触发。
- Hook MUST NOT 直接修改 Ledger；订阅者若需状态由自己 service 管理。
- 任何 hook 抛异常 SHALL 终止当前 per-day run，异常向上传播到调用方
  （单日 `Orchestrator.run()` 或多日 `MultiDayRunner.run_multi_day()`）。

**多日相关的 hook 不属于 orchestrator**——`on_day_start` / `on_day_end` 是
`MultiDayRunner` 的 hook 接口（见 `multi-day-run` spec）；orchestrator 不
引入它们以保持单日/多日分层。

#### Scenario: 注册多个 on_tick_end
- **WHEN** 先后注册 `cb_a` 和 `cb_b` 到 `on_tick_end`
- **THEN** 每 tick 末 SHALL 先调 `cb_a(TickResult)` 再调 `cb_b(TickResult)`

#### Scenario: Hook 异常中止 simulation
- **WHEN** `on_tick_end` 的 callback 抛 `RuntimeError`
- **THEN** `Orchestrator.run()` SHALL 向上传播该 `RuntimeError`，
  不吞不遮；`MultiDayRunner.run_multi_day` 调用时同样向上传播，
  不 swallow 当日错误以跳到次日

#### Scenario: on_simulation_start 每天触发
- **WHEN** `MultiDayRunner.run_multi_day(num_days=3)` 被调用
- **THEN** `on_simulation_start` hook SHALL 每天被触发一次（共 3 次），
  每次传入对应日的 `SimulationContext`（含该日 `simulated_date`）


### Requirement: Tick 循环

`Orchestrator` SHALL 提供 `run(*, day_index: int = 0,
simulated_date: date | None = None) -> SimulationSummary`，以每 tick
`tick_minutes` 分钟的步长推进 Ledger.current_time，共 `1440 // tick_minutes`
tick（tick_minutes=5 默认时 288 tick/天）。

- 若 `simulated_date` 传入，SHALL 把它填入 TickContext / TickResult；
  未传时从 `Ledger.current_time.date()` 派生。
- `day_index` 默认 0（单日调用）；多日调用方（`MultiDayRunner`）SHALL
  按 0, 1, 2, ... 传入。

每 tick 内部 SHALL 依以下顺序执行：

1. 触发 `on_tick_start` hook 订阅者
2. 对每个 agent（按 `agent_id` 字典序）：
   2a. 读 `Ledger.get_entity(agent_id).position` 并与
       `AgentRuntime.build_observer_context()` 返回的 dict 合并，
       构造完整 `ObserverContext`
   2b. 构造 `TickContext(tick_index, simulated_time, simulated_date,
       day_index, observer_context)`
   2c. 调用 `agent.step(tick_ctx) -> Intent`，收入 intent_pool
3. 调 `IntentResolver.resolve(intent_pool)` 产出 `list[CommitDecision]`
   （含赢家与失败者）
4. 对每个 CommitDecision（按赢家 agent_id 字典序）：
   4a. 按 Intent 类型分派到 SimulationService 方法（见 "Intent →
       Simulation 方法映射" Requirement）
   4b. 裁决失败的 Intent 直接产出 `SimulationResult.fail(
       error_code=PRECONDITION_FAILED)`，不调 simulation
   4c. 若 MoveIntent 成功，用 `NavigationService.find_route` 展开
       原位置到目标位置的 `NavigationResult.steps`，逐 step 调
       `move_entity`；同步记入本 tick 的 `TickMovementTrace`
5. 扫描 `TickMovementTrace`，按 location 桶求 agent 对的位置序列交集，
   产出 `list[EncounterCandidate]`
6. 推进 `Ledger.current_time` += `tick_minutes`
7. 触发 `on_tick_end(TickResult)` hook 订阅者；TickResult 含 commits /
   encounter_candidates / tick_index / simulated_date / day_index

#### Scenario: 全天 288 tick
- **WHEN** `tick_minutes=5` 且 agents 都有合法 DailyPlan
- **THEN** `Orchestrator.run()` SHALL 执行 288 次 tick；
  `Ledger.current_time` SHALL 前推 24 小时

#### Scenario: tick 内动作按字典序提交
- **WHEN** agent `alpha` 和 `beta` 同 tick 各自 `MoveIntent`
- **THEN** `alpha` 的 Simulation 调用 SHALL 先发生；但两者都成功，
  Ledger 最终状态与调用顺序无关（Move 非互斥）

#### Scenario: 多日调用 day_index / date 被填充
- **WHEN** `Orchestrator.run(day_index=3, simulated_date=date(2026,4,25))`
- **THEN** 该调用产出的 TickResult.day_index SHALL = 3；
  TickResult.simulated_date SHALL = date(2026,4,25)
