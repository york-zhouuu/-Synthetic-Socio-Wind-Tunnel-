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
available_locations, life_patterns, carryover: CarryoverContext | None = None)
→ DailyPlan` 为**异步**方法，SHALL：
- 构造 prompt（`_PLAN_PROMPT_TEMPLATE`），包含人格、家庭位置、兴趣、
  当日天气与作息；
- **若 `carryover` 非 None**：prompt 额外包含三段：
  - `【昨日经历摘要】{carryover.yesterday_summary.summary_text}`
  - `【近 3 日反思】` 按 day_index 升序列出每条 summary 前 120 字
  - `【未完成任务锚点】` 列出 pending_task_anchors 的 content（≤ 5 条）
  - 提示 LLM："当前日期是 {date}；请生成与过去经历一致但允许偏离的新 plan"；
  - 如果 carryover 总字数超过 1500 字，SHALL 对 summary_text 截断到前 300 字
    以防 prompt 爆炸；
- 调用 `llm_client.generate(prompt, model=profile.base_model)` 一次，解析
  出 `PlanStep` 列表；
- 解析失败时 SHALL 返回空 steps 的 DailyPlan，不得抛异常中断 tick。
- 每个 PlanStep SHALL 含 `time`（如 `"7:00"`）、`action`
  （`move` / `stay` / `interact` / `explore`）、`destination`、`activity`、
  `duration_minutes`、`reason`、`social_intent`
  （`alone` / `open_to_chat` / `seeking_company`）。

- **每个 simulated day** SHALL 每个 agent 仅调用一次 `generate_daily_plan`
  （`carryover=None` 时行为与单日路径完全一致）。
- `carryover=None` 是默认值；单日调用方无需改造。

#### Scenario: 外向性高者更愿意社交
- **WHEN** profile `extroversion=0.9`
- **THEN** 返回的 PlanStep 中 `social_intent` 为 `seeking_company`
  的比例 SHOULD 显著高于 `extroversion=0.1` 的同类 agent

#### Scenario: carryover=None 时向后兼容
- **WHEN** 调用 `generate_daily_plan(profile, date=d, ..., carryover=None)`
- **THEN** 生成的 prompt SHALL 与 Phase 2 归档时完全一致；LLM 调用次数
  SHALL 为 1；产出的 DailyPlan 与单日路径等价

#### Scenario: carryover 非空时 prompt 扩展
- **WHEN** 调用时 `carryover` 非 None 且含非空 yesterday_summary +
  2 条 recent_reflections + 3 条 pending_task_anchors
- **THEN** prompt SHALL 新增【昨日经历摘要】/【近 3 日反思】/
  【未完成任务锚点】三个段落；LLM 调用次数 SHALL 仍为 1；总 prompt
  字符数 SHALL ≤ 1500 + 原单日 prompt 长度

#### Scenario: carryover 过长时截断
- **WHEN** carryover.yesterday_summary.summary_text 长 800 字符
- **THEN** prompt 中该 summary_text SHALL 被截断到 300 字符 + "…"

#### Scenario: 多日调用 plan 重生成
- **WHEN** `MultiDayRunner.run_multi_day(num_days=3)` 触发每日
  on_day_start 调 `planner.generate_daily_plan(..., carryover=ctx_day_N)`
- **THEN** 每日 SHALL 恰生成一个新 DailyPlan（共 3 个）；carryover 在
  day 0 为 None、day 1+ 非 None

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

---

<!-- Added by realign-to-social-thesis (archived 2026-04-20) -->

### Requirement: AgentProfile 结构性身份维度

`agent.profile.AgentProfile` SHALL 新增一组**结构性**字段，表达 thesis 所需
的社会结构异质性。所有字段默认值 SHALL 使老构造签名保持兼容。

- `ethnicity_group: str | None = None`
  值 SHALL 使用区域码（例如 `"AU-born"`、`"AU-migrant-1gen-asia"`、
  `"AU-migrant-2gen-europe"`），**不**使用具体国籍或族群名词；
- `migration_tenure_years: float | None = None`
  负值 SHALL 被 Pydantic 校验拒绝；
- `housing_tenure: Literal["owner_occupier", "renter", "public_housing"] | None = None`；
- `income_tier: Literal["low", "mid", "high"] | None = None`；
- `work_mode: Literal["commute", "remote", "shift", "nonworking"] | None = None`；
- `digital: DigitalProfile = DigitalProfile()`（定义见 `attention-channel`）。

这些字段 SHALL 与既有 `personality_traits` 正交：LLM prompt 可以把两者一起
喂入，但基建层不做跨字段合成指标。

#### Scenario: 旧构造签名仍工作
- **WHEN** 调用 `AgentProfile(agent_id, name, age, occupation, household, home_location)`
  （无任何结构性参数）
- **THEN** profile 构造 SHALL 成功；结构性字段 SHALL 全部为 `None`，
  `digital` SHALL 为默认 DigitalProfile

#### Scenario: 结构性字段校验
- **WHEN** 构造 `AgentProfile(..., migration_tenure_years=-3)`
- **THEN** Pydantic SHALL 抛校验错误，拒绝负数

#### Scenario: LLM prompt 可读取结构性字段
- **WHEN** `Planner.generate_daily_plan` 构造 prompt
- **THEN** prompt SHALL 能通过 profile 读取 `ethnicity_group` /
  `housing_tenure` / `income_tier` / `work_mode` / `digital.feed_bias`
  的字面值（由 planner 自行决定是否注入）

### Requirement: Population 采样子模块

系统 SHALL 在 `synthetic_socio_wind_tunnel/agent/population.py` 中提供：

- `PopulationProfile`：声明一个社区的人群画像，字段包括
  `size: int`、`ethnicity_distribution: dict[str, float]`（权重和为 1.0）、
  `housing_distribution: dict[str, float]`、`income_distribution: dict[str, float]`、
  `work_mode_distribution: dict[str, float]`、`digital_profile_params: DigitalParams`、
  `age_bracket_distribution: dict[str, float]`、
  `language_distribution: dict[str, float]`。
- `sample_population(profile: PopulationProfile, *, seed: int) -> list[AgentProfile]`
  按画像采样，返回长度为 `profile.size` 的 AgentProfile 列表。
- 内置 preset：`LANE_COVE_PROFILE`。数值为占位（非 ABS-ground-truthed），
  后续 change 做一次性对齐。

采样 SHALL：
- 完全由 `seed` 决定，同一 seed 产出逐字段一致的结果（可复现）；
- 分布权重之和 SHALL 为 1.0 ± 1e-6；偏差超阈值 SHALL 抛错；
- Profile 生成的 `agent_id` SHALL 为 `"a_{seed}_{index:04d}"` 格式，全局可追溯。

#### Scenario: 确定性采样
- **WHEN** 两次调用 `sample_population(LANE_COVE_PROFILE, seed=42)`
- **THEN** 两次返回的 profile 列表 SHALL 逐字段一致

#### Scenario: 分布权重校验
- **WHEN** 画像的 `ethnicity_distribution` 权重之和为 0.8
- **THEN** `sample_population` SHALL 在预检阶段抛 `ValueError`

#### Scenario: 主角分配
- **WHEN** 采样 1000 人时请求 `num_protagonists=10`
- **THEN** 返回列表中恰好 10 个 profile 的 `is_protagonist=True`，
  其 `base_model` SHALL 为 Sonnet 档；其余 990 个为 Haiku 档

### Requirement: ObserverContext 构造从 Profile 读取 digital

`AgentRuntime.build_observer_context()` SHALL 把 `profile.digital` 与
`AttentionService.pending_for(agent_id)` 合成为 `AttentionState` 并挂到
`ObserverContext.digital_state`。

- 若 `AttentionService` 未注入（向后兼容路径），`digital_state` SHALL 为 `None`。
- 合成逻辑 SHALL 为纯函数（无副作用）；MUST NOT 写入 Ledger。

#### Scenario: 无 AttentionService 的退化
- **WHEN** `AgentRuntime.build_observer_context()` 在未注入 AttentionService
  的环境下被调用
- **THEN** 返回的 `ObserverContext.digital_state` SHALL 为 `None`；
  其余字段行为与本 change 之前一致

#### Scenario: 有推送时 pending 非空
- **WHEN** AttentionService 已为该 agent 注入 2 条 feed item，
  且 agent `profile.digital.notification_responsiveness > 0`
- **THEN** `build_observer_context().digital_state.pending_notifications`
  SHALL 包含这两个 feed_item_id

---

<!-- Added by orchestrator (archived 2026-04-20) -->

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

---

<!-- Added by typed-personality (archived 2026-04-21) -->
<!-- 这些 Requirement 在语义上 MODIFY 了"AgentProfile 作为静态身份"——
     personality_traits dict 被 typed PersonalityTraits 替换，
     personality_description / trait() 方法被移除。以"追加 + 覆盖老描述"
     方式保留历史；运行时代码以这些新 Requirement 为准。 -->

### Requirement: PersonalityTraits 为 typed 人格模型

系统 SHALL 在 `synthetic_socio_wind_tunnel/agent/personality.py` 中定义
`PersonalityTraits` Pydantic 模型：

- 字段（全部 `float`，默认 0.5，`[0.0, 1.0]` 范围校验）：
  - `openness`
  - `conscientiousness`
  - `extraversion`
  - `agreeableness`
  - `neuroticism`
  - `curiosity`
  - `routine_adherence`
  - `risk_tolerance`
- `model_config = {"frozen": True}`，可哈希
- 越界值 SHALL 被 Pydantic 拒绝

#### Scenario: 默认构造全是 0.5
- **WHEN** 构造 `PersonalityTraits()`
- **THEN** 所有 8 个字段 SHALL 为 0.5

#### Scenario: 越界值被拒
- **WHEN** 构造 `PersonalityTraits(curiosity=1.5)`
- **THEN** SHALL 抛 Pydantic ValidationError

#### Scenario: frozen
- **WHEN** 对构造好的 PersonalityTraits 赋值
- **THEN** SHALL 抛 ValidationError

### Requirement: Skills 与 EmotionalState typed 模型

系统 SHALL 在同文件提供：

```
class Skills(BaseModel):
    perception: float = 0.5      # [0, 1]
    investigation: float = 0.5
    stealth: float = 0.5

class EmotionalState(BaseModel):
    guilt: float = 0.0           # [0, 1]
    anxiety: float = 0.0
    curiosity: float = 0.0
    fear: float = 0.0
```

- 字段越界 SHALL 被拒
- `model_config = {"frozen": True}`

#### Scenario: 默认 Skills 0.5 / 默认 Emotion 0.0
- **WHEN** 分别构造 `Skills()` 与 `EmotionalState()`
- **THEN** 前者默认 0.5，后者默认 0.0

### Requirement: AgentProfile 使用 typed personality

`AgentProfile` SHALL：
- 移除字段 `personality_traits: dict[str, float]`
- 移除字段 `personality_description: str`
- 移除方法 `trait(name, default)`
- 新增字段 `personality: PersonalityTraits = Field(default_factory=PersonalityTraits)`
- 保留其它现有字段

- 调用方读取 trait 时 SHALL 使用 `profile.personality.curiosity` 等
  typed 访问，不再使用字符串索引。

#### Scenario: 直接读取 typed trait
- **WHEN** `profile = AgentProfile(agent_id=..., ...)`
- **THEN** `profile.personality.curiosity` SHALL 为 0.5（默认），可直接
  被 IDE 类型检查

#### Scenario: trait() 便利方法已移除
- **WHEN** 调用 `profile.trait("curiosity")`
- **THEN** SHALL 抛 AttributeError（方法不存在）

### Requirement: PlanStep 的 action / social_intent Literal 化

`PlanStep` 字段 SHALL 使用 Literal 类型：

- `action: Literal["move", "stay", "interact", "explore"]`
- `social_intent: Literal["alone", "open_to_chat", "seeking_company"] = "alone"`

- `AgentProfile.household: Literal["single", "couple", "family_with_kids"]`

- LLM 产出的 JSON 若 action 值不在允许集合，Pydantic SHALL 在
  `_parse_plan_response` 的 `PlanStep(**data)` 处抛 ValidationError；
  Planner 现有 try/except 捕获后返回空 plan。

#### Scenario: Literal 拒绝无效 action
- **WHEN** 构造 `PlanStep(time="7:00", action="walk")`（"walk" 不在允许集）
- **THEN** SHALL 抛 Pydantic ValidationError

#### Scenario: LLM 吐错字母被捕获
- **WHEN** Planner 解析一段 LLM 输出，其中一个 step 的 action 为
  "moves"（拼写错误）
- **THEN** Planner SHALL 捕获 ValidationError 并返回空 DailyPlan，
  日志记录原始 LLM 输出

### Requirement: PopulationProfile 使用 PersonalityParams 采样

`PopulationProfile` SHALL 新增字段
`personality_params: PersonalityParams = Field(default_factory=PersonalityParams)`。

`PersonalityParams` SHALL 为 Pydantic 模型，每个 PersonalityTraits 维度
对应一个 `(mean, std)` tuple，默认全部 `(0.5, 0.2)`。

`sample_population` SHALL 对每个 agent 按
`clamp(random.gauss(mean, std), 0.0, 1.0)` 独立采样 8 个维度，构造
PersonalityTraits 并放入 AgentProfile。

#### Scenario: 1000 样本人格异质性
- **WHEN** `sample_population(LANE_COVE_PROFILE, seed=42)` 产出 1000
  AgentProfile
- **THEN** 这些 agent 的 `personality.curiosity` std SHALL ≥ 0.15
  （默认 (0.5, 0.2) 采样自然满足）

#### Scenario: seed 可复现
- **WHEN** 两次 `sample_population(profile, seed=42)`
- **THEN** 所有 agent 的 PersonalityTraits 所有字段 SHALL 逐字段相等

### Requirement: Planner prompt 引用 typed trait

`Planner._build_prompt`（或同效代码路径）SHALL 在 prompt 中以结构化文本
引用 `profile.personality` 的 8 个字段（每个两位小数），而非旧的
`personality_description` 自由文本。

#### Scenario: prompt 含人格数值
- **WHEN** 对某 agent `profile.personality.curiosity = 0.87` 构造 prompt
- **THEN** prompt 字符串 SHALL 包含 `"0.87"` 或 `"0.9"` 之类的数值表示，
  LLM 能够直接读到具体好奇心强度

---

<!-- Added by memory (archived 2026-04-21) -->

### Requirement: AgentRuntime.should_replan 纯代码规则

`AgentRuntime` SHALL 新增方法：

```
should_replan(
  memory_view: Sequence[MemoryEvent],
  candidate: MemoryEvent,
) -> bool
```

- 方法 SHALL 为**纯代码规则**，MUST NOT 调用 LLM（每 tick 每 agent 触发，
  LLM 成本禁区）。
- 默认实现基于 `profile.personality.routine_adherence` /
  `profile.personality.curiosity` typed 字段（typed-personality change 引入）
  以及 `candidate.kind` 分支决定；具体规则由 `memory` spec 的
  process_tick Requirement 与 `docs/agent_system/09` 文档说明。
- 子类或策略对象可覆盖 `should_replan`；基类版本保持为"合理默认"。
- 方法不得修改 memory_view 或 candidate（只读分析）。

#### Scenario: 高好奇心 agent 对通知返回 True
- **WHEN** agent `profile.personality.routine_adherence=0.2,
  profile.personality.curiosity=0.9`，candidate 是 `kind="notification"` 且
  `urgency=0.8`
- **THEN** `should_replan(memory_view, candidate)` SHALL 返回 `True`

#### Scenario: 高坚持 agent 对通知返回 False
- **WHEN** agent `profile.personality.routine_adherence=0.9`，同样的通知
  candidate
- **THEN** `should_replan(memory_view, candidate)` SHALL 返回 `False`

#### Scenario: 方法不调用 LLM
- **WHEN** `should_replan` 被调用 10000 次
- **THEN** 任何 LLMClient / anthropic SDK / 网络请求 SHALL 不被触发；
  耗时 SHALL 在毫秒量级

### Requirement: Planner.replan 方法

`Planner` SHALL 新增异步方法：

```
async replan(
  profile: AgentProfile,
  current_plan: DailyPlan,
  interrupt_ctx: dict,
) -> DailyPlan
```

- `interrupt_ctx` 至少含 `trigger_event: MemoryEvent` 与
  `recent_memories: list[MemoryEvent]`。
- SHALL 调用 `llm_client.generate(prompt, model=profile.base_model)`
  恰好 1 次。
- 产出新 DailyPlan：`current_step_index` 保留为原值；
  `steps[:current_step_index]` 不变；`steps[current_step_index:]` 替换为
  LLM 新产的 step 列表。
- LLM 解析失败时 SHALL 返回 `current_plan` 的副本（fallback），不抛异常。

#### Scenario: 成功 replan
- **WHEN** 当前 plan 有 10 step，`current_step_index=4`；replan 触发
- **THEN** 返回的新 plan SHALL 保留 `steps[:4]`，替换 `steps[4:]`；
  llm_client.generate SHALL 被调用 1 次

#### Scenario: LLM 失败 fallback
- **WHEN** llm_client.generate 抛异常
- **THEN** `replan` SHALL 返回原 plan 的副本，不抛；日志 SHALL 含"replan_failed"
