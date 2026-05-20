# orchestrator — tick 循环驱动

## Purpose

Phase 2 中把 Phase 1 / 1.5 的库函数串成可跑的 tick 循环。单天 sequential
执行；每 tick 为每个 agent 走"感知 → Intent → 裁决 → 提交"流程。Move 逐
NavigationResult.steps 写 Ledger，tick 末产出路径相遇候选对。Hook 系统为
后续 Phase 2 能力（memory / social-graph / policy-hack / conversation /
metrics）提供固定订阅点。

模块：`synthetic_socio_wind_tunnel/orchestrator/`
引入自：`orchestrator`（归档于 2026-04-20）
## Requirements
### Requirement: Orchestrator 主入口与构造

系统 SHALL 提供 `synthetic_socio_wind_tunnel.orchestrator.Orchestrator`
作为单天 tick 循环的驱动。构造签名至少包含：

```
Orchestrator(
  atlas: Atlas,
  ledger: Ledger,
  agents: list[AgentRuntime],
  *,
  simulation: SimulationService | None = None,
  pipeline: PerceptionPipeline | None = None,
  navigation: NavigationService | None = None,
  attention_service: AttentionService | None = None,
  tick_minutes: int = 5,
  seed: int = 0,
  num_days: int = 1,
)
```

- 缺省的 `simulation` / `pipeline` / `navigation` SHALL 由 orchestrator 按
  传入的 atlas / ledger / attention_service 构造合理默认。
- `num_days > 1` SHALL 在构造时抛 `NotImplementedError`，提示需
  `memory` capability。
- `tick_minutes` SHALL 满足：为正整数且整除 1440（24×60）；否则抛
  `ValueError`。推导：`ticks_per_day = 1440 // tick_minutes`。

#### Scenario: 最小构造
- **WHEN** 传入 atlas / ledger / 1 个 AgentRuntime，其它参数默认
- **THEN** Orchestrator SHALL 成功构造；`simulation` / `pipeline` /
  `navigation` SHALL 被 orchestrator 用默认值填充

#### Scenario: 多天请求被拒
- **WHEN** 构造 `Orchestrator(..., num_days=2)`
- **THEN** SHALL 抛 `NotImplementedError`，错误消息包含
  `memory` capability 字样

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

### Requirement: Intent 冲突裁决

`IntentResolver` SHALL 对"独占类"Intent 做字典序裁决：

- 独占 Intent 类型：`PickupIntent` / `OpenDoorIntent` / `UnlockIntent` /
  `LockIntent`。裁决维度：同 tick、同 `target_id`（item_id 或 door_id）。
- 非独占 Intent 类型（`MoveIntent` / `WaitIntent` / `ExamineIntent`）
  SHALL 不进裁决器，直接进入提交队列。
- 当多个 agent 同 tick 对同一 target 提出独占 Intent：按 `agent_id`
  字典序取第一名为赢家；其余 agent 产出 `SimulationResult.fail(
  error_code=PRECONDITION_FAILED, data={"resolver": "lost_to",
  "winner": "<agent_id>"})`。
- 赢家正常 commit；失败者不修改 Ledger。

#### Scenario: 两人抢同一把伞
- **WHEN** agent `alpha` 和 `beta` 同 tick 都 `PickupIntent(item_id="umbrella_01")`
- **THEN** 解析后 `alpha` 赢；Ledger 中 `umbrella_01.held_by="alpha"`；
  `beta` 的 Intent 结果 SHALL 为 `SimulationResult(success=False,
  error_code=PRECONDITION_FAILED)`

#### Scenario: 非独占 Intent 不进裁决
- **WHEN** 3 个 agent 同 tick 都 `MoveIntent(to_location="cafe_a")`
- **THEN** `IntentResolver` SHALL 直接让全部 3 个走提交；
  Ledger 中 `cafe_a` SHALL 出现 3 个 entity

### Requirement: Intent → Simulation 方法映射

Orchestrator 在 commit 阶段 SHALL 按以下固定映射把 Intent 分派到
SimulationService：

| Intent           | SimulationService 方法                      |
|------------------|---------------------------------------------|
| `MoveIntent`     | `move_entity(agent_id, step_location)` × n  |
| `WaitIntent`     | 不调 simulation，直接产 `SimulationResult.ok()` |
| `ExamineIntent`  | `mark_item_examined(target_id, agent_id)`   |
| `PickupIntent`   | `give_item_to_entity(item_id, agent_id)`    |
| `OpenDoorIntent` | `open_door(door_id, agent_id)`              |
| `UnlockIntent`   | `unlock_door(door_id, agent_id, key_id)`    |
| `LockIntent`     | `lock_door(door_id, agent_id, key_id)`      |

- 所有 `SimulationResult`（包括 WaitIntent 的 ok 默认值）SHALL 被原样填入
  `CommitRecord.result`。
- WaitIntent MUST NOT 产生 WorldEvent（"等待"不是可感知事件）。

#### Scenario: WaitIntent 不生产 simulation 调用
- **WHEN** agent 返回 `WaitIntent(reason="at_destination")`
- **THEN** orchestrator SHALL 不调用任何 SimulationService 方法；
  CommitRecord.result.success SHALL 为 `True`；Ledger 事件日志 SHALL
  不新增 WorldEvent

#### Scenario: PickupIntent 调 give_item_to_entity
- **WHEN** agent `alpha` 的 `PickupIntent(item_id="key_001")` 裁决赢得提交
- **THEN** orchestrator SHALL 调 `simulation.give_item_to_entity(
  "key_001", "alpha")`；CommitRecord.result 来自该调用的返回值

### Requirement: MoveIntent 逐 step 写 Ledger

Orchestrator SHALL 把每个 commit 成功的 `MoveIntent` 展开为一系列对
`SimulationService.move_entity` 的调用——每个 `NavigationResult.steps`
的 step 触发一次 `move_entity`——让 Ledger 中该 entity 的 `location_id`
依次经过所有中间位置（而非一次性跳到终点）。

- 所有 sub-step 的调用 SHALL 在 tick 内部发生；`Ledger.current_time`
  在 sub-step 之间不推进，仅在 tick 末统一推进 `tick_minutes`。
- 每次 sub-step 的 `move_entity` 产生的 WorldEvent（ENTITY_LEFT_ROOM /
  SOUND_FOOTSTEPS / ENTITY_ENTERED_ROOM）SHALL 使用同一 tick 的起始
  `current_time` 作为 timestamp。
- 若某 sub-step 返回 `SimulationResult.success=False`（中间节点不可达），
  orchestrator SHALL 停止剩余 sub-step；agent 留在最后一个成功 sub-step
  的 location；该 MoveIntent 的整体 CommitRecord.result 取最后一次
  失败的 SimulationResult。
- 同步记录 `TickMovementTrace.locations: tuple[str, ...]` 为本 tick 内
  agent 实际经过的 location id 序列（orchestrator 内部状态，tick 末
  清空；不写入 Ledger）。

#### Scenario: 3-step 路径写 3 次 move_entity
- **WHEN** agent `alpha` 的 MoveIntent 解析路径为
  `[street_1, street_2, cafe_a]`（3 step）
- **THEN** orchestrator SHALL 调 `simulation.move_entity(alpha, ...)` 3 次；
  Ledger 中该 entity 的 location_id 依次是 `street_1` → `street_2` → `cafe_a`；
  事件日志 SHALL 至少含 3 条 ENTITY_ENTERED_ROOM 记录（对应 3 个目标）

#### Scenario: sub-step 中途失败
- **WHEN** 3-step 路径中 step 2 返回 `success=False`（例如运行期中间节点
  被标不可达）
- **THEN** step 3 SHALL 不执行；agent 的 final location_id 是 step 1 的
  目标；CommitRecord.result 的 `success=False` 且 `error_code` 与 step 2
  一致

### Requirement: 路径相遇检测（基于 TickMovementTrace + Ledger Snapshot）

Orchestrator SHALL 在 tick 末扫描所有 agent 的位置，产出 `list[EncounterCandidate]`：

- 输入两类来源：
  1. **trace-based**：本 tick 移动过的 agent 的 `TickMovementTrace.locations`
     里的每个 sub-step location（已有路径）
  2. **end-of-tick co-presence**：`Ledger.list_entity_ids()` + `get_entity()`
     快照里**每个**entity 的 `current_location`——包括 stationary（WaitIntent /
     任何 non-MoveIntent）的 agent
- 把两类来源按 location 分桶聚合到 `location_visitors: dict[str, set[str]]`
  (set 自动 dedup 同 agent × 同 location 的多次 add)
- 对任意两 agent a < b（字典序），若两人共享至少 1 个 location，emit
  `EncounterCandidate(tick, agent_a, agent_b, shared_locations)`。
- `shared_locations` SHALL 为 `tuple(sorted(intersection))`——固定字典序，
  跨运行一致，支撑 determinism Requirement。
- 扫描 SHALL 用按 location 分桶实现（O(total_trace_length + N) 而非 O(N²)）。
- EncounterCandidate MUST NOT 写入 Ledger；通过 `on_tick_end` 交给订阅者。

**语义升级**（fix-encounter-detection-and-observability，2026-05-10）：原版本只看
trace-based 位置，stationary agent 完全不进检测 → 系统性低估 dwell 期 encounter
（参见 `docs/audit/2026-05-09-bug-hunt.md` B9）。新版本"co-presence at end-of-tick"
口径更贴近"两个人此刻在同一物理位置"的直觉，与 thesis 关注的 encounter density
信号对齐。

#### Scenario: 同一街道段交汇
- **WHEN** agent `alpha` 从 `street_1` 移至 `cafe_a`，经过
  `[street_1, street_2, cafe_a]`；同 tick agent `beta` 从 `park` 移至
  `street_2`，经过 `[park, street_2]`
- **THEN** `EncounterCandidate(agent_a="alpha", agent_b="beta",
  shared_locations=["street_2"])` SHALL 出现在本 tick 的 TickResult

#### Scenario: 仅终点重合不算 trace 交集（trace-based 路径）
- **WHEN** agent `alpha` 与 `beta` 不同 tick 先后到达 cafe_a，且 alpha
  本 tick 已离开 cafe_a
- **THEN** 那些 tick 各自 SHALL NOT 产出 encounter（trace 交集跨 tick
  不成立；end-of-tick 同 location 也不重合）

#### Scenario: MoveIntent 第一步就失败
- **WHEN** agent 的第一个 sub-step 即失败（起点即不可达目标）
- **THEN** 该 agent 本 tick 的 `TickMovementTrace.locations` SHALL 为空元组；
  但其 ledger 中的 `current_location` 仍参与 end-of-tick co-presence 扫描

#### Scenario: stationary agent 同 location 共在
- **WHEN** agent `alpha` 与 `beta` 本 tick 都 issue WaitIntent（无 trace），
  且 ledger 中 `current_location[alpha] == current_location[beta] == "cafe_a"`
- **THEN** EncounterCandidate(agent_a="alpha", agent_b="beta",
  shared_locations=["cafe_a"]) SHALL 出现在本 tick 的 TickResult
  （这是 B9 修复的核心 scenario）

#### Scenario: walking-through 与 stationary 共在
- **WHEN** agent `alpha` 在 `cafe_a` 坐着 dwell（WaitIntent，无 trace），
  agent `beta` 经过 cafe_a 作为路径 sub-step（trace 包含 cafe_a）
- **THEN** EncounterCandidate(agent_a="alpha", agent_b="beta",
  shared_locations=["cafe_a"]) SHALL 出现在本 tick 的 TickResult

#### Scenario: 跨多 tick 持续 dwell
- **WHEN** alpha + beta 在 cafe_a 同时 dwell 12 个 tick，皆无 trace
- **THEN** 12 个 tick 每个 tick SHALL 各自产 1 个 EncounterCandidate
  （per-tick co-presence 计数；不去重；下游 reader 自己决定是否聚合到
  per-day pair count）

### Requirement: 确定性

Orchestrator SHALL 保证确定性：给定相同的
`seed / atlas / profile seeds / agents / initial ledger state`，
两次 `Orchestrator.run()` 结束后的 Ledger 快照逐字段一致。

- orchestrator 内部一切随机选择 SHALL 由 `seed` 参数派生（目前无此类
  随机，但保留该契约防范未来扩展）。
- IntentResolver 的裁决规则是纯字典序（不依赖 seed），天然确定性。

#### Scenario: 两次运行结果一致
- **WHEN** 使用同一配置跑 `Orchestrator.run()` 两次
- **THEN** 两次结束后 `Ledger.to_dict()` SHALL 逐字段相等

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

### Requirement: orchestrator 为 fitness-audit 的 phase2-gaps 探针自动翻绿

`synthetic_socio_wind_tunnel.orchestrator` 模块 SHALL importable；因此
`fitness-audit` 的 `phase2-gaps.orchestrator` AuditResult SHALL 为 PASS
（该转化由 `phase2_gaps.py` 的 `_module_exists` 探针实现）。

#### Scenario: 审计自动翻绿
- **WHEN** 运行 `make fitness-audit`
- **THEN** `phase2-gaps.orchestrator` AuditResult 的 `status` SHALL 为 `pass`

### Requirement: TickResult SHALL expose end-of-tick agent positions

The frozen dataclass `TickResult` MUST include an `entity_locations: tuple[tuple[str, str], ...]`
field defaulting to empty tuple. Each tuple element SHALL be a
`(agent_id, location_id)` pair representing the agent's location at the
end of this tick.

Orchestrator `_run_tick` MUST populate this field from the same
`entity_locations` dict it already computes for encounter detection (B9 fix).

The field SHALL be backward compatible: existing callers that construct
`TickResult(...)` without `entity_locations` MUST continue to work.

#### Scenario: orchestrator emits entity locations in tick result
- **WHEN** `_run_tick` completes a tick with 3 agents at locations a/b/c
- **THEN** the returned TickResult.entity_locations SHALL contain exactly
  3 pairs, one per agent

#### Scenario: backward compat for direct TickResult construction
- **WHEN** test code calls `TickResult(tick_index=0, simulated_time=..., commits=(), encounter_candidates=())`
  without entity_locations
- **THEN** the field SHALL default to empty tuple; no exception raised

### Requirement: Orchestrator SHALL enforce per-tick walking-distance budget

The orchestrator MUST limit how far an agent travels in a single tick.
`Orchestrator.__init__` SHALL accept a new keyword parameter
`walking_speed_m_per_min: float = 80.0` representing the global fallback
travel pace (used only when an agent lacks a per-agent speed value).

`_dispatch_move(agent_id, intent, agent)` MUST:

1. Compute `tick_budget_m = tick_minutes × agent_speed`, where `agent_speed`
   reads `agent.profile.walking_speed_m_per_min` and falls back to the
   orchestrator-level default.
2. Walk the route step-by-step, accumulating distance, and STOP after the
   first step whose accumulated distance reaches or exceeds `tick_budget_m`
   (always advance at least one step so a single oversized segment doesn't
   stall the agent).
3. Save unwalked NavigationSteps to `agent._in_flight_route_remaining` and
   `agent._in_flight_target = intent.to_location` so the next tick resumes
   from the same path.
4. Clear `_in_flight_*` when the route is fully consumed.

If a subsequent tick arrives with a different `intent.to_location` than
`agent._in_flight_target`, the orchestrator SHALL discard the stale
in-flight state and recompute a fresh route.

#### Scenario: long route spans multiple ticks
- **WHEN** an 80 m/min agent (400m budget) initiates a 1.2km route
- **THEN** the move SHALL complete across approximately 3 ticks; each
  intermediate tick SHALL leave `agent._in_flight_route_remaining` non-empty;
  the final tick SHALL clear it

#### Scenario: short route completes in one tick
- **WHEN** an 80 m/min agent moves to a destination 200m away (single tick
  budget covers it)
- **THEN** `agent._in_flight_route_remaining` SHALL be empty after the move

#### Scenario: target change invalidates in-flight state
- **WHEN** `_in_flight_target = "cafe_A"` and a new MoveIntent arrives with
  `to_location = "cafe_B"`
- **THEN** the orchestrator SHALL discard the cafe_A route and recompute
  to cafe_B from the agent's current location

#### Scenario: at least one segment per tick (no stall)
- **WHEN** the only available segment is 500m (exceeds 400m budget for a
  walker)
- **THEN** the agent SHALL still advance one segment that tick; budget
  is treated as advisory, not absolute, for single-segment progress

### Requirement: Orchestrator SHALL call NavigationService with agent-appropriate mode

`_dispatch_move` MUST pick `mode = "driving"` when
`agent.profile.prefer_driving is True`, else `mode = "walking"`. If the
mode-filtered route returns `success=False`, the orchestrator MAY retry
with `mode="any"` as a fallback to avoid hard-failing on edge cases (e.g.
a tagged pedestrian path leading to the final building).

#### Scenario: walker requests walking mode
- **WHEN** `_dispatch_move` runs for an agent with
  `profile.prefer_driving == False`
- **THEN** the first `nav.find_route` call SHALL pass `mode="walking"`

#### Scenario: driver requests driving mode
- **WHEN** `_dispatch_move` runs for an agent with
  `profile.prefer_driving == True`
- **THEN** the first `nav.find_route` call SHALL pass `mode="driving"`

#### Scenario: fallback to any if mode-filtered fails
- **WHEN** `nav.find_route(..., mode="walking")` returns `success=False`
- **THEN** the orchestrator SHALL retry with `nav.find_route(..., mode="any")`
  before raising a Route-not-found error

### Requirement: tick-end async hooks SHALL share a persistent event loop

`Orchestrator._fire_async_tick_end` SHALL use a single persistent
`asyncio.AbstractEventLoop` instance attached to the Orchestrator
for the duration of the simulation, rather than calling
`asyncio.run()` per tick (which creates+destroys a fresh loop each
time). httpx.AsyncClient and other async-bound resources keep
internal state tied to the first loop they were used in; per-tick
fresh loops cause state corruption that has been observed to manifest
as recurring deadlock at scale (2026-05-20 scout: 4 worker hang at
~1.5h, backlog 1.9).

The loop is lazy-created on first call. Cleanup happens on the
`on_simulation_end` hook. The orchestrator's outer API
(`Orchestrator.run`, `MultiDayRunner.run_multi_day`) remains
synchronous.

#### Scenario: 多次 tick_end async 调用复用同一 loop

- **GIVEN** an Orchestrator with at least one async tick_end hook
  registered
- **WHEN** `_fire_async_tick_end` is invoked N times during simulation
- **THEN** the SAME `asyncio.AbstractEventLoop` instance SHALL be used
  for all N invocations
- **AND** at no point SHALL `asyncio.run()` be called inside the
  Orchestrator's tick path

#### Scenario: 无 async hook 时不创建 loop

- **GIVEN** an Orchestrator with NO async tick_end hooks registered
- **WHEN** `_fire_async_tick_end` is invoked
- **THEN** no event loop SHALL be created (back-compat for sync-only
  simulations)

#### Scenario: simulation 结束时关闭 loop

- **GIVEN** an Orchestrator that has been running with a persistent
  event loop
- **WHEN** `on_simulation_end` hooks fire (end of simulation)
- **THEN** the persistent loop SHALL be closed (`loop.is_closed() == True`)

