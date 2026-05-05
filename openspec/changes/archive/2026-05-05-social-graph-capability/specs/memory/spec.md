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
- 若 `social_graph` 在 MemoryService 构造时注入（social-graph-capability），
  SHALL 在写 encounter MemoryEvent 之外，**额外**对每条 encounter_candidate
  调用一次 `social_graph.record_encounter(agent_a, agent_b, tick, day_index)`
  累积 pairwise tie。MemoryService 不消费 `record_encounter` 的返回值。
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
    出现的 candidate，每个产出 `NearbyAgent(is_familiar)`
- `nearby_agents.is_familiar` 判定 SHALL 优先使用 social_graph：
  - 若 `social_graph` 已注入：`is_familiar = (other_id ∈
    social_graph.familiar_with(agent_id, threshold=0.1))`
  - 若 `social_graph` 未注入：降级到原行为（agent 的 memory 中是否存在
    actor_id 等于 other_id 的 `kind="encounter"` MemoryEvent）
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

#### Scenario: encounter 同步累积到 social_graph

- **WHEN** MemoryService 注入了 social_graph，TickResult 含
  EncounterCandidate(a="emma", b="linda", shared_locations=("cafe_main",))
  在 tick=10
- **THEN** `social_graph.get_tie("emma", "linda")` SHALL 返回非 None Tie
  且 `encounter_count == 1`，`first_seen_tick == 10`

#### Scenario: 未注入 social_graph 时不调 record

- **WHEN** MemoryService 构造时 social_graph=None，TickResult 含 1 条
  encounter_candidate
- **THEN** 行为不变；不抛异常；旧 callers 继续工作

#### Scenario: replan 一 tick 最多一次
- **WHEN** emma 本 tick 接到 3 条通知，全部触发 should_replan=True
- **THEN** `planner.replan` SHALL 被调用**恰好一次**；第一个 match 后
  break

#### Scenario: nearby_agents.is_familiar 走 social_graph

- **WHEN** social_graph 注入；emma 跟 linda 在历史上累积 encounter_count=5
  （strength ≈ 0.33 > 0.1）；emma 跟 john 累积 encounter_count=0
  （未见过）；本 tick TickResult 中 emma 跟 linda + john 各有一条
  encounter_candidate；触发 should_replan=True
- **THEN** 传给 planner.replan 的 `interrupt_ctx.nearby_agents` SHALL 含
  2 条；其中 linda 对应 `is_familiar=True`，john 对应 `is_familiar=False`

#### Scenario: nearby_agents.is_familiar 降级（未注入 social_graph）

- **WHEN** social_graph=None；emma 的 memory store 中**有**一条 actor_id="linda"
  的 encounter MemoryEvent；本 tick emma 跟 linda 又 encounter
- **THEN** is_familiar SHALL 为 True（旧行为：memory 里有 encounter 即算
  familiar）

#### Scenario: replan_count_today 跨日重置

- **WHEN** emma 第一天 replan 4 次，新一天 on_day_start 后又触发一次
  should_replan
- **THEN** 新一天传给 should_replan 的 `replan_count_today` SHALL 为 0

#### Scenario: rng 来自 MemoryService

- **WHEN** 同 seed 跑两次相同 sim
- **THEN** 两次 should_replan 的 rng_roll 序列 SHALL 完全一致；replan
  决策序列 SHALL 完全一致
