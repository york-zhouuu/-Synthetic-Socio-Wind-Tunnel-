## Why

在准备 `memory` change 时发现一个广泛的反模式：**用 dict-of-strings
或自由字符串字段承载 behavior-driving state**。

两条具体伤痕：

1. **`AgentProfile.personality_traits: dict[str, float]`**
   通过 `profile.trait("curiosity", 0.5)` 访问，默认 0.5。
   - `sample_population`（Phase 1.5 引入）**根本没填这个 dict** → 所有
     1000 采样 agent 的 trait 永远是 0.5，行为完全同质
   - 访问点散落：`runtime.build_observer_context` 读 `"perception"`/
     `"curiosity"`；memory 的 `should_replan` 计划读 `"routine_adherence"`
     / `"curiosity"`
   - typo 永不报错（"currosity" 拿到默认 0.5，跟正确写法一样）
   - 没有 IDE 自动补全 / 类型检查 / "哪些 trait 被读过"的可追溯性

2. **`PlanStep.action: str`**
   LLM 生成的字段，约定值是 `"move" / "stay" / "interact" / "explore"`。
   - `AgentRuntime.step()` 用 `if current.action == "move"` 判断分支
   - 若 LLM 吐出 `"moves"` / `"walk"` / `"移动"`：**静默走 else 分支**
     → agent 变 WaitIntent → 一整天原地不动 → 无日志无异常
   - 相关字段 `social_intent / household` 同病

第二个伤痕和第一个是同一哲学问题的两种表现——**behavior-driving state
应当是类型系统的公民，不是字符串 dict / 自由 str**。既然要改，一次改
齐，而不是每个 Phase 2 change 各自绕。

## What Changes

### 1. `PersonalityTraits` 替换 dict（MODIFIED）

新增 `synthetic_socio_wind_tunnel/agent/personality.py`：

```python
class PersonalityTraits(BaseModel):
    # OCEAN 五因素（学术惯例）
    openness: float = 0.5
    conscientiousness: float = 0.5
    extraversion: float = 0.5
    agreeableness: float = 0.5
    neuroticism: float = 0.5

    # 本项目 thesis 特别需要的维度
    curiosity: float = 0.5          # 对新鲜事物的吸引（用于 replan）
    routine_adherence: float = 0.5  # 对固定日程的坚持（用于 replan）
    risk_tolerance: float = 0.5     # 冒险 / 接受陌生人（未来 policy-hack 用）

    model_config = {"frozen": True}
```

- 所有字段 `[0, 1]`，`frozen`，可哈希。
- `AgentProfile.personality_traits: dict[str, float]` → `AgentProfile.personality: PersonalityTraits`。
- **移除** `AgentProfile.trait(name, default)` 便利方法；访问改为
  `profile.personality.curiosity`。
- **移除** `AgentProfile.personality_description: str`——合并到
  `AgentProfile.summary: str`（或同级自由描述字段），以名称不和"数据"混淆。

### 2. `Skills` + `EmotionalState` 替换 dict（MODIFIED）

```python
class Skills(BaseModel):
    perception: float = 0.5
    investigation: float = 0.5
    stealth: float = 0.5  # Phase 1 遗留；暂不删

class EmotionalState(BaseModel):
    guilt: float = 0.0
    anxiety: float = 0.0
    curiosity: float = 0.0  # 与 PersonalityTraits.curiosity 不同：这是
                             # "当下感受"，trait 是"稳定倾向"
    fear: float = 0.0
```

- 替换 `ObserverContext.skills: dict` 和 `emotional_state: dict`
- 便利属性 `investigation_skill / perception_skill / guilt_level /
  anxiety_level` 保留（现在从 typed 字段读）

### 3. `PlanStep` 的 Literal 化（MODIFIED）

```python
PlanAction = Literal["move", "stay", "interact", "explore"]
SocialIntent = Literal["alone", "open_to_chat", "seeking_company"]
Household = Literal["single", "couple", "family_with_kids"]

class PlanStep(BaseModel):
    action: PlanAction
    social_intent: SocialIntent = "alone"
    ...

class AgentProfile(BaseModel):
    household: Household
    ...
```

- LLM 吐错拼写 → Pydantic 解析 JSON 时立即 `ValidationError`
- `Planner._parse_plan_response` 捕获 ValidationError 记日志并返回空 plan
  （现有 fallback 语义）

### 4. `sample_population` 填充 PersonalityTraits（MODIFIED）

`PopulationProfile` 新增 `personality_distribution: PersonalityDistribution`，
定义每个 trait 的采样分布（均值 + 标准差，或 beta 分布参数）。

`sample_population` 为每个 agent 实例化 `PersonalityTraits`：每个维度
独立高斯采样，clamp 到 [0, 1]。默认分布：全维度 `N(0.5, 0.2)`。

`LANE_COVE_PROFILE` 用上默认分布；任何 `profile.personality.curiosity`
在 1000 样本上自然有异质性。

### 5. Planner prompt 引用 typed 字段（MODIFIED）

`_PLAN_PROMPT_TEMPLATE` 里 `{personality_description}` 替换为：

```
人格特征：
- 开放性：{openness:.1f}
- 好奇心：{curiosity:.1f}
- 日常坚持：{routine_adherence:.1f}
- ...
```

让 LLM 直接看数值而不是凭自由描述猜。

### 6. Non-goals

- **不**动 C 类自由字符串：`interests / languages / ethnicity_group` 保持
  现状（文档约定够用）
- **不**做 `perception/models.py::AgentProfile`（另一个同名类的）改造。
  那个类有 demographic 字段（age_group / class_background / income_level
  / home_side）是同款反模式，但它与 `agent/profile.py::AgentProfile` 重名
  已经很乱了——**重命名 + 清理是独立 change**，本 change 只改真正的
  `agent/profile.py::AgentProfile`
- **不**改 `Atlas.plot_tags / MemoryEvent.tags`：atlas 的是语义标签
  （开放集合合理）；memory 的 tags 改造在 memory change 自己处理
- **不**引入 domain-specific trait（例如"digital_literacy"）：先稳定 8 维
  标配，下一个 change 再叠加

## Capabilities

### New Capabilities
无（本 change 是重构 + typing 强化，不新增能力）

### Modified Capabilities
- `agent`: `AgentProfile` / `DailyPlan`（通过 PlanStep） 的字段类型变化；
  `personality_traits` dict 替换为 `personality: PersonalityTraits`；
  `PlanStep.action` / `social_intent` / `household` 成为 Literal；
  新增 `PersonalityTraits / Skills / EmotionalState` 值对象。
- `perception`: `ObserverContext.skills` / `emotional_state` 从 dict 改为
  typed 模型。

## Impact

### 受影响代码
- `synthetic_socio_wind_tunnel/agent/personality.py`（新）—
  `PersonalityTraits` / `Skills` / `EmotionalState`
- `synthetic_socio_wind_tunnel/agent/profile.py` — 字段替换 +
  household Literal
- `synthetic_socio_wind_tunnel/agent/planner.py` — PlanStep Literal +
  prompt 模板
- `synthetic_socio_wind_tunnel/agent/population.py` — 填 PersonalityTraits
- `synthetic_socio_wind_tunnel/agent/runtime.py` — 读 typed
- `synthetic_socio_wind_tunnel/perception/models.py` — ObserverContext
  dict → typed
- `synthetic_socio_wind_tunnel/perception/filters/*` — 读 typed 字段
- `synthetic_socio_wind_tunnel/perception/pipeline.py` — 便利属性访问
- `synthetic_socio_wind_tunnel/__init__.py` — re-export 新模型
- 所有构造 AgentProfile / ObserverContext 的测试 — 对应修改
- `memory` change 的 design.md D7 与 spec — archive 前不动，等本 change
  archive 后回去修（已在 typed-personality 的 tasks.md 记录）

### 不受影响（保持兼容）
- Atlas / Ledger / Simulation / Navigation / Collapse / Cartography /
  MapService / AttentionChannel / FitnessAudit / Orchestrator 的已冻结
  Requirement
- 已归档 change 与 Phase 1 所有测试（测试代码会改，Scenario 语义不变）

### 依赖变化
- 无新依赖。纯 Pydantic 字段 + Literal 类型。

### 风险
- **全面的 profile 构造迁移**：所有 `AgentProfile(...)` 的调用点（production
  + tests）都要迁。fitness-audit / agent_phase1 / observer_context_digital
  等测试都要走一遍。
- **向后兼容**：`profile.trait(name, default)` 被移除是 BREAKING。但当前
  没有外部消费者（单仓项目），接受。

### 预期成果
- `sample_population(LANE_COVE_PROFILE)` 出来的 1000 agent 的
  `personality.curiosity` 分布的标准差 ≥ 0.15（当前是 0——全是 0.5）
- orchestrator 跑一天，若某 agent 的 plan JSON 里 action 字段拼错，
  `Planner._parse_plan_response` SHALL 立即失败并记日志，而不是静默
  产生全 WaitIntent 的 agent
- `memory` change 的 `should_replan` 在本 change archive 后 SHALL 改为
  读 `profile.personality.routine_adherence` typed 字段，`memory` change
  的 design.md D7 对应 update
