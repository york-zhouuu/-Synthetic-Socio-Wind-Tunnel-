## MODIFIED Requirements

### Requirement: Orchestrator 集成（process_tick）

MemoryService SHALL 提供 `process_tick(tick_result: TickResult,
agents: Mapping[str, AgentRuntime], planner: Planner | None)
-> list[tuple[str, MemoryEvent]]`：

- 从 `tick_result.commits` 派生 per-agent `action` MemoryEvent。
- 从 `tick_result.encounter_candidates` 派生 `encounter` MemoryEvent
  （两侧各写一条）。
- 若 `attention_service` 在 MemoryService 构造时注入，
  SHALL 从它查询本 tick 新交付的 NotificationEvent，派生 `notification`
  MemoryEvent；`task_received` kind 在 notification 的 feed_item 的
  category == "task" 时派生。
- 若 `planner` 非 None，对每个 agent 调用
  `runtime.should_replan(recent, candidate, current_step, replan_count_today, rng)`；返回 True 时调
  `planner.replan(profile, current_plan, interrupt_ctx)`，用结果替换
  plan。每 tick 每 agent SHALL 最多 replan 一次。
- `interrupt_ctx` 装配 SHALL 包含以下字段（详见 `agent` spec 的
  `Requirement: Planner.replan 方法`）：
  - `trigger_event`、`recent_memories`、`current_time`（已有）
  - `current_step`：取自 `runtime.plan.current_step`（可为 None）
  - `current_location_kind`：从 `ledger.get_entity(aid).location_id` 反查
    `atlas` 中该 location 的 `area_type`（"street" / "park" / 等），归一化
    为 6 类标签
  - `nearby_agents`：从 `tick_result.encounter_candidates` 中筛选 `agent_id`
    出现的 candidate，每个产出 `NearbyAgent(is_familiar)`，`is_familiar`
    通过 agent 的 memory 中是否有过同 actor_id 的 encounter 判定
- `should_replan` 调用所用的 `rng` SHALL 是 MemoryService 持有的 seeded
  `random.Random` 实例（与 reproducibility lock 一致）。
- `replan_count_today` SHALL 由 MemoryService 维护 per-agent 计数；on_day_start
  时清零。

#### Scenario: tick 后 action 事件被记录
- **WHEN** orchestrator 完成一个 tick，其中 emma 有一次 MoveIntent
- **THEN** `memory.all_for("emma")` SHALL 含一条 kind=="action" 的 event

#### Scenario: encounter 双向记录
- **WHEN** TickResult 含 EncounterCandidate(a="emma", b="linda",
  shared_locations=("street_1",))
- **THEN** emma 与 linda 的 memory SHALL 各含一条 kind=="encounter"，
  彼此 actor_id 互指

#### Scenario: replan 一 tick 最多一次
- **WHEN** emma 本 tick 接到 3 条通知，全部触发 should_replan=True
- **THEN** `planner.replan` SHALL 被调用**恰好一次**；第一个 match 后
  break

#### Scenario: interrupt_ctx 装配新字段

- **WHEN** emma 在 `cafe_main` 当前正在 step "have lunch"，附近有 1 个
  familiar agent + 2 个 stranger，should_replan 返回 True
- **THEN** 传给 `planner.replan` 的 `interrupt_ctx` SHALL 含:
  - `current_step.activity == "have lunch"`
  - `current_location_kind == "cafe"`
  - `nearby_agents` 长度为 3，其中 1 条 `is_familiar=True`，2 条
    `is_familiar=False`

#### Scenario: replan_count_today 跨日重置

- **WHEN** emma 第一天 replan 4 次，新一天 on_day_start 后又触发一次
  should_replan
- **THEN** 新一天传给 should_replan 的 `replan_count_today` SHALL 为 0

#### Scenario: rng 来自 MemoryService

- **WHEN** 同 seed 跑两次相同 sim
- **THEN** 两次 should_replan 的 rng_roll 序列 SHALL 完全一致；replan
  决策序列 SHALL 完全一致
