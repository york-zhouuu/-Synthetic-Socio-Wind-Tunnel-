"""
Typed 人格 / 技能 / 情绪 模型

替换 Phase 1 遗留的 dict[str, float] 反模式：
- AgentProfile.personality_traits: dict → PersonalityTraits (typed)
- ObserverContext.skills: dict → Skills (typed)
- ObserverContext.emotional_state: dict → EmotionalState (typed)

所有模型 frozen + 字段范围校验。访问改为 profile.personality.curiosity
（typed, IDE 自动补全, typo 编译期暴露）。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PersonalityTraits(BaseModel):
    """
    Agent 稳定人格维度。8 维度：OCEAN 5 因素 + 3 个本项目 thesis 关键维度。

    每维度 [0, 1] float；默认 0.5（中性）。采样由 agent.population 的
    PersonalityParams 驱动。
    """

    model_config = ConfigDict(frozen=True)

    # OCEAN 五因素
    openness: float = Field(default=0.5, ge=0.0, le=1.0)
    conscientiousness: float = Field(default=0.5, ge=0.0, le=1.0)
    extraversion: float = Field(default=0.5, ge=0.0, le=1.0)
    agreeableness: float = Field(default=0.5, ge=0.0, le=1.0)
    neuroticism: float = Field(default=0.5, ge=0.0, le=1.0)

    # thesis 特别需要
    curiosity: float = Field(default=0.5, ge=0.0, le=1.0)
    """对"新鲜事件 / 偏离日常 / 意外信息"的吸引。memory 的 replan 核心变量。"""

    routine_adherence: float = Field(default=0.5, ge=0.0, le=1.0)
    """对固定日程的坚持度。与 curiosity 相互制衡。"""

    risk_tolerance: float = Field(default=0.5, ge=0.0, le=1.0)
    """对陌生人 / 未知空间 / 低置信任务的接受度。policy-hack / conversation 用。"""


class Skills(BaseModel):
    """
    Agent 观察 / 交互的稳定能力。Phase 1 侦探引擎血统的残留字段。

    用在 perception 的 skill 滤镜（投掷阈值决定是否发现隐藏物品 / 线索）。
    """

    model_config = ConfigDict(frozen=True)

    perception: float = Field(default=0.5, ge=0.0, le=1.0)
    """观察敏锐度。决定注意到远处 / 细微物理线索的概率。"""

    investigation: float = Field(default=0.5, ge=0.0, le=1.0)
    """主动调查能力。隐藏 item 的 discovery_skill 阈值比较对象。"""

    stealth: float = Field(default=0.5, ge=0.0, le=1.0)
    """潜行 / 不被发现。Phase 1 遗留；目前无使用点，保留字段。"""


class EmotionalState(BaseModel):
    """
    Agent 当下的情绪状态（区别于 PersonalityTraits 的稳定倾向）。

    curiosity 同时在两个模型出现是有意的：
    - PersonalityTraits.curiosity = 稳定好奇倾向
    - EmotionalState.curiosity    = 当下好奇感受
    一个日常坚持的人今天也可以一时好奇。
    """

    model_config = ConfigDict(frozen=True)

    guilt: float = Field(default=0.0, ge=0.0, le=1.0)
    anxiety: float = Field(default=0.0, ge=0.0, le=1.0)
    curiosity: float = Field(default=0.0, ge=0.0, le=1.0)
    fear: float = Field(default=0.0, ge=0.0, le=1.0)
