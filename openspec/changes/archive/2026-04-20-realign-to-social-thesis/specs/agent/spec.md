# agent — 能力增量

## ADDED Requirements

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
