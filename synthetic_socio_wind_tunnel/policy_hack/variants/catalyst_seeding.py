"""
D. CatalystSeedingVariant — H_structure（社区缺连接者假设）

操作化：run 前**一次性**把 `catalyst_ratio`（默认 5%）的 agents 的
personality 字段替换为 "connector" 预设（高 extraversion / 低
routine_adherence / 高 curiosity）。其它字段（年龄 / 职业 / housing /
digital 等）不变。

Cure 生效意味着：**病灶在结构层，城市规划是 lever**。弱支持 H_structure。
理论传统：Granovetter 弱关系 + Burt 结构洞。
"""

from __future__ import annotations

import math
from random import Random
from typing import TYPE_CHECKING

from pydantic import Field

from synthetic_socio_wind_tunnel.agent.personality import PersonalityTraits
from synthetic_socio_wind_tunnel.policy_hack.base import Variant, VariantContext

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.agent.profile import AgentProfile


# Connector 预设：高外向 / 低 routine / 高 curiosity（& 适度其它）
_CONNECTOR_PERSONALITY = PersonalityTraits(
    openness=0.80,
    conscientiousness=0.55,
    extraversion=0.90,
    agreeableness=0.75,
    neuroticism=0.30,
    curiosity=0.90,
    routine_adherence=0.20,
    risk_tolerance=0.70,
)


class CatalystSeedingVariant(Variant):
    """D variant — H_structure 的操作化。"""

    name: str = "catalyst_seeding"
    hypothesis: str = "H_structure"  # type: ignore[assignment]
    theoretical_lineage: str = (
        "Granovetter 弱关系 + Burt 结构洞：社区缺少 bridging 个体，"
        "种入少量 connector 人格可涌现更多弱连接。"
    )
    success_criterion: str = (
        "Intervention 期间 encounter 网络密度 / clustering 上升；bridging "
        "agents 自发出现；弱关系（未来 social-graph 测）增量显著。"
        "Evidence consistent with H_structure."
    )
    failure_criterion: str = (
        "Connector 种子对 encounter 网络无显著影响（度分布 / 聚类系数不变）；"
        "或仅 connector 自己受益。Not consistent with H_structure."
    )
    chain_position: str = "social-downstream"  # type: ignore[assignment]

    catalyst_ratio: float = Field(default=0.05, ge=0.01, le=0.50)
    catalyst_personality: PersonalityTraits = Field(
        default=_CONNECTOR_PERSONALITY,
        description="被选中 agent 的 personality 被完全替换为此值。",
    )

    def apply_population(
        self,
        profiles: list["AgentProfile"],
        rng: Random,
    ) -> list["AgentProfile"]:
        """
        从 profiles 里选 `ceil(N × catalyst_ratio)` 个 agent；用
        `catalyst_personality` 覆盖其 personality 字段，其它字段不变。

        使用 Random.sample 保证同 rng 同 seed 下**选中集合可复现**。
        """
        if not profiles:
            return profiles

        n_catalysts = max(1, math.ceil(len(profiles) * self.catalyst_ratio))
        n_catalysts = min(n_catalysts, len(profiles))
        indexes = rng.sample(range(len(profiles)), n_catalysts)
        chosen = set(indexes)

        out: list["AgentProfile"] = []
        for i, p in enumerate(profiles):
            if i in chosen:
                out.append(p.model_copy(
                    update={"personality": self.catalyst_personality},
                ))
            else:
                out.append(p)
        return out

    def apply_day_start(self, ctx: VariantContext) -> None:
        """本 variant 作用在 run 前；每日 no-op。"""
        return


__all__ = ["CatalystSeedingVariant"]
