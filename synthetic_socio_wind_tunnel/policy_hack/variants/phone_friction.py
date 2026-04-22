"""
B. PhoneFrictionVariant — H_pull（手机吸力过强假设）

操作化：intervention 首日将每个 agent 的
`DigitalProfile.daily_screen_hours` 乘以 `friction_multiplier`（默认 0.5），
同时降低 `notification_responsiveness` 与 `feed_bias` 朝 "local" 偏移。
Post 首日恢复 intervention 前的 profile。

Cure 生效意味着：**病灶在 pull 端，反-技术化是方向**。弱支持 H_pull。
理论传统：Herbert Simon 注意力经济学 + Tim Wu《Attention Merchants》。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field, PrivateAttr

from synthetic_socio_wind_tunnel.attention.models import DigitalProfile
from synthetic_socio_wind_tunnel.policy_hack.base import Variant, VariantContext

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.agent.profile import AgentProfile


class PhoneFrictionVariant(Variant):
    """B variant — H_pull 的操作化。"""

    name: str = "phone_friction"
    hypothesis: str = "H_pull"  # type: ignore[assignment]
    theoretical_lineage: str = (
        "Simon 注意力稀缺 + Wu《Attention Merchants》：手机商业模式过度"
        "索取注意力；降低 pull 能让人自发回到附近。"
    )
    success_criterion: str = (
        "Friction 期间 agents 的 AttentionState.allocation 'physical_world' "
        "占比上升；空间探索熵上升；encounter 密度上升。"
        "Evidence consistent with H_pull."
    )
    failure_criterion: str = (
        "Friction 无显著行为变化（allocation 分布 IQR 重叠）；或效果仅"
        "在 friction 期间，post 立刻回归。Not consistent with H_pull."
    )
    chain_position: str = "attention-main"  # type: ignore[assignment]

    friction_multiplier: float = Field(
        default=0.5, ge=0.1, le=1.0,
        description="screen_time_hours 与 notification_responsiveness 的"
                    "乘子；1.0 表示无 friction。",
    )
    switch_feed_bias_to: str = Field(
        default="local",
        description="feed_bias 被改为什么值；默认 'local' 配合 friction 叙事。",
    )

    # 缓存每 agent intervention 前的 DigitalProfile，供 post 恢复
    _original_profiles: dict[str, "AgentProfile"] = PrivateAttr(
        default_factory=dict,
    )

    def apply_intervention_start(self, ctx: VariantContext) -> None:
        """首日缓存 + 施加 friction。"""
        for runtime in ctx.runtimes:
            original = runtime.profile
            if original.agent_id in self._original_profiles:
                continue  # 已缓存过（防重复）
            self._original_profiles[original.agent_id] = original

            new_digital = DigitalProfile(
                daily_screen_hours=(
                    original.digital.daily_screen_hours * self.friction_multiplier
                ),
                feed_bias=self.switch_feed_bias_to,  # type: ignore[arg-type]
                headphones_hours=(
                    original.digital.headphones_hours * self.friction_multiplier
                ),
                notification_responsiveness=(
                    original.digital.notification_responsiveness
                    * self.friction_multiplier
                ),
                primary_apps=original.digital.primary_apps,
            )
            new_profile = original.model_copy(update={"digital": new_digital})
            runtime.profile = new_profile

    def apply_day_start(self, ctx: VariantContext) -> None:
        """中间天 no-op——friction 是一次性态度施加。"""
        return

    def apply_intervention_end(self, ctx: VariantContext) -> None:
        """Post 首日恢复原 profile。"""
        for runtime in ctx.runtimes:
            orig = self._original_profiles.get(runtime.profile.agent_id)
            if orig is not None:
                runtime.profile = orig
        # 不 clear 缓存——允许未来 debug / 多次 intervention 循环


__all__ = ["PhoneFrictionVariant"]
