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
- 若 `conversation` 在 MemoryService 构造时注入（conversation-capability），
  SHALL 完成两件事：
  - **Origin 注入**：每条本 tick 新派生的 `notification` / `task_received`
    MemoryEvent，转换为对应的 `Information` 实例（`category="push"`，
    salience 由 feed_item 的 hyperlocal_radius / category 推导），并调
    `conversation.record_origin(info, recipient_agent_id, tick)`。
    salience 推导规则：
    - `hyperlocal_radius < 1000` → 0.8
    - `category in ("local_news", "task")` → 0.6
    - `category == "commercial_push"` → 0.5
    - `category in ("global_news", "global_distraction")` → 0.3
    - 默认 → 0.4
  - **传播驱动**：调 `conversation.process_tick(tick_result, social_graph,
    sim_day)` 让信息在本 tick 的 encounters 上按概率传播。`sim_day` 取自
    `tick_result.day_index`。要求 social_graph 同时注入；conversation 注入
    但 social_graph 未注入 SHALL 抛 ValueError（明确错误优于隐式降级）。
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

#### Scenario: conversation 注入但 social_graph 未注入抛错

- **WHEN** MemoryService 构造时只传 conversation，不传 social_graph
- **THEN** 构造或第一次 process_tick 调用 SHALL 抛 ValueError，明确说明
  conversation 依赖 social_graph

#### Scenario: push 注入信息源

- **WHEN** MemoryService 注入 conversation + social_graph；本 tick
  AttentionService 派出一条 hyperlocal feed item 给 emma
  （hyperlocal_radius=500）
- **THEN** `conversation.info_known_by("emma")` SHALL 含 1 条 info；
  `conversation.get_propagation(info_id).hops_at["emma"]` SHALL == 0；
  info.salience SHALL == 0.8

#### Scenario: salience 由 category 推导

- **WHEN** 一条 feed_item 的 category="global_distraction"，hyperlocal_radius=None
- **THEN** record_origin 派出的 Information 的 salience SHALL == 0.3

#### Scenario: 信息在 encounter 上传播

- **WHEN** emma 已 known info（origin），emma 与 linda 在 tick=20 encounter；
  emma 与 linda 已有 strength=0.5 的 tie（中等强度）；两人 extraversion 均值=0.7；
  info.salience=0.8；origin 是当天
- **THEN** `conversation.process_tick` 至少有一定概率（实测 P ≈ 0.15 ×
  1.0 × 0.7 × 0.8 × 1.0 ≈ 0.084）让 linda 知道；多 seed 下 linda known
  比例应在 [5%, 15%]

#### Scenario: replan 一 tick 最多一次
- **WHEN** emma 本 tick 接到 3 条通知，全部触发 should_replan=True
- **THEN** `planner.replan` SHALL 被调用**恰好一次**；第一个 match 后
  break

#### Scenario: replan_count_today 跨日重置

- **WHEN** emma 第一天 replan 4 次，新一天 on_day_start 后又触发一次
  should_replan
- **THEN** 新一天传给 should_replan 的 `replan_count_today` SHALL 为 0
