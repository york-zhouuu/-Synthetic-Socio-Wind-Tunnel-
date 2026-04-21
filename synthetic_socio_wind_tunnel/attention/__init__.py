"""
Attention Channel - 数字注意力通道

把"手机 / 推送 / 算法偏向"从 Policy Hack 的分支机制提升为一级接口。

核心概念：
- FeedItem: 手机 feed 上的一条内容
- NotificationEvent: 推送事件（继承 WorldEvent 但走 digital 通道，不经物理传播）
- AttentionState: agent 当前的注意力分配（physical_world / phone_feed / ...）
- DigitalProfile: AgentProfile 的数字生活子字段
- AttentionService: 注入 / 查询 / 算法偏向抑制

相较于物理事件：
- AttentionService.inject_feed_item 不会触发 audible_range / visible_range 传播
- DigitalAttentionFilter 消费 pending_notifications 产出 sense=DIGITAL 的 Observation
"""

from synthetic_socio_wind_tunnel.attention.models import (
    AttentionState,
    DigitalProfile,
    FeedDeliveryRecord,
    FeedItem,
    NotificationEvent,
    create_notification_event,
)
from synthetic_socio_wind_tunnel.attention.service import AttentionService

__all__ = [
    "AttentionService",
    "AttentionState",
    "DigitalProfile",
    "FeedDeliveryRecord",
    "FeedItem",
    "NotificationEvent",
    "create_notification_event",
]
