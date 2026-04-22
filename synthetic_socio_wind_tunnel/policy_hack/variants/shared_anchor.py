"""
C. SharedAnchorVariant — H_meaning（共享意义缺失假设）

操作化：intervention 首日挑一条 task 描述；之后每日向一组 predefined
agents（默认 10%）用**同一 feed_item_id**注入 task-category feed。memory
会把它作为 `kind="task_received"` 写入，进 CarryoverContext.pending_task_anchors。

Cure 生效意味着：**病灶在 meaning 层，社会设计是 lever**。弱支持 H_meaning。
理论传统：MacIntyre 共同体主义 + Putnam 社会资本。
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import Field, PrivateAttr

from synthetic_socio_wind_tunnel.attention.models import FeedItem
from synthetic_socio_wind_tunnel.policy_hack.base import Variant, VariantContext

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.agent.runtime import AgentRuntime


_DEFAULT_TASKS: tuple[str, ...] = (
    "社区里据说走失了一只叫阿银的橘猫；如果你今天看到请留意并告诉邻居。",
    "有人在 Lane Cove 的某堵墙上画了一幅新的街头涂鸦；据说只有"
    "走过特定几条小巷才能发现——看见的话别忘了拍照告诉大家。",
    "社区图书角贴了一张纸：邀请所有路过的人今天留下一句给未来邻居的话。",
    "有位老奶奶在 Lane Cove 周围寻找她二十年前在某条街上开过的小花店"
    "留下的木门牌——见过类似线索请告知社区群。",
    "社区今晚准备做公共烛光露台；材料不够，经过的人顺手带点蜡烛或零食。",
)


class SharedAnchorVariant(Variant):
    """C variant — H_meaning 的操作化。"""

    name: str = "shared_anchor"
    hypothesis: str = "H_meaning"  # type: ignore[assignment]
    theoretical_lineage: str = (
        "MacIntyre 共同体主义 + Putnam 社会资本：社区缺共同叙事/目标，"
        "注入一个共享的 anchor 可催化弱连接。"
    )
    success_criterion: str = (
        "共享 anchor 的 agents 之间 encounter density 显著高于 control；"
        "tie formation（未来 social-graph 能测）高于 baseline。"
        "Evidence consistent with H_meaning."
    )
    failure_criterion: str = (
        "anchor agents 的轨迹与非 anchor agents 无差异；task 仅停留在"
        "memory，未转化为空间汇聚。Not consistent with H_meaning."
    )
    chain_position: str = "social-downstream"  # type: ignore[assignment]

    share_ratio: float = Field(default=0.10, ge=0.01, le=1.0)
    task_templates: tuple[str, ...] = Field(default=_DEFAULT_TASKS)
    urgency: float = Field(default=0.65, ge=0.0, le=1.0)

    # 缓存选中的 task & anchor agents（seed 确定性）
    _chosen_task: str | None = PrivateAttr(default=None)
    _anchor_ids: tuple[str, ...] = PrivateAttr(default=())
    _feed_item_id: str | None = PrivateAttr(default=None)

    def apply_intervention_start(self, ctx: VariantContext) -> None:
        """首日选 task + 选 anchor 群体 + 固定 feed_item_id。"""
        self._chosen_task = ctx.rng.choice(self.task_templates)

        all_ids = sorted(r.profile.agent_id for r in ctx.runtimes)
        n_anchors = max(1, math.ceil(len(all_ids) * self.share_ratio))
        # 用 Random.sample 做确定性抽样
        self._anchor_ids = tuple(ctx.rng.sample(all_ids, n_anchors))
        self._feed_item_id = f"shared_anchor_{ctx.seed}"

    def apply_day_start(self, ctx: VariantContext) -> None:
        """Intervention 每日用同一 feed_item_id 推给同一组 agents。"""
        if (ctx.attention_service is None
                or self._chosen_task is None
                or not self._anchor_ids
                or self._feed_item_id is None):
            return

        item = FeedItem(
            feed_item_id=self._feed_item_id,
            content=self._chosen_task,
            source="neighbourhood",
            hyperlocal_radius=None,  # 任务本身不绑定具体点
            category="task",
            urgency=self.urgency,
            created_at=datetime.combine(
                ctx.simulated_date, datetime.min.time(),
            ).replace(hour=8),
            origin_hack_id="shared_anchor",
        )
        ctx.attention_service.inject_feed_item(item, self._anchor_ids)


__all__ = ["SharedAnchorVariant"]
