"""
Attention Channel - 数据模型

Pydantic 模型（FeedItem / DigitalProfile / AttentionState / FeedDeliveryRecord）
均 frozen，可哈希，符合 CQRS 写入由 Service 控制的风格。

NotificationEvent 是 dataclass 并继承自 WorldEvent，保持与物理事件一致的
mutable 语义（WorldEvent 本身不是 frozen）。其状态语义仍然是"一经构造即事实"，
由 AttentionService 保证写入后不再修改。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from synthetic_socio_wind_tunnel.core.errors import EventType
from synthetic_socio_wind_tunnel.core.events import WorldEvent


FeedSource = Literal[
    "global_news",
    "local_news",
    "commercial_push",
    "social_app",
    "neighbourhood",
]

FeedBias = Literal["global", "local", "mixed"]

AttentionTarget = Literal["physical_world", "phone_feed", "task", "conversation"]


class FeedItem(BaseModel):
    """手机 feed 上的一条内容。frozen 以便哈希与跨 agent 引用。"""

    model_config = ConfigDict(frozen=True)

    feed_item_id: str
    content: str
    source: FeedSource
    hyperlocal_radius: float | None = Field(
        default=None,
        description="米；None 表示全局。命名上区分于物理 audible/visible range。",
        ge=0.0,
    )
    category: str = "event"
    urgency: float = Field(default=0.5, ge=0.0, le=1.0)
    created_at: datetime
    origin_hack_id: str | None = None


class DigitalProfile(BaseModel):
    """AgentProfile 的数字生活子字段。只记可观察事实，不含合成指标。"""

    model_config = ConfigDict(frozen=True)

    daily_screen_hours: float = Field(default=0.0, ge=0.0)
    feed_bias: FeedBias = "global"
    headphones_hours: float = Field(default=0.0, ge=0.0)
    notification_responsiveness: float = Field(default=0.5, ge=0.0, le=1.0)
    primary_apps: tuple[str, ...] = ()


class AttentionState(BaseModel):
    """
    Agent 当前的注意力分配。每 tick 由新实例替换。

    notification_responsiveness 复制自 DigitalProfile 的同名字段，因为
    感知管线只能访问到 ObserverContext.digital_state，无法直接回看 profile；
    pipeline 用它作为 DIGITAL observation 的 confidence 初值，filter 用它判断
    missed tag。
    """

    model_config = ConfigDict(frozen=True)

    attention_target: AttentionTarget = "physical_world"
    screen_time_hours_today: float = Field(default=0.0, ge=0.0)
    last_feed_opened_at: datetime | None = None
    pending_notifications: tuple[str, ...] = ()
    notification_responsiveness: float = Field(default=0.5, ge=0.0, le=1.0)


@dataclass
class NotificationEvent(WorldEvent):
    """
    推送事件 - 继承 WorldEvent，但走 digital 通道：
    - properties 必带 feed_item_id 与 recipient_entity_id
    - audible_range / visible_range 保持 0.0（物理感知层不会看到它）
    - location_id 用 recipient 所在 location 记录，便于归档查询
    """

    @property
    def feed_item_id(self) -> str:
        return self.properties["feed_item_id"]

    @property
    def recipient_entity_id(self) -> str:
        return self.properties["recipient_entity_id"]

    @classmethod
    def from_dict(cls, data: dict) -> "NotificationEvent":
        """由 WorldEvent.to_dict() 产物重建。与 Ledger 存储兼容。"""
        timestamp = data["timestamp"]
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        event_type = data["event_type"]
        if isinstance(event_type, str):
            event_type = EventType(event_type)
        return cls(
            event_type=event_type,
            timestamp=timestamp,
            location_id=data["location_id"],
            actor_id=data.get("actor_id"),
            target_id=data.get("target_id"),
            properties=dict(data.get("properties") or {}),
            audible_range=data.get("audible_range", 0.0),
            visible_range=data.get("visible_range", 0.0),
            source_action=data.get("source_action", ""),
            description=data.get("description", ""),
        )


def create_notification_event(
    *,
    feed_item_id: str,
    recipient_entity_id: str,
    recipient_location_id: str,
    timestamp: datetime,
    origin_hack_id: str | None = None,
) -> NotificationEvent:
    """构造一条数字推送事件。与 create_movement_event 等工厂保持签名风格一致。"""
    properties: dict = {
        "feed_item_id": feed_item_id,
        "recipient_entity_id": recipient_entity_id,
    }
    if origin_hack_id is not None:
        properties["origin_hack_id"] = origin_hack_id

    return NotificationEvent(
        event_type=EventType.NOTIFICATION_RECEIVED,
        timestamp=timestamp,
        location_id=recipient_location_id,
        actor_id=None,
        target_id=recipient_entity_id,
        properties=properties,
        audible_range=0.0,
        visible_range=0.0,
        source_action="inject_feed_item",
        description=f"Notification {feed_item_id} → {recipient_entity_id}",
    )


class FeedDeliveryRecord(BaseModel):
    """推送日志条目；`export_feed_log` 返回的单元。"""

    model_config = ConfigDict(frozen=True)

    feed_item_id: str
    recipient_id: str
    delivered: bool
    delivered_at: datetime
    origin_hack_id: str | None = None
    suppressed_by_bias: bool = False
