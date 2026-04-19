# agent — LLM 智能体运行时（Phase 1）

## Purpose
`agent` 模块实现计划式（planning-based）智能体：每个 agent 在一天开始时由 LLM
生成 `DailyPlan`，随后按计划执行，仅在被打断时重规划。通过分层模型预算
（10 个 Sonnet 主角 + 990 个 Haiku 分级）控制 1000 agent 的 LLM 成本。

## Requirements

### Requirement: AgentProfile 作为静态身份
`agent.profile.AgentProfile` SHALL 包含：
`agent_id`、`name`、`age`、`occupation`、`household`、`home_location`、
`personality_traits: dict[str, float]`、`personality_description: str`、
`preferred_social_size`、`interests`、`languages`、`wake_time`、`sleep_time`、
`is_protagonist: bool`、`base_model: str`。

- Profile 在 agent 生命周期内 SHALL 不变；`trait(name, default=0.5)` 用于安全取值。

#### Scenario: 未定义的人格维度
- **WHEN** 查询 `profile.trait("mysticism")` 而 profile 未包含该字段
- **THEN** SHALL 返回默认值 `0.5`

### Requirement: 每日计划生成（一次 LLM / 天）
`Planner(llm_client)` SHALL 在构造时注入 LLM 客户端；
`await planner.generate_daily_plan(profile, *, date, day_of_week, weather,
available_locations, life_patterns) → DailyPlan` 为**异步**方法，
SHALL：
- 构造 prompt（`_PLAN_PROMPT_TEMPLATE`），包含人格、家庭位置、兴趣、
  当日天气与作息；
- 调用 `llm_client.generate(prompt, model=profile.base_model)` 一次，解析
  出 `PlanStep` 列表；
- 解析失败时 SHALL 返回空 steps 的 DailyPlan，不得抛异常中断 tick。
- 每个 PlanStep SHALL 含 `time`（如 `"7:00"`）、`action`
  （`move` / `stay` / `interact` / `explore`）、`destination`、`activity`、
  `duration_minutes`、`reason`、`social_intent`
  （`alone` / `open_to_chat` / `seeking_company`）。

- 整个模拟日 SHALL 每个 agent 仅调用一次 `generate_daily_plan`。

#### Scenario: 外向性高者更愿意社交
- **WHEN** profile `extroversion=0.9`
- **THEN** 返回的 PlanStep 中 `social_intent` 为 `seeking_company`
  的比例 SHOULD 显著高于 `extroversion=0.1` 的同类 agent

### Requirement: 计划打断（当前仅支持手动插入）
Phase 1 SHALL 通过 `DailyPlan.insert_interrupt(step, at_index=None)` 在当前
步骤之后插入打断步骤。**完整的 `replan(profile, plan, interrupts, llm_client)`
接口尚未实现**，相关能力在 Phase 2 的 `conversation` / `memory` change 中落地。

#### Scenario: 手动插入聚会打断
- **WHEN** 正在步行上班的 agent 决定加入咖啡聚会
- **THEN** 调用方 SHALL 用 `plan.insert_interrupt(PlanStep(...))` 在
  `current_step_index + 1` 处插入一步，后续 tick `plan.advance()` 推进到该步

### Requirement: AgentRuntime 执行态
`agent.runtime.AgentRuntime` SHALL 包装单个 agent 的可变状态：
- `profile: AgentProfile`、`plan: DailyPlan | None`、`current_location: str`；
- 运动控制：`is_moving`（property）、`start_moving(route)`、
  `next_move_location()`、`cancel_movement()`；
- 计划控制：`set_plan(plan)`、`current_step()`、`advance_plan()`；
- 感知上下文构造：`build_observer_context() → ObserverContext`。

#### Scenario: 逐步执行路径
- **WHEN** runtime 已 `start_moving(route)`
- **THEN** 每次调用 `next_move_location()` SHALL 返回路径上的下一个位置 id，
  直到耗尽后 `is_moving` 变为 False

### Requirement: 成本预算与分层模型
整个模拟 SHALL 在单日 100 tick / 1000 agent 规模下维持 LLM 调用在数量级
1,000–5,000 次量级，而非每 tick 每 agent 都调用。

- 主角 agent（`is_protagonist=True`，数量约 10）SHALL 使用更强模型
  （例如 Sonnet）作为 `base_model`；
- 其余 agent SHALL 默认使用 Haiku 或等价轻量模型；
- 模型选择 SHALL 在 runtime/planner 中通过 `profile.base_model` 透明化。

#### Scenario: 模型预算验证
- **WHEN** 运行一天 1000 agent 的模拟
- **THEN** 实际 LLM 调用次数 SHOULD 接近"每 agent 一次基础计划 + 若干重规划"，
  与全量调用形成显著成本差（文档化为实验指标）

### Requirement: 对其它模块的只读依赖
agent 模块在生成/执行计划时 SHALL 只通过：
- `map_service`（已知目的地、路径）
- `perception.pipeline`（当前观察）
- `Ledger`（时间、天气）

读取世界，且 SHALL 不直接修改 Ledger；所有写入 SHALL 委派给 simulation。

#### Scenario: runtime 无副作用读
- **WHEN** `build_observer_context()` 被调用
- **THEN** SHALL 仅调用 ledger / atlas 的读方法，不产生任何状态更改
