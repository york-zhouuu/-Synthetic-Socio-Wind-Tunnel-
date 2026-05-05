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

`AgentRuntime` SHALL 提供方法：

```
should_replan(
  memory_view: Sequence[MemoryEvent],
  candidate: MemoryEvent,
  current_step: PlanStep | None = None,
  replan_count_today: int = 0,
  rng: random.Random | None = None,
) -> bool
```

- 方法 SHALL 为**纯代码规则**，MUST NOT 调用 LLM。
- 决策 SHALL 综合 6 维 personality（`routine_adherence` / `curiosity` / `openness` / `conscientiousness` / `risk_tolerance` / `extraversion`）以及 candidate.urgency。
- 决策 SHALL 加入 **context modifier**：当 `current_step` 非 None 且 `elapsed_min > duration_minutes * 0.3`（已投入活动）时，触发阈值 SHALL 升高 ~0.10（更不易被新信息拉走）。
- 决策 SHALL 加入 **疲劳衰减**：`replan_count_today` 每加 1，触发阈值 SHALL 升高 ~0.05。
- 决策 SHALL 通过**概率门**实施（`rng.random() + (urgency - threshold) > 0`）而非硬阈值，使同一 urgency 在不同 sample 下产生有限随机性，避免"全 0 / 全 1"两极化。
- `rng` 为 None 时 SHALL 使用模块级 `random` 但 caller 必须感知此场景为非 reproducible；`MemoryService.process_tick` SHALL 注入 seeded `random.Random` 实例。
- 子类或策略对象可覆盖 `should_replan`；基类版本保持为"合理默认"。
- 方法不得修改 memory_view、candidate、current_step（只读分析）。
- 每次决策 SHALL 产出一条 `ReplanDecisionRecord`（入参 / 阈值各项 / rng_roll / 决策结果），追加到 agent 的决策日志（详见 `Requirement: AgentRuntime.replan_decision_log`）。

#### Scenario: 6 维 personality 都参与决策

- **WHEN** 两个 agent 仅 `personality.openness` 不同（一个 0.1，一个 0.9），其它 7 维 + life_pattern 完全一致；同时收到同一 candidate（`kind="notification"`, `urgency=0.6`）
- **THEN** 高 openness agent 触发概率 SHALL 显著高于低 openness agent（在 1000 次重复实验下 p<0.05）

#### Scenario: 已投入活动者更难被拉走

- **WHEN** agent A 的 `current_step.elapsed_min = 5` / `duration_minutes = 30`（刚开始），agent B 的 `current_step.elapsed_min = 20` / `duration_minutes = 30`（已投入），其它一切相同
- **THEN** 同一 candidate 下 agent B 的触发概率 SHALL 低于 agent A

#### Scenario: 疲劳衰减

- **WHEN** 同一 agent `replan_count_today` 从 0 累计到 3，期间 candidate 完全相同
- **THEN** 第 4 次 should_replan 的触发阈值 SHALL 比第 1 次高 ~0.15

#### Scenario: 概率门取代硬阈值

- **WHEN** 1000 次相同 urgency=0.6 / 相同 personality 的决策（不同 rng seed）
- **THEN** True 比例 SHALL 介于 [10%, 90%]（即不全 0 也不全 1，体现概率性）

#### Scenario: 方法不调用 LLM

- **WHEN** `should_replan` 被调用 10000 次
- **THEN** 任何 LLMClient / anthropic SDK / 网络请求 SHALL 不被触发；耗时 SHALL 在毫秒量级

### Requirement: Planner.replan 方法

`Planner` SHALL 提供异步方法：

```
async replan(
  profile: AgentProfile,
  current_plan: DailyPlan,
  interrupt_ctx: dict,
) -> DailyPlan
```

- `interrupt_ctx` SHALL 至少包含以下键：
  - `trigger_event: MemoryEvent`（触发本次 replan 的事件）
  - `recent_memories: list[MemoryEvent]`（最近 5-10 条记忆）
  - `current_time: datetime`
  - `current_step: PlanStep | None`（agent 当前正在执行的 step）
  - `current_location_kind: str`（"street" / "cafe" / "park" / "home" / "office" / "other"）
  - `nearby_agents: list[NearbyAgent]`（每条含 `is_familiar: bool`，无需暴露 id）
- SHALL 调用 `llm_client.generate(prompt, model=profile.base_model)` 恰好 1 次。
- prompt 由 `_build_replan_prompt` 装配，SHALL 满足 prompt 结构对称性约束（详见 `Requirement: Replan prompt 对称 context window`）。
- 产出新 DailyPlan：`current_step_index` 保留为原值；`steps[:current_step_index]` 不变；`steps[current_step_index:]` 替换为 LLM 新产的 step 列表。
- LLM 解析失败时 SHALL 返回 `current_plan` 的副本（fallback），不抛异常。

#### Scenario: 成功 replan

- **WHEN** 当前 plan 有 10 step，`current_step_index=4`；replan 触发；interrupt_ctx 含完整新 keys
- **THEN** 返回的新 plan SHALL 保留 `steps[:4]`，替换 `steps[4:]`；llm_client.generate SHALL 被调用 1 次

#### Scenario: LLM 失败 fallback

- **WHEN** llm_client.generate 抛异常
- **THEN** `replan` SHALL 返回原 plan 的副本，不抛；日志 SHALL 含 "replan_failed"

#### Scenario: interrupt_ctx 缺失新 key 时不崩

- **WHEN** caller 传入仅含 trigger_event + recent_memories + current_time 的旧 schema interrupt_ctx
- **THEN** `replan` SHALL 不抛异常；prompt 中缺失的 block（current_step / nearby_agents）SHALL 整块省略，不显示"无 / 空"占位


### Requirement: Planner LLM I/O 使用轻量格式 + 容忍自由词汇

`Planner` SHALL 使用 XML（或同等轻量结构化格式）作为 LLM I/O 形态——
不强制 LLM 输出严格 JSON 与 Literal enum；解析层 SHALL 容忍自由 action /
social_intent 措辞，通过同义词映射归一化到 canonical PlanAction /
SocialIntent。

设计意图（见 `lightweight-llm-format` change design D1-D5）：
- LLM（特别是小模型如 Gemini Flash）在严格 JSON + 多 Literal 下输出
  失败率高
- Cross-model audit（`validation-strategy` Part II）需要保留模型间语言
  差异；schema enum 强制会抹平
- PlanStep 的 PlanAction / SocialIntent 仍是 dispatch 工程契约；canonical
  词表不变；只是**允许 LLM 用自由词汇 + post-hoc 映射**

具体要求：

1. Prompt 输出格式 SHALL 使用 XML 标签结构（如 `<plan><step><time>.../>...
   </step></plan>`）；MUST NOT 要求严格 JSON + Literal enum
2. Parser SHALL 用 stdlib `xml.etree.ElementTree`，无新依赖
3. 解析失败 / 字段缺失 / 未知子元素 SHALL 容忍（与现有 `_parse_plan` 失败
   = 空 list 语义一致）；MUST NOT 抛异常
4. action 字段 SHALL 容忍自由文本（如 `visit` / `work` / `go_home`）；
   通过手写同义词字典映射到 canonical PlanAction（`move` / `stay` /
   `interact` / `explore`）；未知词 → fallback `stay` + `logger.debug`
   记录原始词
5. social_intent 字段 SHALL 容忍自由文本；同上映射到 canonical SocialIntent
   （`alone` / `open_to_chat` / `seeking_company`）
6. LLM 原始 action 措辞 SHALL 保留到 `PlanStep.activity`（若 LLM 未显式
   提供 `<activity>` 时）；保留信息供未来 cross-model audit
7. PlanStep / DailyPlan / Planner 公共 API 契约 MUST NOT 改变

#### Scenario: XML 输出被正确解析
- **WHEN** LLM 返回 `<plan><step><time>8:00</time><destination>cafe</destination><action>move</action><duration>30</duration><social>alone</social></step></plan>`
- **THEN** `Planner._parse_xml_plan` SHALL 返回 1 条 PlanStep，
  `time="8:00"` / `destination="cafe"` / `action="move"` / `social_intent="alone"`

#### Scenario: 自由 action 词汇通过同义词映射
- **WHEN** LLM 返回 `<step>...<action>visit cafe to find note</action>...</step>`
- **THEN** PlanStep.action SHALL == `"move"`（visit → move 同义映射）；
  `PlanStep.activity` SHALL 含 `"visit cafe to find note"` 或 LLM 提供的
  `<activity>` 文本

#### Scenario: 未知 action 词 fallback
- **WHEN** LLM 返回 `<step>...<action>flying</action>...</step>`
  （flying 不在同义词表里）
- **THEN** PlanStep.action SHALL == `"stay"`（fallback）；
  Logger SHALL 输出 debug 级 "unknown action token: flying"

#### Scenario: 缺失字段优雅 degrade
- **WHEN** LLM 返回 `<step><time>9:00</time><action>move</action></step>`
  （缺 destination / duration / social / activity）
- **THEN** PlanStep SHALL 构造成功；destination=None；duration_minutes=30
  （默认）；social_intent="alone"（默认）；activity="" 或 action 文本

#### Scenario: 完全无效输出 fallback
- **WHEN** LLM 返回纯文本 `"sorry, I cannot help"`（无 XML）
- **THEN** parser SHALL 返回空 list；`Planner.generate_daily_plan` 返回
  空 steps DailyPlan；`Planner.replan` 返回 current_plan 的副本（与现有
  失败语义一致）

#### Scenario: 公共契约保持不变
- **WHEN** Planner.generate_daily_plan / Planner.replan 被调用，无论 LLM
  输出何种格式（成功 / 失败 / 自由词）
- **THEN** 返回值 SHALL 仍是合法 DailyPlan；包含 0+ 个 PlanStep；每个
  PlanStep 的 `action` 字段 SHALL 为 PlanAction Literal 之一（4 类）；
  `social_intent` SHALL 为 SocialIntent Literal 之一（3 类）


### Requirement: 同义词映射不在 spec 层面写死

同义词映射表（如 `visit → move` / `work → stay`）SHALL 作为 implementation
detail 存在 `synthetic_socio_wind_tunnel/agent/planner.py` 内部；spec 不
枚举具体映射，只规定行为：必须支持映射、未知 → fallback、原始措辞保留。

未来增删映射条目 MUST NOT 触发 spec 改动；属代码迭代级别。

#### Scenario: 同义词表迭代不破契约
- **WHEN** 团队向同义词表新增 `"jog" → "move"`
- **THEN** spec MUST NOT 要求修改；只需更新 `_ACTION_SYNONYMS` dict +
  对应单元测试覆盖


### Requirement: AgentProfile 含 gender 字段

`AgentProfile` SHALL 含 `gender: Literal["male","female","non_binary"] | None = None`
字段；`PopulationProfile` SHALL 含 `gender_distribution: Mapping[Gender, float]`
（默认 `{"male":0.487,"female":0.513,"non_binary":0.0}`）；
`sample_population` SHALL 按分布给每个 agent 采样 gender。

设计意图：ABS Census 2021 6 维校准要求 gender 为可观察字段；缺它无法做
strict 6/6 acceptance，且 stereotype-audit 的 gender-swap 协议依赖此字段。

本 change MUST NOT 级联修改 name generator 与 Planner prompt（name-gender
一致性 / 代词使用）—— defer 到 stereotype-audit 或独立 gender-aware-naming
change（见 design Open Q5）。

#### Scenario: sample_population 给每个 agent 写 gender
- **WHEN** 调用 `sample_population(LANE_COVE_PROFILE, seed=42)`
- **THEN** 返回的所有 AgentProfile SHALL 含非 None 的 `gender` 值，
  ∈ {"male","female","non_binary"}

#### Scenario: gender_distribution 验证和=1
- **WHEN** PopulationProfile 构造时 `gender_distribution={"male":0.5,"female":0.4}`
  （和=0.9）
- **THEN** Pydantic SHALL 抛 ValidationError（与现有其它 distribution
  validator 一致）


### Requirement: LANE_COVE_PROFILE 校准至 ABS Census 2021

LANE_COVE_PROFILE 6 维分布 SHALL 校准至 ABS Census 2021 Lane Cove SA2
数据；从 `sample_population(LANE_COVE_PROFILE, n=1000)` 采样的统计分布与
真实人口距离 SHALL 通过 best-effort acceptance（≥ 4/6 维度 p > 0.10）。

校准维度：
1. age（5 岁分组）
2. gender（male/female）
3. housing_tenure（own / mortgage / rent / public）
4. income_tier（low / mid / high）
5. ethnicity_group（按 ancestry 聚合）
6. work_mode（commute / remote / shift / not_working）

距离指标：
- 离散字段：`scipy.stats.chi2_contingency`
- 连续字段：`scipy.stats.kstest`

#### Scenario: 6 维分布对照 ABS Census
- **WHEN** 调用 `sample_population(LANE_COVE_PROFILE, seed=42, n=1000)` 后
  通过 `compute_population_distance(samples, abs_data)` 计算
- **THEN** 返回 dict 含 6 个 dimension key，每个 value 是 p 值；至少 4 个
  p > 0.10

#### Scenario: 报告显式 disclose 未通过维度
- **WHEN** best-effort 通过（4/6 或 5/6）、有维度未达 strict
- **THEN** `assess_population_calibration` 返回 dict 含 `passed: True`、
  `acceptance_level: "best-effort"`、`failed_dimensions: list[str]`；
  publishable suite report SHALL 在 calibration section 列出未通过维度

#### Scenario: strict 通过状态可探测
- **WHEN** 6 个维度全部 p > 0.10
- **THEN** `assess_population_calibration` 返回 `acceptance_level: "strict"`


### Requirement: scripted_plan 三模式（commute / errand / leisure）

非主角 agent（Haiku tier）的脚本化日程 SHALL 按 `profile.work_mode` 分派
为四类 day-shape（commute / remote / shift / not_working），每类内部
SHALL 至少含三类活动 step：commute、errand、leisure。

时间锚点 SHALL 来自 ABS Travel Survey 2021 Sydney（journey-to-work
departure-time 分布）；errand 与 leisure 目的地 SHALL 按 Popular Times
hourly 热度做加权采样。

`build_scripted_plan(profile, destinations, date, rng)` 公共签名 MUST NOT
改变；位置 SHALL 在 `synthetic_socio_wind_tunnel.agent.scripted_plan` 模块
（不再在 `tools/smoke_experiment_demo.py`）。

#### Scenario: commute work_mode 含通勤往返 + errand
- **WHEN** profile.work_mode == "commute"
- **THEN** 返回的 DailyPlan SHALL 含至少 2 个 commute step（home →
  workplace 与 workplace → home）+ ≥ 1 个 errand step（去超市 / 接娃 /
  办事）+ ≥ 1 个 leisure step

#### Scenario: not_working work_mode 无通勤
- **WHEN** profile.work_mode == "not_working"
- **THEN** 返回的 DailyPlan SHALL 不含 commute step；errand / leisure
  step 占满白天

#### Scenario: 公共签名向后兼容
- **WHEN** 既有调用 `build_scripted_plan(profile, destinations, date, rng)`
- **THEN** 调用 SHALL 不抛；返回有效 DailyPlan；`tools/run_variant_suite.py`、
  `tools/run_multi_day_experiment.py`、`tools/replan_trace.py` import
  路径 SHALL 全部指向 `synthetic_socio_wind_tunnel.agent.scripted_plan`


### Requirement: 行为校准至 ABS Travel Survey + Popular Times

baseline 14d × 1000 agent sim 的行为分布 SHALL 通过 best-effort 行为
acceptance：
- OD 矩阵 chi² p > 0.05（对照 ABS Travel Survey Sydney 2021 SA2 → SA2）
- ≥ 70% top-20 POI 的 hourly visit EMD < 0.25（对照 Popular Times 数据）

距离指标：
- OD：`scipy.stats.chi2_contingency`（2D 矩阵）
- Popular Times：`scipy.stats.wasserstein_distance`（per-POI 24h × 7d）

#### Scenario: OD 矩阵对照
- **WHEN** baseline sim 跑完后通过 `compute_od_chi_squared(sim_OD, abs_OD)`
- **THEN** 返回 p 值；best-effort 通过要求 p > 0.05

#### Scenario: Popular Times EMD per POI
- **WHEN** baseline sim 14d 跑完，对每个 top-20 POI 调
  `compute_popular_times_emd(sim_visits, popular_times_data)`
- **THEN** 返回 `dict[poi_id, float]`；best-effort 通过要求 ≥ 70%
  POI 的 EMD < 0.25


### Requirement: calibration 模块独立于 hot path

`synthetic_socio_wind_tunnel.agent.calibration` 模块 SHALL 独立提供
calibration helpers，不被 sim runtime / Planner / AgentRuntime 调用；
sim hot path MUST NOT 包含 calibration 计算（chi² / KS / EMD）。

`tools/run_calibration.py` SHALL 是唯一的 CLI 入口；它跑出的报告（JSON）
SHALL 持久化到 `data/calibration/calibration_report.json`，由 publishable
suite report 链接而非重算。

#### Scenario: hot path 无 calibration import
- **WHEN** 检查 `synthetic_socio_wind_tunnel/agent/runtime.py`、
  `synthetic_socio_wind_tunnel/agent/planner.py` 的 import 列表
- **THEN** 都 SHALL NOT 含 `from .calibration import` 或 `import scipy`

#### Scenario: calibration report 是 sim suite 的输入而非输出
- **WHEN** `tools/run_variant_suite.py` 写最终 report.md 的 calibration
  section
- **THEN** 它 SHALL 读 `data/calibration/calibration_report.json`，
  MUST NOT 重新计算 chi²/KS/EMD


### Requirement: calibration 数据源 ship 在仓库

`data/calibration/` 目录 SHALL 含三份静态 JSON：

1. `abs_census_lanecove_2021.json` — ABS Census 2021 Lane Cove SA2 6 维分布
2. `abs_travel_survey_sydney_2021.json` — ABS Travel Survey OD + 时间分布
3. `lanecove_popular_times.json` — top-20 POI 24h × 7d schedule（Outscraper
   抓取后的快照）

每份 SHALL 含 source URL、download date、schema 版本字段；变更原始数据
SHALL 通过重跑 fetch / 转换脚本（`tools/fetch_popular_times.py` 或一次性
ABS 转换 helper），MUST NOT 直接手编 JSON。

#### Scenario: 数据来源可追溯
- **WHEN** 任意 calibration JSON 被 load
- **THEN** 顶层 dict SHALL 含 `source: str`、`downloaded: str` (ISO date)
  字段；`docs/calibration/01-data-sources.md` SHALL 含对应的下载 URL
  + 字段映射规则


### Requirement: AgentProfile 含 thesis-direct 维度字段

`AgentProfile` SHALL 含以下 13 个 `Literal[...] | None = None` 字段，对应
ABS Census 2021 的 thesis-relevant 维度。所有字段 default `None`，向后兼容
存量代码。

**Tier 1（thesis 核心，5 字段）**：
- `community_tenure_5yr` — `Literal["new_<1yr","recent_1_5yr","established_5plus"]` (G45)
- `unpaid_child_care_hours` — `Literal["none","1_14","15_29","30plus"]` (G26)
- `unpaid_domestic_hours` — `Literal["none","1_14","15_29","30plus"]` (G24)
- `unpaid_disability_care_hours` — `Literal["none","yes"]` (G25)
- `volunteer_status` — `Literal["volunteer","non_volunteer"]` (G23)

**Tier 2（精化现有，5 字段）**：
- `english_proficiency` — `Literal["very_well","well","not_well","not_at_all","english_only"]` (G13)
- `family_composition` — `Literal["lone_person","couple_no_kids","couple_kids_under_15","couple_kids_15plus","one_parent_family","group_household","other"]` (G27/G29)
- `dwelling_structure` — `Literal["separate_house","semi_detached","flat_apartment","other_dwelling"]` (G36)
- `vehicles_at_dwelling` — `Literal["0","1","2","3plus"]` (G34)
- `year_of_arrival_bucket` — `Literal["pre_2000","2000_2010","2011_2015","2016_2021","australian_born"]` (G10)

**Tier 3（完整性，3 字段）**：
- `indigenous_status` — `Literal["indigenous","non_indigenous"]` (G07)
- `disability_status` — `Literal["needs_assistance","no_assistance"]` (G18)
- `education_level` — `Literal["postgrad","bachelor","diploma","year_12","year_11_or_below","no_qualification"]` (G16+G49)

设计意图（见 `agent-profile-enrich` change design D1-D7）：让 sim 区分
*rooted* vs *floating* agent，支持 hyperlocal-push 在不同人群上效果差异
的 rival hypothesis。

#### Scenario: 存量代码无新字段不报错
- **WHEN** 既有 `AgentProfile(agent_id=..., name=..., age=..., occupation=...,
  household=..., home_location=...)` 调用
- **THEN** SHALL 不抛；新字段全为 None；公共 API 兼容

#### Scenario: 字段类型严格
- **WHEN** 构造 `AgentProfile(community_tenure_5yr="brand_new")`（非 Literal 值）
- **THEN** Pydantic SHALL 抛 ValidationError


### Requirement: PopulationProfile 含 13 个新 distribution

`PopulationProfile` SHALL 含 13 个 distribution 字段对应 AgentProfile 新字段，
default 为 ABS-derived 值或合理 fallback；MUST 通过现有 `_dist_sum_to_one`
validator。

`sample_population` SHALL 给每个 agent 用 `_weighted_pick` 从对应 distribution
采样新字段；分布为空（默认空 dict）时字段保持 `None`。

#### Scenario: sample_population 写新字段
- **WHEN** 调用 `sample_population(LANE_COVE_PROFILE, seed=42)`
- **THEN** 返回的所有 AgentProfile SHALL 含 13 新字段的非 None 值（前提
  LANE_COVE_PROFILE 已配置所有 13 distribution）

#### Scenario: 缺 distribution 字段保持 None
- **WHEN** PopulationProfile 不配置 `disability_status_distribution`
- **THEN** 采样产生的 agent.disability_status SHALL == None；其它已配置
  字段不受影响


### Requirement: family_composition 与 household 自动映射

`sample_population` SHALL 优先按 `family_composition_distribution` 采样
agent.family_composition，再用以下映射回填 agent.household：
- `lone_person` → `single`
- `couple_no_kids` / `couple_kids_15plus` → `couple`
- `couple_kids_under_15` / `one_parent_family` → `family_with_kids`
- `group_household` / `other` → `single`

household 字段公共类型 MUST NOT 改变（保持 3-bucket Literal）；现有依赖
`agent.household` 的代码 MUST 继续工作。

#### Scenario: family_composition → household 映射一致
- **WHEN** sample_population 给 agent.family_composition 写入
  `couple_kids_under_15`
- **THEN** 同一 agent.household SHALL == `family_with_kids`

#### Scenario: 缺 family_composition_distribution 的回退
- **WHEN** PopulationProfile 没配置 `family_composition_distribution` 但有
  `household_distribution`
- **THEN** sample_population SHALL 用 household_distribution 采样；
  agent.family_composition 保持 None；agent.household 仍按当前逻辑赋值


### Requirement: calibration 评估新维度递进式

`assess_population_calibration` SHALL 按 Tier 评估：
- **Tier 1（核心 6 维 + 新 5 维）**：现有 6 维 ≥ 4 通过 **AND** Tier 1 新 5 维
  ≥ 3 通过 → best-effort
- **Strict**：现有 6 维全过 **AND** Tier 1 新 5 维全过 **AND** Tier 2 新 5 维
  ≥ 3 通过

Tier 3 字段（indigenous / disability / education）状态 SHALL 出现在 disclosure
段，但 MUST NOT 阻塞 acceptance_level 升级。

`compute_population_distance` SHALL 自动覆盖 abs_data["distributions"] 里所有
key，不限于原 6 维。

#### Scenario: 新 Tier 1 5 维全过升级 strict
- **WHEN** 现有 6 维全 p > 0.10 + Tier 1 新 5 维全 p > 0.10 + Tier 2 5 维有
  3 个 p > 0.10
- **THEN** acceptance_level SHALL == "strict"

#### Scenario: Tier 3 失败不阻塞 best-effort
- **WHEN** 现有 6 维 4 过 + Tier 1 5 维 3 过 + Tier 3 全失败
- **THEN** acceptance_level SHALL == "best-effort"；report SHALL 在
  disclosure 段列出 Tier 3 failed dims


### Requirement: convert_abs_census.py 含 `--full` flag

`tools/convert_abs_census.py` SHALL 接受 `--full` flag：
- 不带：输出原 6 维 distribution（agent-calibration 行为）
- 带：输出原 6 维 + 13 新维度 distribution；JSON 顶层 `distributions` 字段
  不删 6 维原 key，只新增

#### Scenario: --full 输出 19 维
- **WHEN** 跑 `python3 tools/convert_abs_census.py --full`
- **THEN** 输出 JSON 的 `distributions` SHALL 含 19 个 key（age, gender,
  housing_tenure, income_tier, ethnicity_group, work_mode + 13 new）

#### Scenario: 不带 --full 输出 6 维
- **WHEN** 跑 `python3 tools/convert_abs_census.py`（无 flag）
- **THEN** 输出 JSON 的 `distributions` SHALL 仅含原 6 个 key（向后兼容）


### Requirement: stereotype audit module 提供 swap / blind / distance helpers

`synthetic_socio_wind_tunnel/agent/audit.py` SHALL 提供以下纯函数 helpers，
独立于 sim runtime（不被 hot path 调用）：

1. `swap_profile_attribute(profile: AgentProfile, attr: str, new_value) -> AgentProfile`
2. `blind_profile_attribute(profile: AgentProfile, attr: str) -> AgentProfile`
3. `compute_behavioral_distance(run_a, run_b) -> BehavioralDistance`
4. `assess_swap_acceptance(distance, *, mode: Literal["stub","real_llm"]) -> AuditStatus`
5. `assess_blind_acceptance(distance) -> AuditStatus`
6. `assess_cross_model_convergence(report_a: dict, report_b: dict) -> AuditStatus`

设计意图（见 `stereotype-audit` change design D1-D6）：把 validation-strategy
Part II 三协议从 doc 提升为可重复跑的 audit pipeline，作为 publishable
checklist #2 的硬门禁实施。

具体要求：

1. `swap_profile_attribute` SHALL 用 `profile.model_copy(update={attr: new_value}, deep=True)`
   返回新 profile；其它字段（name / personality / digital / 13 维 enrich
   字段）MUST NOT 改变
2. `blind_profile_attribute` SHALL 把指定字段置 None；其它字段保持
3. audit 模块 MUST NOT 被 `runtime.py` / `planner.py` / orchestrator hot
   path import；只被 `tools/run_stereotype_audit.py` 调用

#### Scenario: swap 隔离单变量
- **WHEN** 调用 `swap_profile_attribute(profile, attr="gender", new_value="female")`
  且 profile.gender 原为 "male"
- **THEN** 返回新 profile.gender == "female"；name / age / personality /
  housing_tenure / 13 enrich 字段 SHALL 与原 profile 完全一致

#### Scenario: blind 把字段置 None
- **WHEN** 调用 `blind_profile_attribute(profile, attr="ethnicity_group")`
  且 profile.ethnicity_group 原为 "China"
- **THEN** 返回新 profile.ethnicity_group is None；其它字段保持

#### Scenario: hot path 不导入 audit
- **WHEN** 检查 runtime.py / planner.py / orchestrator import 列表
- **THEN** 都 SHALL NOT 含 `from .audit import` 或 `import synthetic_socio_wind_tunnel.agent.audit`


### Requirement: stereotype audit CLI 单一入口

`tools/run_stereotype_audit.py` SHALL 是跑三协议的唯一 CLI 入口；输出
`data/calibration/stereotype_audit_report.json`。

CLI 接受 `--scale {dev|publishable}` flag：
- `dev`：stub-only，1 seed × 20 agent × 3 day（~10 s）；用于 CI / smoke
- `publishable`：要求 `--use-real-llm`，2 seed × 100 agent × 14 day
  （~30 min × $5-10）；用于真 publishable 报告

#### Scenario: dev mode stub-only
- **WHEN** `python3 tools/run_stereotype_audit.py --scale dev`
- **THEN** 不需 API key；执行时间 < 30 s；输出 JSON 含 swap_test /
  blind_test 段；cross_model_test SHALL 标 `state: "skipped (stub mode)"`

#### Scenario: publishable mode 要求 real LLM
- **WHEN** `python3 tools/run_stereotype_audit.py --scale publishable`
  无 `--use-real-llm`
- **THEN** SHALL sys.exit(2) + 诊断 message："publishable scale requires
  --use-real-llm"


### Requirement: audit report JSON schema

`data/calibration/stereotype_audit_report.json` SHALL 含以下顶层字段：

- `generated`：ISO 时间戳
- `scale`：`"dev"` 或 `"publishable"`
- `swap_test`：含 `passed: bool`、`axes: dict[axis_name → AxisResult]`
- `blind_test`：含 `passed: bool`、`destination_overlap_pct: float`
- `cross_model_test`：含 `passed: bool`、`models_compared: list[str]`、
  `evidence_alignment` 字段比对结果
- `overall_passed`：三协议全 pass 时 true

#### Scenario: report schema 完整
- **WHEN** publishable mode 跑完后读 stereotype_audit_report.json
- **THEN** 顶层 SHALL 含 generated / scale / swap_test / blind_test /
  cross_model_test / overall_passed 6 个字段；每个 *_test 子字段含
  passed: bool

#### Scenario: dev mode cross_model 标 skipped
- **WHEN** dev mode 跑完
- **THEN** report.cross_model_test.state SHALL == "skipped (stub mode)"；
  overall_passed SHALL 仍能基于其它两协议判定（dev mode 时 disclose
  cross_model 未跑）


### Requirement: AgentProfile 含 LifePattern 字段

`AgentProfile` SHALL 含 `life_pattern: LifePattern | None = None` 字段。
`LifePattern` 是 Pydantic model，包含 6 个字段记录 agent 14 天 sticky 的
"我的"routine 锚：

- `preferred_cafe: str | None`
- `preferred_leisure_park: str | None`
- `preferred_errand_destination: str | None`
- `morning_commute_minute: int`（0-59，hour window 内偏移）
- `evening_return_minute: int`（0-59）
- `weekend_outing_destination: str | None`

`sample_population` SHALL 给每个 agent 采样一份 LifePattern；同 seed 同输出
（reproducibility 不破）。LifePattern 采样 SHALL 优先选 home 附近的 POI（不
全城随机）。

#### Scenario: 同 seed 同 LifePattern
- **WHEN** 两次调用 `sample_population(LANE_COVE_PROFILE, seed=42)`
- **THEN** 每个 agent 的 `life_pattern.preferred_cafe` /
  `morning_commute_minute` 等字段 SHALL 完全相同

#### Scenario: 旧构造签名仍兼容
- **WHEN** 既有 `AgentProfile(agent_id=..., name=..., age=..., ...)` 调用
- **THEN** SHALL 不抛；`life_pattern` 默认 None；公共 API 兼容


### Requirement: scripted_plan 区分 weekday vs weekend

`build_scripted_plan(profile, destinations, date, rng)` SHALL 按
`date.weekday() < 5` 区分两套 day-shape：

- **Weekday**：现有 4 模式（commute/remote/shift/nonworking）保留 + 强化
- **Weekend**：新 `_weekend_day_shape` —— 无 commute；morning_at_home 长；
  上午 errand；下午 leisure；晚 family time；锚 weekend_outing_destination

#### Scenario: Saturday 不含 commute step
- **WHEN** `build_scripted_plan(profile, ..., date=2026-05-02, ...)`
  （周六），profile.work_mode == "commute"
- **THEN** 返回的 DailyPlan SHALL 不含 reason="commute" 的 step；
  SHALL 含 ≥ 1 个 leisure step

#### Scenario: weekday/weekend 总活跃差
- **WHEN** 跑 100 agent × 7 day baseline（混合 work_mode），weekday 5 天
  + weekend 2 天
- **THEN** weekday 平均每天 encounter ≥ weekend 平均每天 × 1.15


### Requirement: scripted_plan 读 8 个 profile 维度做 conditioning

`build_scripted_plan` SHALL 在 day-shape 生成时 condition 在以下 profile
字段（"每维 1-2 行 conditioning"原则；不重写主干）：

| 字段 | 影响 |
|---|---|
| `family_composition == "couple_kids_under_15"` | 必含 3pm school pickup step + 18:30 home anchor |
| `unpaid_child_care_hours ∈ {"15_29", "30plus"}` | errand 时段集中 9-15pm |
| `vehicles_at_dwelling == "0"` | commute step 加 transit via-point（lightweight） |
| `community_tenure_5yr == "new_<1yr"` | leisure venue 多样性 ↑（不锁 LifePattern） |
| `community_tenure_5yr == "established_5plus"` | LifePattern 锚强 |
| `english_proficiency ∈ {"not_well", "not_at_all"}` | leisure POI 偏好 own-language community POI（mild bias） |
| `personality.routine_adherence > 0.7` | LifePattern 用率 ≥ 80% |
| `personality.openness > 0.7` | leisure venue 多样化（不死锁单一 venue） |

#### Scenario: couple_kids_under_15 含 school pickup
- **WHEN** profile.family_composition == "couple_kids_under_15" 且 day 是
  weekday，build_scripted_plan 跑
- **THEN** DailyPlan SHALL 含一个 time ∈ ["14:30", "15:30"] 的 step；
  reason 或 activity 含 "school" / "pickup" / "kids"

#### Scenario: 0-car 通勤不含 driving
- **WHEN** profile.vehicles_at_dwelling == "0" 且 work_mode == "commute"
- **THEN** commute step SHALL 通过一个 transit via-point 或显示 "transit"
  reason；MUST NOT 直接 home → workplace（无 via）


### Requirement: LifePattern 通过 routine_adherence gated 锁定

scripted_plan 用 LifePattern.preferred_* 字段时 SHALL 由
`profile.personality.routine_adherence` 概率门控：

- routine_adherence > 0.7 → 80% 概率用 preferred_*
- routine_adherence 0.4-0.7 → 50% 概率
- routine_adherence < 0.4 → 20% 概率

agent 14 天保持 LifePattern 的"sticky"通过这门控随机性涌现：高坚持者大
多数天用同一 cafe；低坚持者每天换。

#### Scenario: 高 routine_adherence 14 天 cafe 重复
- **WHEN** 跑 100 agent × 14 day baseline，筛 routine_adherence > 0.7 的
  agents
- **THEN** ≥ 50% 的高坚持 agent 14 天里访问 LifePattern.preferred_cafe
  的次数 ≥ 8 天

#### Scenario: 低 routine_adherence 探索多
- **WHEN** 同样筛 routine_adherence < 0.4 的 agents
- **THEN** 14 天 unique leisure venue 数中位数 ≥ 4 个


### Requirement: Popular Times 加权采样（graceful fallback）

`scripted_plan._pick_destination` SHALL 接受 `current_hour: int | None`
参数。当 `data/calibration/lanecove_popular_times.json` 存在且 current_hour
非 None 时，destination 采样权重 SHALL 用 Popular Times 的当前小时热度。

JSON 不存在 / current_hour 为 None / POI 在 popular_times 里没记录 → fallback
均匀采样（不抛错）。

#### Scenario: 没数据时 fallback 均匀
- **WHEN** Popular Times JSON 不存在 / 不含某 POI
- **THEN** _pick_destination SHALL 均匀采样剩余 POI，跟当前行为完全一致

#### Scenario: 有数据时按热度加权
- **WHEN** lanecove_popular_times.json 已 ship，cafe_main 的周一 8am 热度
  90、cafe_secondary 周一 8am 热度 30
- **THEN** 在 current_hour=8 的多次 _pick_destination 调用中，cafe_main
  采样比例 SHOULD 显著高于 cafe_secondary（卡方 p < 0.05）


### Requirement: Realism CLI 输出量化指标

`tools/measure_group_alignment.py` SHALL 是衡量"agent 拟真度"的离线 CLI。
输入：suite directory（已跑过的 sim 输出）。输出：
`data/realism/<suite>_metrics.json` 含 F1 时空 + F3 routine 三组数字。

JSON 结构：
```jsonc
{
  "f1_temporal": {
    "morning_peak_ratio": float,
    "weekday_weekend_diff_pct": float,
    "popular_times_emd": float | null
  },
  "f3_routine": {
    "high_adherence_repeat_pct": float,
    "low_adherence_repeat_pct": float,
    "spearman_adherence_repeat": float
  },
  "stage1_passed": bool
}
```

`stage1_passed` 当全部以下成立时为 true：
- morning_peak_ratio > 1.5
- weekday_weekend_diff_pct > 0.15
- spearman_adherence_repeat > 0.5

#### Scenario: stage1 passed
- **WHEN** sim 数据满足三阈值
- **THEN** measure_group_alignment.py SHALL 输出 stage1_passed = true

#### Scenario: 没 Popular Times 数据
- **WHEN** lanecove_popular_times.json 不存在
- **THEN** popular_times_emd SHALL == null；stage1_passed 评估时不依赖
  此字段

---

<!-- Added by realism-attention-rebalance -->

### Requirement: Replan prompt 对称 context window

`Planner._build_replan_prompt` SHALL 装配的 prompt 满足**对称 context window** 约束——push 不被语言学特殊化为"打断者 / interrupt"，与其它 context 信号并列展示。

具体约束：

- prompt MUST NOT 包含字符串 "打断了你的计划" / "interrupted" / "interrupting" / "中断" 或任何把 push 描述为"打断者 / 紧急事件"的措辞。
- prompt SHALL 用统一的 markdown 标记（如 `【...】` 或同级别 `## ...` heading）展示以下 context blocks：
  - `【现在】` / `【正在做】` / `【周围】` / `【最近发生】` / `【手机】` / `【接下来计划】`
- 每个 block 在数据存在时显示；数据为空时**整块省略**（不显示"无" / "空" 占位文字）。
- 推送内容 SHALL 在 `【手机】` block 中展示，禁止在该 block 标题之外的任何位置重复 / 高亮 push 内容。
- 提问句 SHALL 中性（"综合以上信息你会改变接下来的计划吗？"），不带"由于这条紧急推送 / 这件事打断你"的偏向。

#### Scenario: prompt 不含打断措辞

- **WHEN** Planner._build_replan_prompt 接收完整 interrupt_ctx 装配 prompt
- **THEN** prompt 字符串 SHALL NOT 包含 "打断"、"interrupt"、"紧急"、"urgent" 等偏向词

#### Scenario: 五个对称 block 出现

- **WHEN** prompt 装配且 interrupt_ctx 五个 block 数据完整
- **THEN** prompt SHALL 同时含 `【现在】`、`【正在做】`、`【周围】`、`【最近发生】`、`【手机】`、`【接下来计划】` 6 个 block 标记

#### Scenario: 空 block 省略

- **WHEN** `nearby_agents = []`
- **THEN** prompt SHALL NOT 含 `【周围】` 标记（整块省略）；其它 block 不受影响

### Requirement: AgentRuntime.replan_decision_log

`AgentRuntime` SHALL 维护 `replan_decision_log: list[ReplanDecisionRecord]`，每次 `should_replan` 调用追加一条（无论返回 True 或 False）。

`ReplanDecisionRecord` 字段：

```
agent_id: str
tick: int
simulated_time: datetime
candidate_kind: str
candidate_urgency: float
threshold_computed: float
base_components: dict[str, float]   # personality 各维度的贡献
context_modifier: float
replan_count_today: int
rng_roll: float
decision: bool
```

- 决策日志 SHALL 仅在 dev / inspector 路径累积；publishable suite 30 seed × 14 day 跑动期间 SHALL 可关闭以避免内存膨胀（通过 `AgentRuntime.enable_replan_log: bool = False` 控制）。
- 每日开始 SHALL 重置 `replan_count_today = 0`。
- inspector payload 导出器（`tools/export_inspector_payload.py`）SHALL 把决策日志写入输出 JSON 的 `replan_decision_log` 顶层 key。

#### Scenario: 默认关闭

- **WHEN** AgentRuntime 默认构造
- **THEN** `enable_replan_log` SHALL 为 False；should_replan 调用 SHALL NOT 累积记录

#### Scenario: 启用时记录每次决策

- **WHEN** `runtime.enable_replan_log = True`，should_replan 被调用 5 次（3 True, 2 False）
- **THEN** `runtime.replan_decision_log` SHALL 含 5 条 record；其中 decision=True 的 SHALL 为 3 条

#### Scenario: 跨日重置 replan_count_today

- **WHEN** 一天内累计 4 次 replan，新一天 on_day_start 调用
- **THEN** `replan_count_today` SHALL 重置为 0

### Requirement: 触发率 goldilocks band

`Planner` + `AgentRuntime.should_replan` 联合 SHALL 在标准 hyperlocal_push variant 设定下使触发率落入合理区间。

合理区间：单 24 小时窗口内，在 hyperlocal_push variant 下，per-agent 平均 replan 触发率 SHALL ∈ **[5%, 15%]**（即每 100 次 should_replan 调用约 5-15 次返回 True）。

- 高于 15%：push 触发过强，疑似 prompt artifact，需收紧 base 系数。
- 低于 5%：push 几乎无效，需放松 base 系数。
- 该区间 SHALL 在 dev mode publishable suite（5 seeds × 7 days × hp variant）下作为回归断言被检查。

#### Scenario: dev suite 触发率在范围内

- **WHEN** 跑 5 seeds × 7 days × 100 agents × hyperlocal_push variant
- **THEN** 平均 per-agent-per-day replan 触发率 SHALL ∈ [5%, 15%]

#### Scenario: 触发率超出范围时 fitness audit 报警

- **WHEN** 触发率 = 25%（超 15%）
- **THEN** `fitness-audit` SHALL 产出一条 `attention_rebalance.replan_rate_out_of_band` warning

### Requirement: 个体异质响应（heterogeneity）

同一条 push 给 8 维 personality 不同的 100 个 agent 时，触发分布 SHALL 不为单峰。

- 用 100 个 agent 跑同一个 candidate（urgency=0.6, kind=notification）1000 次决策 → 把 should_replan 触发概率按 personality 主成分聚类
- SHALL 至少出现 3 个聚类组，触发概率分别为 low (<20%) / mid (30-50%) / high (>60%)
- low 组 SHALL 主要由 `routine_adherence > 0.7` + `openness < 0.3` 的 agent 组成
- high 组 SHALL 主要由 `curiosity > 0.7` + `openness > 0.7` 的 agent 组成

#### Scenario: 多峰分布出现

- **WHEN** 100 agent × 同一 candidate × 1000 rng seed 的触发概率聚类
- **THEN** SHALL 出现至少 3 个有显著差异的聚类（KL-divergence 或 silhouette score 满足 sklearn 默认阈值）
