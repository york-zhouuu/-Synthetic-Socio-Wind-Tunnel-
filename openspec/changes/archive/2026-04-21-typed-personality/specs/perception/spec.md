# perception — 能力增量

## ADDED Requirements

### Requirement: ObserverContext 使用 typed Skills / EmotionalState

`perception.models.ObserverContext` SHALL：

- 移除字段 `skills: dict[str, float]`
- 移除字段 `emotional_state: dict[str, float]`
- 新增字段 `skills: Skills = Field(default_factory=Skills)`
- 新增字段 `emotional_state: EmotionalState = Field(default_factory=EmotionalState)`

`Skills` / `EmotionalState` 从 `synthetic_socio_wind_tunnel.agent.personality`
导入。

- 便利 property `investigation_skill` / `perception_skill` / `guilt_level`
  / `anxiety_level` 保留，内部改为从 typed 字段读
  （`self.skills.investigation` / `self.emotional_state.guilt` 等）。
- 现有 `get_skill(name, default)` / `get_emotion(name, default)` 方法
  SHALL 移除（同属于 dict 反模式的接口）。所有调用点改为 typed 访问。

#### Scenario: 默认构造
- **WHEN** `ObserverContext(entity_id=..., position=..., location_id=...)`
- **THEN** `ctx.skills` SHALL 是默认 Skills（全 0.5）；`ctx.emotional_state`
  是默认 EmotionalState（全 0.0）

#### Scenario: 便利 property 从 typed 字段读
- **WHEN** 构造 `ObserverContext(..., skills=Skills(investigation=0.8))`
- **THEN** `ctx.investigation_skill` SHALL 返回 `0.8`

#### Scenario: 旧 dict 接口移除
- **WHEN** 调用 `ctx.get_skill("investigation")` 或 `ctx.skills["investigation"]`
- **THEN** SHALL 分别抛 AttributeError / TypeError（dict 方法在 Skills 模型上不可用）

### Requirement: perception.filters 读 typed 字段

`perception/filters/*` SHALL 通过 typed 字段访问 observer state：

- skill filter 从 `ctx.skills.investigation` / `.perception` 读
- 任何需要情绪值的过滤 / 解释代码从 `ctx.emotional_state.guilt` /
  `.anxiety` 等读
- MUST NOT 保留 `ctx.skills.get(...)` 或 `ctx.emotional_state.get(...)`
  这类 dict-style 调用

#### Scenario: skill filter 仍按阈值工作
- **WHEN** 构造 agent 的 `Skills(investigation=0.3)`，查一个
  `discovery_skill=0.6` 的隐藏 item
- **THEN** 行为与本 change 之前一致（不发现）；底层代码路径使用
  typed 访问
