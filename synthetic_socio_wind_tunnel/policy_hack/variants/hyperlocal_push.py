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
from typing import TYPE_CHECKING, Any

from pydantic import Field, PrivateAttr

from synthetic_socio_wind_tunnel.attention.models import FeedItem
from synthetic_socio_wind_tunnel.policy_hack.base import Variant, VariantContext
from synthetic_socio_wind_tunnel.policy_hack.personalizer import (
    PushPersonalizer,
    PushTemplate,
)
from synthetic_socio_wind_tunnel.policy_hack.templates import PUSH_TEMPLATES

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
    hyperlocal_radius_m: float = Field(default=1000.0, gt=0.0)  # CLAUDE.md 1km
    # B4 fix: equalize hp / gd push count to isolate "direction" effect.
    # Both variants now push 5/day per target recipient.
    daily_push_count: int = Field(default=5, ge=1)
    # push-content-individualization：True 时走 PushPersonalizer 路径（每个
    # target 收到 audience-aware 个体化 FeedItem）；False 时退回 legacy 路径
    # （broadcast 一条 generic content 给所有 target）
    use_personalizer: bool = Field(default=True)
    push_template_pool: tuple[PushTemplate, ...] = Field(
        default=PUSH_TEMPLATES,
        description="个体化路径用的 PushTemplate 池；按 day rng 选 1 个/day。",
    )

    # Cache of resolved target_agent_ids — populated on first apply_day_start.
    # Exposed via metadata_dict so metric factory can compute protag-only
    # trajectory_deviation_m without dragging in 90 scripted agents (B1 fix).
    _resolved_target_ids: tuple[str, ...] | None = PrivateAttr(default=None)

    def apply_day_start(self, ctx: VariantContext) -> None:
        if ctx.attention_service is None:
            return  # 无 attention-channel 的场景无从 push

        target_ids = self._resolve_target_ids(ctx.runtimes)
        if not target_ids:
            return

        created_at = datetime.combine(
            ctx.simulated_date, datetime.min.time(),
        ).replace(hour=9)  # 上午 9 点发

        if self.use_personalizer and self.push_template_pool:
            self._apply_personalized(ctx, target_ids, created_at)
        else:
            self._apply_legacy(ctx, target_ids, created_at)

    def _apply_personalized(
        self,
        ctx: VariantContext,
        target_ids: tuple[str, ...],
        created_at: datetime,
    ) -> None:
        """push-content-individualization 路径：每 target 一条 personalized FeedItem。"""
        # build agent_id -> profile lookup once
        profile_by_id = {r.profile.agent_id: r.profile for r in ctx.runtimes}
        for push_idx in range(self.daily_push_count):
            template = ctx.rng.choice(self.push_template_pool)
            for agent_id in target_ids:
                profile = profile_by_id.get(agent_id)
                if profile is None:
                    continue  # safety guard
                feed_id = (
                    f"hyperlocal_push_{ctx.seed}_{ctx.day_index}_"
                    f"{push_idx}_{agent_id}"
                )
                item, _rel = PushPersonalizer.personalize(
                    template, profile,
                    location=self.target_location,
                    feed_item_id=feed_id,
                    created_at=created_at,
                    source="local_news",
                    base_urgency=0.6,
                    hyperlocal_radius_m=self.hyperlocal_radius_m,
                    origin_hack_id="hyperlocal_push",
                )
                # Single recipient — keeps personalization 1:1
                ctx.attention_service.inject_feed_item(item, [agent_id])

    def _apply_legacy(
        self,
        ctx: VariantContext,
        target_ids: tuple[str, ...],
        created_at: datetime,
    ) -> None:
        """Legacy broadcast path (kept for tests / rollback)."""
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
                created_at=created_at,
                origin_hack_id="hyperlocal_push",
            )
            ctx.attention_service.inject_feed_item(item, target_ids)

    def _resolve_target_ids(
        self, runtimes: tuple["AgentRuntime", ...],
    ) -> tuple[str, ...]:
        if self.target_agent_ids is not None:
            resolved = self.target_agent_ids
        else:
            sorted_ids = sorted(r.profile.agent_id for r in runtimes)
            half = len(sorted_ids) // 2
            resolved = tuple(sorted_ids[:half])
        # Cache so metadata_dict can expose for downstream metric factory.
        self._resolved_target_ids = resolved
        return resolved

    def metadata_dict(self) -> dict[str, Any]:
        meta = super().metadata_dict()
        meta["target_location"] = self.target_location
        if self._resolved_target_ids is not None:
            meta["target_agent_ids"] = self._resolved_target_ids
        return meta


__all__ = ["HyperlocalPushVariant"]
