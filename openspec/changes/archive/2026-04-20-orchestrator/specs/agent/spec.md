# agent — 能力增量

## ADDED Requirements

### Requirement: Intent 层次

系统 SHALL 在 `synthetic_socio_wind_tunnel/agent/intent.py` 中定义
Intent 类型层次：

- `Intent` 基类（frozen / 可哈希）。
- **非独占**（orchestrator 不走裁决器，直接提交）：
  - `MoveIntent(to_location: str)`
  - `WaitIntent(reason: str = "")`
  - `ExamineIntent(target_id: str)`
- **独占**（orchestrator 走 IntentResolver 按字典序选赢家）：
  - `PickupIntent(item_id: str)`
  - `OpenDoorIntent(door_id: str)`
  - `UnlockIntent(door_id: str, key_id: str | None = None)`
  - `LockIntent(door_id: str, key_id: str | None = None)`

- 所有 Intent SHALL 为 frozen，暴露 `exclusive: bool` property 便于
  orchestrator 分流；独占 Intent 额外暴露 `target_id` property。
- Intent MUST NOT 包含执行结果字段（结果由 `SimulationResult` 承载）。

#### Scenario: 非独占 Intent 标识
- **WHEN** 构造 `MoveIntent(to_location="cafe_a")`
- **THEN** `intent.exclusive` SHALL 为 `False`

#### Scenario: 独占 Intent 暴露 target_id
- **WHEN** 构造 `PickupIntent(item_id="umbrella_01")`
- **THEN** `intent.exclusive` SHALL 为 `True`；`intent.target_id` SHALL
  为 `"umbrella_01"`

#### Scenario: Intent 可哈希
- **WHEN** 两个 `MoveIntent(to_location="cafe_a")` 实例
- **THEN** SHALL 具备相同 hash 且相等；可作为 dict key

### Requirement: AgentRuntime.step 产出本 tick 的 Intent

`AgentRuntime` SHALL 新增方法：

```
step(tick_ctx: TickContext) -> Intent
```

- 输入 `TickContext` 含 `tick_index / simulated_time / observer_context`
  （`TickContext` 在 `orchestrator` 模块定义；`agent.intent` 模块通过
  `typing.TYPE_CHECKING` 引用，避免运行时循环依赖）。
- 返回**恰好一个** Intent。
- `step()` SHALL 在内部自管 plan advance——当 `current_step` 的时间窗
  已过（`simulated_time >= step.time + step.duration_minutes`）时，
  自动调用 `self.plan.advance()`；orchestrator MUST NOT 直接调
  `plan.advance()`。
- 映射规则（本 change 范围内）：
  - `action == "move"` 且 `current_location != destination` → `MoveIntent(to_location=destination)`
  - `action == "move"` 且 `current_location == destination` → `WaitIntent(reason="at_destination")`
  - 其它 `action`（`stay` / `interact` / `explore`）→ `WaitIntent(reason=action or activity)`
  - plan 为 None 或已耗尽 → `WaitIntent(reason="plan_exhausted")`
- 本 change **不**产出 `ExamineIntent` / `PickupIntent` / `OpenDoorIntent` /
  `UnlockIntent` / `LockIntent`——类型存在但由未来 change（policy-hack /
  conversation / memory）通过扩展 PlanStep 字段或外部插入机制产出。
- `step()` 是**幂等的状态读**（对 plan 状态可能有 advance 副作用，但不写
  Ledger）；MUST NOT 调用 LLM。

#### Scenario: plan 步骤映射到 MoveIntent
- **WHEN** `plan.current()` 为 `PlanStep(action="move",
  destination="cafe_a")` 且 `current_location != "cafe_a"`
- **THEN** `agent.step(tick_ctx)` SHALL 返回 `MoveIntent(to_location="cafe_a")`

#### Scenario: 到达目的地后返回 WaitIntent
- **WHEN** `plan.current()` 为 `PlanStep(action="move", destination="cafe_a",
  duration_minutes=30)`，agent 已 `current_location=="cafe_a"`，
  但 simulated_time 仍在该 step 时间窗内
- **THEN** `agent.step(tick_ctx)` SHALL 返回
  `WaitIntent(reason="at_destination")`

#### Scenario: 时间窗过期自动 advance
- **WHEN** `plan.current()` 为 `PlanStep(time="7:00", duration_minutes=30)`，
  `tick_ctx.simulated_time` 为 07:35
- **THEN** `step()` 内部 SHALL 自动调 `plan.advance()`；返回值基于
  **新的** current step

#### Scenario: 计划耗尽时返回 WaitIntent
- **WHEN** `agent.plan` 为 None 或所有 step 都已 advance 过
- **THEN** `agent.step(tick_ctx)` SHALL 返回
  `WaitIntent(reason="plan_exhausted")`

#### Scenario: 本 change 不产出独占类 Intent
- **WHEN** PlanStep 的 action 为 `"interact"` 或 `"explore"`
- **THEN** `step()` SHALL 返回 `WaitIntent`，MUST NOT 返回
  `ExamineIntent / PickupIntent / OpenDoorIntent / UnlockIntent / LockIntent`

### Requirement: 老方法保留并内部复用

系统 SHALL 保留 `AgentRuntime` 现有方法 `current_step()` /
`advance_plan()` / `next_move_location()` / `start_moving()` /
`cancel_movement()` 的原签名与语义，不打 deprecated 标记。

- `step(tick_ctx)` 内部 SHOULD 复用这些低层方法。
- 现有测试 (`tests/test_agent_phase1.py`) 中对这些方法的断言 SHALL 继续
  PASS。

#### Scenario: 老 API 不破坏
- **WHEN** 运行 `tests/test_agent_phase1.py`
- **THEN** 所有测试 SHALL 继续通过，与本 change 之前一致
