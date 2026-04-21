# Typed Personality

本文件记录 `typed-personality` change（归档于 2026-04-21）的核心决策与
迁移前后对比。

## 为什么

Phase 1 遗留的 `AgentProfile.personality_traits: dict[str, float]` 是
"**用数据存状态**"的反模式：

- `profile.trait("curiosity", 0.5)` — 字符串键 + 魔法默认值
- `sample_population` 从未填此 dict → 1000 agent 全部 `curiosity=0.5` 同质
- typo 永不报错（"currosity" 拿默认 0.5 跟正确写法没区别）
- 无类型提示 / 无可追溯性 / 无全局"哪些 trait 被消费过"视图

同款问题出现在 `PlanStep.action: str`——LLM 吐出 `"moves"` 会静默变
WaitIntent。

## 迁移前后

```
迁移前                              迁移后
────────────────────────────────────────────────────────────────
AgentProfile:
  personality_traits:               personality: PersonalityTraits
    dict[str, float]                  # 8 typed 字段
  personality_description: str      （移除）
  trait(name, default)              （移除）
  household: str                    household: Literal[...]

PlanStep:
  action: str                       action: Literal["move","stay",
                                               "interact","explore"]
  social_intent: str                social_intent: Literal[...]

ObserverContext:
  skills: dict[str, float]          skills: Skills
  emotional_state: dict[str, float] emotional_state: EmotionalState

访问方式：
  profile.trait("curiosity", 0.5)   profile.personality.curiosity
  ctx.get_skill("perception")       ctx.skills.perception
  ctx.emotional_state.get("guilt")  ctx.emotional_state.guilt
```

## 8 个人格维度

| 维度 | 含义 | 主要消费者 |
|---|---|---|
| openness | 对抽象/艺术新思想的开放 | runtime.build_observer_context 映射 perception |
| conscientiousness | 责任感 / 守信 | Planner prompt |
| extraversion | 外向性 | PlanStep.social_intent 倾向 |
| agreeableness | 宜人性 | conversation 未来用 |
| neuroticism | 神经质 | EmotionalState.anxiety 映射 |
| **curiosity** | 对新鲜事件的好奇 | memory.should_replan 核心变量 |
| **routine_adherence** | 对日常计划的坚持 | memory.should_replan 核心变量 |
| **risk_tolerance** | 对陌生人/未知空间的接受 | 未来 policy-hack |

## 采样

`PopulationProfile.personality_params: PersonalityParams`，每维度
独立高斯 `(mean, std)`，默认 `(0.5, 0.2)`，clamp 到 `[0, 1]`。

1000 个采样的 `curiosity` 标准差 `~0.2`（> 0.15 的 fitness-audit 门禁）。

## Planner prompt 变化

`_PLAN_PROMPT_TEMPLATE` 现在直接把 8 个维度的数值丢给 LLM：

```
人格特征（0.0 保守 / 0.5 中性 / 1.0 极端，用来指导你的选择）：
- 好奇心（对新鲜事物）: 0.87
- 日常坚持: 0.23
- 外向性: 0.62
- ...
```

LLM 比读"内向 + 偏严谨"自由描述更稳定。

## PlanStep Literal 的副作用

LLM 吐出拼写错误（`"moves"` / `"walk"` / `"移动"`）时：
- Pydantic 在解析 JSON 时 `ValidationError`
- `Planner._parse_plan` 捕获异常 → 返回空 plan
- orchestrator 接到空 plan 的 agent 走 WaitIntent("plan_exhausted")
- **响亮失败** 而非静默错分支

## fitness-audit 新探针

`profile.personality-variance`：1000 样本 `curiosity` std ≥ 0.15。
默认 `PersonalityParams(0.5, 0.2)` 下 PASS。

## 衔接 memory change

memory 的 `should_replan` 现在读 typed 字段：

```python
adherence = self.profile.personality.routine_adherence   # ≠ .trait(...)
curiosity = self.profile.personality.curiosity
```

memory 的 `MemoryEvent.tags` 反模式（把 urgency 藏在 tag 里）**不在本
change 处理**——留给 memory change 自己把 urgency 提升为显式字段。
