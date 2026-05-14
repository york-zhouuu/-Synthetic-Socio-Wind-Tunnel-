"""
B. PhoneFrictionVariant — H_pull（手机吸力过强假设）

操作化：
1. intervention 首日将每个 agent 的 `DigitalProfile.daily_screen_hours`
   乘以 `friction_multiplier`（默认 0.5），同时降低 `notification_responsiveness`
   与 `feed_bias` 朝 "local" 偏移。
2. intervention 每日通过 `attention_service.inject_feed_item` 注入
   `friction_nudge` FeedItem，让 friction 通过 attention → memory → replan
   链路真正产生 plan-level 行为差异（B3 修复，参见
   `docs/audit/2026-05-09-bug-hunt.md`）。
3. Post 首日恢复 intervention 前的 profile。

Cure 生效意味着：**病灶在 pull 端，反-技术化是方向**。弱支持 H_pull。
理论传统：Herbert Simon 注意力经济学 + Tim Wu《Attention Merchants》。

实现备注：FeedItem.source 是封闭 Literal（5 个值），不为 friction nudge
新增 source 类型，而是复用 `"neighbourhood"`（最贴近"附近邻居"的语义）+
`origin_hack_id="phone_friction"` + `category="self_reflection"` 三段联合
唯一识别本 variant 的注入。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import Field, PrivateAttr

from synthetic_socio_wind_tunnel.attention.models import DigitalProfile, FeedItem
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

    nudge_content_templates: tuple[str, ...] = Field(
        default=(
            "今天注意力被屏幕拽走了——出去走走？",
            "放下手机，看看附近的人。",
            "屏幕之外，街角咖啡店今天有什么？",
            "短暂离线一会儿，看看你的小区。",
        ),
        description="Friction nudge 文案模板池；每日 seed-bound 选 1 条。",
    )
    nudge_target_ratio: float = Field(
        default=1.0, ge=0.1, le=1.0,
        description="每日注入 nudge 给多少比例的 agent（按 agent_id 字典序前 N 个）。",
    )
    nudge_urgency: float = Field(default=0.5, ge=0.0, le=1.0)
    primary_metric_name: str = Field(
        default="encounter.per_day_median",
        description="contest.json 用此键作 primary metric；不再用 degenerate "
                    "的 attention.phone_feed_proxy（B4 修复）。",
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

            # add-attention-induced-nearby-blindness: propagate the reduced
            # daily_screen_hours into the attention service's baseline +
            # cached digital profile so phone_attention dynamics reflect the
            # intervention. Without this the AttentionService keeps the
            # pre-intervention baseline and friction has no thesis-aligned effect.
            if ctx.attention_service is not None:
                from synthetic_socio_wind_tunnel.attention.noticing import (
                    baseline_screen_share,
                )
                ctx.attention_service.set_phone_attention_baseline(
                    original.agent_id, baseline_screen_share(new_digital),
                )
                ctx.attention_service.set_profile(
                    original.agent_id, new_digital,
                )

    def apply_day_start(self, ctx: VariantContext) -> None:
        """每日通过 attention_service 注入 friction_nudge FeedItem。

        intervention 期内每日选 `floor(ratio * N)` 个 agent 注入 1 条 nudge；
        让 friction 通过 attention → memory → replan 真正改变 plan（B3 修复）。
        无 attention_service 注入时为 no-op（保留原"一次性 profile mutation"
        语义不变）。
        """
        if ctx.attention_service is None:
            return

        sorted_ids = sorted(rt.profile.agent_id for rt in ctx.runtimes)
        cutoff = max(1, int(self.nudge_target_ratio * len(sorted_ids)))
        target_ids = tuple(sorted_ids[:cutoff])
        if not target_ids:
            return

        content = ctx.rng.choice(self.nudge_content_templates)
        created_at = datetime.combine(
            ctx.simulated_date, datetime.min.time(),
        ).replace(hour=10)
        item = FeedItem(
            feed_item_id=f"phone_friction_{ctx.seed}_{ctx.day_index}",
            content=content,
            source="neighbourhood",  # 见类 docstring 的"FeedSource 复用"说明
            hyperlocal_radius=None,
            category="self_reflection",
            urgency=self.nudge_urgency,
            created_at=created_at,
            origin_hack_id="phone_friction",
        )
        ctx.attention_service.inject_feed_item(item, target_ids)

    def apply_intervention_end(self, ctx: VariantContext) -> None:
        """Post 首日恢复原 profile。"""
        for runtime in ctx.runtimes:
            orig = self._original_profiles.get(runtime.profile.agent_id)
            if orig is not None:
                runtime.profile = orig
        # 不 clear 缓存——允许未来 debug / 多次 intervention 循环

    def metadata_dict(self) -> dict[str, Any]:
        """Expose primary_metric_name so contest.json picks the right metric."""
        meta = super().metadata_dict()
        meta["primary_metric_name"] = self.primary_metric_name
        return meta


__all__ = ["PhoneFrictionVariant"]
