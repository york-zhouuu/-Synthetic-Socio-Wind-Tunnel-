"""
A'. GlobalDistractionVariant — 与 A (HyperlocalPush) 配对的 paired mirror

操作化：同一 target agent 集合；每日**饱和推送**global-news 内容
（默认 20 条/day）；content 与 hyperlocal 无关；
hyperlocal_radius=None；source="global_news"。

这是 `experimental-design` spec 要求的 dual-use 显式化——证明同一
attention-channel 基建既可用于把人带回附近，也可用于把盲区加深。

Cure"有效"含义：**trajectory 偏离向远方增加**、附近 encounter 下降。
若偏离不明显，说明**仅靠 global-news 不能让附近性进一步恶化**（反
supportive for some version of H_info）。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import Field

from synthetic_socio_wind_tunnel.attention.models import FeedItem
from synthetic_socio_wind_tunnel.policy_hack.base import Variant, VariantContext

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.agent.runtime import AgentRuntime


_DEFAULT_GLOBAL_TEMPLATES: tuple[str, ...] = (
    "BREAKING: 中东局势再度升级，油价创一年新高",
    "AI 新模型在国际基准测试中刷新纪录",
    "冷空气南下，未来三天全国大范围降温",
    "知名艺人在洛杉矶开新展，首日门票售罄",
    "欧洲央行宣布加息 25 基点，市场大幅震荡",
    "某跨国公司被曝数据泄露，涉及数亿用户",
    "TikTok 发布全球年度趋势报告，短视频消费时长再创新高",
    "世界杯预选赛：南美赛区多场爆冷",
    "SpaceX 预告下一次火星任务发射窗口",
    "财经：比特币突破 10 万美元，分析师展望后市",
)


class GlobalDistractionVariant(Variant):
    """A' paired mirror — H_info 的反向操作化。"""

    name: str = "global_distraction"
    hypothesis: str = "H_info"  # type: ignore[assignment]
    theoretical_lineage: str = (
        "同 A (HyperlocalPush) — Shannon/Wu attention economy；但反向操作："
        "饱和 global-news 侵占 agent 注意力。证明工具 dual-use 属性。"
    )
    success_criterion: str = (
        "target agents 相比 control 的 trajectory 更固化（熵下降）；"
        "encounter 密度下降；附近盲区加深。"
        "Evidence consistent with H_info 的反向（即 hyperlocal 信号不足"
        "确实是 binding constraint）。"
    )
    failure_criterion: str = (
        "无论推多少 global-news，agent 行为与 control 无异——说明 routine "
        "主导行为（H_pull 或 H_structure 可能更重要）。"
    )
    chain_position: str = "algorithmic-input"  # type: ignore[assignment]
    is_mirror: bool = True
    paired_variant: str | None = "hyperlocal_push"

    target_agent_ids: tuple[str, ...] | None = Field(
        default=None,
        description="与 A 共享选择逻辑：None 时选前一半 by agent_id 字典序。",
    )
    content_templates: tuple[str, ...] = Field(default=_DEFAULT_GLOBAL_TEMPLATES)
    daily_push_count: int = Field(default=20, ge=1)
    urgency: float = Field(default=0.4, ge=0.0, le=1.0)

    def apply_day_start(self, ctx: VariantContext) -> None:
        if ctx.attention_service is None:
            return

        target_ids = self._resolve_target_ids(ctx.runtimes)
        if not target_ids:
            return

        base_time = datetime.combine(
            ctx.simulated_date, datetime.min.time(),
        )
        for i in range(self.daily_push_count):
            template = ctx.rng.choice(self.content_templates)
            item = FeedItem(
                feed_item_id=(
                    f"global_distraction_{ctx.seed}_{ctx.day_index}_{i}"
                ),
                content=template,
                source="global_news",
                hyperlocal_radius=None,
                category="news_global",
                urgency=self.urgency,
                created_at=base_time.replace(
                    hour=6 + (i * 16 // max(self.daily_push_count, 1)),
                    minute=(i * 7) % 60,
                ),
                origin_hack_id="global_distraction",
            )
            ctx.attention_service.inject_feed_item(item, target_ids)

    def _resolve_target_ids(
        self, runtimes: tuple["AgentRuntime", ...],
    ) -> tuple[str, ...]:
        """与 HyperlocalPushVariant 保持一致的 "前一半" 选择逻辑。"""
        if self.target_agent_ids is not None:
            return self.target_agent_ids
        sorted_ids = sorted(r.profile.agent_id for r in runtimes)
        half = len(sorted_ids) // 2
        return tuple(sorted_ids[:half])


__all__ = ["GlobalDistractionVariant"]
