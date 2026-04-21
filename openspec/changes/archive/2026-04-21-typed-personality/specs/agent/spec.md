# agent — 能力增量

## ADDED Requirements

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
