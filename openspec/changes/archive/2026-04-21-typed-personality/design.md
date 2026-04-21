## Context

现状：`AgentProfile.personality_traits: dict[str, float]` + 便利方法
`profile.trait(name, default=0.5)` 承载所有"好奇心 / 外向性 / 日常坚持"
等关键行为参数。并且：

- `sample_population` 从未填充这个 dict
- 所有使用点（runtime / memory / 未来 planner）都走默认 0.5
- 无类型系统约束、无 typo 检测、无可追溯性

同款问题出现在 PlanStep 的字符串字段（`action` / `social_intent`），
LLM 吐错字母会静默分支错分。

本 change 把这两个反模式**一次性**修掉，为 memory 铺路。

## Goals / Non-Goals

**Goals:**
- 把 behavior-driving state 从 dict/str 提升为 Pydantic typed model
- 让 typos / 缺失 trait / LLM 拼写错误在**解析时**暴露（而非运行时静默）
- `sample_population` 能真正 populate 异质人格
- Planner prompt 直接引用数值而非自由描述

**Non-Goals:**
- 重命名 / 合并 `perception/models.py::AgentProfile`（名字冲突 + 字段
  重叠是另一个 change）
- 引入行业标准人格量表（IPIP, Big Five Inventory 等）的字符串压缩；
  只用 8 个维度的 float
- 性格 → 行为的"因果系数"做实证校准
- 引入 `personality_distribution` 的精细化（beta / 多峰 / 相关性矩阵），
  先用独立高斯

## Decisions

### D1: 8 个人格维度而不是 5

OCEAN 5 因素是心理学标配，但本项目 thesis 涉及 "agent 愿不愿意对推送/
陌生人/新空间做反应"。以下三个额外维度是必需的：

- `curiosity`：对"新鲜 / 偏离日常 / 意外信息"的吸引
- `routine_adherence`：对固定计划的坚持度（memory 的 should_replan 的
  核心变量）
- `risk_tolerance`：对"陌生人 / 未知空间 / 低置信任务"的接受（未来
  policy-hack / conversation change 的主力）

openness 和 curiosity 看起来冗余，但学术上 openness 偏"对艺术 / 抽象 /
新想法"，curiosity 偏"对具体新鲜事件"。thesis 实验里 curiosity 更直接。

8 个维度够用，再加会稀释；后续 change 可以追加。

### D2: PersonalityTraits 为 frozen Pydantic 模型

不用 dataclass 是因为：

- Pydantic 自带字段级验证（`ge=0.0, le=1.0`）
- `model_copy(update=...)` 让"修一个维度"方便
- 与项目其它模型（AttentionState / FeedItem / ...）风格统一

```python
class PersonalityTraits(BaseModel):
    model_config = {"frozen": True}
    openness: float = Field(default=0.5, ge=0.0, le=1.0)
    conscientiousness: float = Field(default=0.5, ge=0.0, le=1.0)
    extraversion: float = Field(default=0.5, ge=0.0, le=1.0)
    agreeableness: float = Field(default=0.5, ge=0.0, le=1.0)
    neuroticism: float = Field(default=0.5, ge=0.0, le=1.0)
    curiosity: float = Field(default=0.5, ge=0.0, le=1.0)
    routine_adherence: float = Field(default=0.5, ge=0.0, le=1.0)
    risk_tolerance: float = Field(default=0.5, ge=0.0, le=1.0)
```

### D3: Skills / EmotionalState 为独立模型

虽然都是 float 集合，但语义不同：
- Skills: 稳定能力（观察 / 调查 / 潜行）
- EmotionalState: 当下感受（内疚 / 焦虑 / 恐惧 / 当下好奇）

独立模型让日后扩展字段时互不干扰（Skills 加 `social_savvy`，
EmotionalState 加 `loneliness` 等）。

Curiosity 同时出现在 trait 和 emotion 是**有意**的：
- `profile.personality.curiosity` = 稳定倾向
- `observer_ctx.emotional_state.curiosity` = 当前情绪
- 可以不同（一个平时坚持日常的人今天突然很好奇）

### D4: PlanStep Literal + Household Literal

```python
PlanAction = Literal["move", "stay", "interact", "explore"]
SocialIntent = Literal["alone", "open_to_chat", "seeking_company"]
Household = Literal["single", "couple", "family_with_kids"]
```

- Pydantic 解析 JSON 时用 Literal 校验；拼错 → ValidationError
- `Planner._parse_plan_response` 已有捕获 Exception 的 fallback（返回空
  DailyPlan），无需额外改——只是现在会在日志里看到 ValidationError 而
  不是静默

注意：`activity` / `destination` / `reason` 保持 str（这些是描述性/引用性，
不驱动分支）。

### D5: 人格分布的采样参数

`PopulationProfile` 新增 `personality_params: PersonalityParams`：

```python
class PersonalityParams(BaseModel):
    # 每个维度一对 (mean, std)。std=0 就是全常数。
    openness: tuple[float, float] = (0.5, 0.2)
    conscientiousness: tuple[float, float] = (0.5, 0.2)
    extraversion: tuple[float, float] = (0.5, 0.2)
    agreeableness: tuple[float, float] = (0.5, 0.2)
    neuroticism: tuple[float, float] = (0.5, 0.2)
    curiosity: tuple[float, float] = (0.5, 0.2)
    routine_adherence: tuple[float, float] = (0.5, 0.2)
    risk_tolerance: tuple[float, float] = (0.5, 0.2)
```

`sample_population` 对每个维度做 `clamp(N(μ, σ), 0, 1)`——独立高斯。
维度之间相关性矩阵是未来 change 的事（现在 independent 的假设已经比
"全是 0.5"强得多）。

默认所有 std=0.2，1000 样本下每维度有明显异质性。

### D6: Planner prompt 里表达 trait

prompt 模板 `{personality_description}` 段改为结构化文本：

```
人格特征（0-1 浮点）：
- 好奇心（对新鲜事物）: {curiosity:.2f}
- 日常坚持: {routine_adherence:.2f}
- 外向性: {extraversion:.2f}
- 开放性: {openness:.2f}
- 风险容忍: {risk_tolerance:.2f}
- 责任心: {conscientiousness:.2f}
- 宜人性: {agreeableness:.2f}
- 神经质: {neuroticism:.2f}
```

LLM 看数字比看"内向 + 偏严谨"这种模糊描述更稳定。

### D7: 移除 `profile.trait(name, default)` 便利方法

该方法是反模式的入口：鼓励调用者传魔法字符串 + 魔法默认值。彻底删除，
访问改为 `profile.personality.<field>`。

- 所有调用点清单（grep 过）：
  - `runtime.build_observer_context`: 读 perception, curiosity
  - `runtime.should_replan`（memory 未 archive，先注）: routine_adherence,
    curiosity, close_ties
  - nothing else
- IDE "Rename Symbol" 或手改都可控。测试跟进修。

### D8: ObserverContext 的便利 property 保留

`observer_ctx.investigation_skill` / `perception_skill` / `guilt_level` /
`anxiety_level` 这些便利 property 保留，但内部从 typed 字段读：

```python
@property
def investigation_skill(self) -> float:
    return self.skills.investigation  # 而不是 self.skills.get("investigation", 0.5)
```

perception/filters 都在用，不破坏。

### D9: 迁移策略 — 批量同步

所有 AgentProfile 构造调用点（production + tests）一次性迁：

1. `household=` 从 `"single"` 这种 str 字面量过 Literal 验证——不变
2. 删除传 `personality_traits={}` / `personality_description=""` 的地方
3. 构造默认 `AgentProfile(...)` 会自动用 `PersonalityTraits()`
   （全 0.5）——老测试意图不变
4. `sample_population` 里填 PersonalityParams 采样

批量迁移不分阶段发布（本 change 单次完整）。

### D10: MemoryEvent tag 结构化 — 不在本 change 做

虽然 memory 的 `MemoryEvent.tags: tuple[str, ...]` 同类问题，**本 change
不动**。理由：
- memory change 正准备写新字段（`urgency` / `participants` / `replan_worthy`
  等），重构 tags 和重构 fields 一起做更合理
- typed-personality 已经是大 refactor，再叠加 memory 文件会破坏 rollback
  简单度

memory change 的 design.md 会在本 change archive 后**同步更新**：
- MemoryEvent 加显式字段（`urgency: float`, `participants: tuple[str, ...]`,
  `replan_worthy: bool`）
- tags 只留描述性标签
- `should_replan` 改读 `profile.personality.routine_adherence` + MemoryEvent
  的显式 urgency 字段

## Risks / Trade-offs

**[R1] 所有 AgentProfile 构造点都要改**
→ 影响：profile.py / population.py / runtime.py / planner.py /
  perception/models.py + 10+ 测试文件
→ Mitigation：tasks 分成"模型先建 → 调用点迁移"两阶段，每阶段跑全量
  回归。Pydantic 在迁移中会直接报告未处理的调用点（TypeError / 不识别字段），
  比静默错好得多。

**[R2] Pydantic 默认值太同质**
→ 全 0.5 意味着默认 AgentProfile 仍然异质性为 0
→ Mitigation：sample_population 必须用 PersonalityParams 采样，不走默认
  构造。手工构造的单 agent（tests）使用 0.5 默认不影响功能。

**[R3] LLM 吐错字母现在会 ValidationError**
→ Phase 1 Planner 的 fallback 是返回空 DailyPlan；一旦 LLM 吐错，
  该 agent 当日无计划 → step() 返回 WaitIntent("plan_exhausted")
→ 这是**期望行为**（错得响亮）。可以额外在 Planner 日志里记 LLM 原始
  输出便于调试。

**[R4] Skills / EmotionalState 的字段选择有主观性**
→ 目前只加 Phase 1 已用过的 3-4 个字段。如果未来 change 需要更多
  （社交相关 skill、羞耻情绪等），扩字段即可——typed 模型加字段向后兼容。

## Migration Plan

1. 新建 `agent/personality.py`：PersonalityTraits / Skills / EmotionalState
2. 新建 `agent/plan_types.py` 或放 planner.py：PlanAction / SocialIntent /
   Household Literal
3. 改 AgentProfile：移除 `personality_traits` / `personality_description`
   / `trait()`；加 `personality` 字段；household 改 Literal
4. 改 population.py：加 PersonalityParams；sample_population 填
   PersonalityTraits
5. 改 PlanStep 的 action / social_intent 为 Literal
6. 改 ObserverContext：skills / emotional_state 从 dict 改 typed
7. 改 runtime.build_observer_context：读 typed
8. 改 planner._PLAN_PROMPT_TEMPLATE：引用 typed 字段
9. 改 perception/filters/*：读 typed
10. 改所有构造 AgentProfile / ObserverContext 的测试
11. 跑全量 pytest
12. 跑 make fitness-audit（profile-distribution 应仍 PASS，且
    digital-profile-variance 之外新增 personality-variance 会 PASS）
13. 在 memory change 的 design.md 加 "已被 typed-personality 解决" 注记

### 回滚
- 本 change 是跨文件 refactor，回滚 = revert 整个提交。
- 没有新增外部依赖，回滚不影响环境。

## Open Questions

- **Q1**：是否在 fitness-audit 的 profile-distribution category 里加一条
  `personality-variance` 检查？
  → 建议：加。断言 1000 agent 样本的 `curiosity` std ≥ 0.15。放在本
  change 的 tasks 里。

- **Q2**：memory 的 should_replan 规则需要用到 `close_ties` 这种"关系"——
  那不属于 personality，属于 social-graph capability。
  → 建议：memory change 的 should_replan 默认规则先只看 kind + urgency +
  curiosity；close_ties 留给 social-graph change 再扩展。memory design.md
  的 D7 会相应简化。
