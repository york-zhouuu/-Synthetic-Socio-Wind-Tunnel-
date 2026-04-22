"""
A. HyperlocalPushVariant — H_info（信息不足假设）

操作化：每日向 "前一半" agent（by agent_id 字典序）推送 1 条 hyperlocal
feed_item；content 从模板池随机（seed-bound）选；category="event"；
source="local_news"；hyperlocal_radius 指向 target_location 附近。

Cure 生效意味着：**病灶在信号层，平台是 lever**。弱支持 H_info。
理论传统：Shannon 信息论 + Wu《Attention Merchants》的注意力稀缺。
"""

from __future__ import annotations

from datetime import datetime
from random import Random
from typing import TYPE_CHECKING

from pydantic import Field

from synthetic_socio_wind_tunnel.attention.models import FeedItem
from synthetic_socio_wind_tunnel.policy_hack.base import Variant, VariantContext

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.agent.runtime import AgentRuntime


_DEFAULT_TEMPLATES: tuple[str, ...] = (
    "距离你不到 500 米的 {location} 今晚 7:30 有社区即兴音乐会，进场免费。",
    "{location} 街角的老烘焙店今晚最后一天营业，全场八折。",
    "听说有人在 {location} 藏了一张关于这条街历史的便签——有人找到了吗？",
    "{location} 附近今晚有邻居自发办的读书分享，主题是《村上春树》。",
    "刚听说 {location} 周围有几只走失的橘猫，遛狗的邻居们在协助找。",
)


class HyperlocalPushVariant(Variant):
    """A variant — H_info 的操作化。"""

    name: str = "hyperlocal_push"
    hypothesis: str = "H_info"  # type: ignore[assignment]
    theoretical_lineage: str = (
        "Shannon 信息论 + Wu《Attention Merchants》：注意力稀缺假设——"
        "附近可被感知的信号不足，平台提供高质量 hyperlocal 内容可补足。"
    )
    success_criterion: str = (
        "target agents 的 trajectory 在 intervention 期间向 target_location "
        "偏移（median delta > 100m）；encounter 密度上升。"
        "Evidence consistent with H_info."
    )
    failure_criterion: str = (
        "target 与 control 之间无显著 delta（IQR 重叠）；或效果衰减在 3 天内。"
        "Not consistent with H_info."
    )
    chain_position: str = "algorithmic-input"  # type: ignore[assignment]

    target_location: str = Field(
        description="推送指向的 outdoor_area id；agent 可能向此位置偏移。",
    )
    target_agent_ids: tuple[str, ...] | None = Field(
        default=None,
        description="None 时运行时选 '前一半' agents by agent_id 字典序。",
    )
    content_templates: tuple[str, ...] = Field(
        default=_DEFAULT_TEMPLATES,
        description="模板池；每日从中 seed-bound 选 1 条。",
    )
    hyperlocal_radius_m: float = Field(default=500.0, gt=0.0)
    daily_push_count: int = Field(default=1, ge=1)

    def apply_day_start(self, ctx: VariantContext) -> None:
        if ctx.attention_service is None:
            return  # 无 attention-channel 的场景无从 push

        target_ids = self._resolve_target_ids(ctx.runtimes)
        if not target_ids:
            return

        for i in range(self.daily_push_count):
            template = ctx.rng.choice(self.content_templates)
            content = template.format(location=self.target_location)
            item = FeedItem(
                feed_item_id=(
                    f"hyperlocal_push_{ctx.seed}_{ctx.day_index}_{i}"
                ),
                content=content,
                source="local_news",
                hyperlocal_radius=self.hyperlocal_radius_m,
                category="event",
                urgency=0.6,
                created_at=datetime.combine(
                    ctx.simulated_date, datetime.min.time(),
                ).replace(hour=9),  # 上午 9 点发
                origin_hack_id="hyperlocal_push",
            )
            ctx.attention_service.inject_feed_item(item, target_ids)

    def _resolve_target_ids(
        self, runtimes: tuple["AgentRuntime", ...],
    ) -> tuple[str, ...]:
        if self.target_agent_ids is not None:
            return self.target_agent_ids
        sorted_ids = sorted(r.profile.agent_id for r in runtimes)
        half = len(sorted_ids) // 2
        return tuple(sorted_ids[:half])


__all__ = ["HyperlocalPushVariant"]
