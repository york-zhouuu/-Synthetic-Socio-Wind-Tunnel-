"""
Event System - 副作用与连锁反应

当一个动作发生时，可能触发多个事件。
这些事件可以被其他系统（如 NPC AI）监听和响应。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from synthetic_socio_wind_tunnel.core.errors import EventType


@dataclass
class WorldEvent:
    """
    世界事件 - 描述发生的事情

    事件是不可变的事实记录，用于：
    1. 通知其他系统（NPC 听到声音）
    2. 记录历史（回放、调试）
    3. 触发连锁反应
    """

    event_type: EventType
    timestamp: datetime
    location_id: str  # 事件发生位置

    # 事件主体
    actor_id: str | None = None  # 谁触发的
    target_id: str | None = None  # 作用对象

    # 事件属性
    properties: dict[str, Any] = field(default_factory=dict)

    # 传播范围
    audible_range: float = 0.0  # 声音传播范围（米）
    visible_range: float = 0.0  # 可见范围（米）

    # 元数据
    source_action: str = ""  # 触发此事件的动作
    description: str = ""  # 人类可读描述

    def is_audible_at(self, distance: float) -> bool:
        """检查在指定距离是否可听到"""
        return self.audible_range > 0 and distance <= self.audible_range

    def is_visible_at(self, distance: float) -> bool:
        """检查在指定距离是否可见"""
        return self.visible_range > 0 and distance <= self.visible_range

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "location_id": self.location_id,
            "actor_id": self.actor_id,
            "target_id": self.target_id,
            "properties": self.properties,
            "audible_range": self.audible_range,
            "visible_range": self.visible_range,
            "source_action": self.source_action,
            "description": self.description,
        }


# ========== 事件工厂函数 ==========


def create_movement_event(
    actor_id: str,
    from_location: str,
    to_location: str,
    timestamp: datetime,
) -> list[WorldEvent]:
    """创建移动相关事件"""
    events = []

    # 离开事件
    events.append(WorldEvent(
        event_type=EventType.ENTITY_LEFT_ROOM,
        timestamp=timestamp,
        location_id=from_location,
        actor_id=actor_id,
        audible_range=10.0,  # 脚步声
        source_action="move_entity",
        description=f"{actor_id} left {from_location}",
    ))

    # 脚步声事件
    events.append(WorldEvent(
        event_type=EventType.SOUND_FOOTSTEPS,
        timestamp=timestamp,
        location_id=from_location,
        actor_id=actor_id,
        audible_range=15.0,
        properties={"direction": to_location},
        source_action="move_entity",
        description=f"Footsteps heard from {from_location}",
    ))

    # 进入事件
    events.append(WorldEvent(
        event_type=EventType.ENTITY_ENTERED_ROOM,
        timestamp=timestamp,
        location_id=to_location,
        actor_id=actor_id,
        visible_range=20.0,
        audible_range=10.0,
        source_action="move_entity",
        description=f"{actor_id} entered {to_location}",
    ))

    return events


def create_door_event(
    actor_id: str,
    door_id: str,
    location_id: str,
    action: str,  # "open", "close", "lock", "unlock"
    timestamp: datetime,
) -> WorldEvent:
    """创建门操作事件"""
    event_type_map = {
        "open": EventType.SOUND_DOOR_OPEN,
        "close": EventType.SOUND_DOOR_CLOSE,
        "lock": EventType.SOUND_DOOR_LOCK,
        "unlock": EventType.SOUND_DOOR_LOCK,
    }

    return WorldEvent(
        event_type=event_type_map.get(action, EventType.DOOR_STATE_CHANGED),
        timestamp=timestamp,
        location_id=location_id,
        actor_id=actor_id,
        target_id=door_id,
        audible_range=12.0,
        properties={"action": action, "door_id": door_id},
        source_action=f"{action}_door",
        description=f"{actor_id} {action}ed door {door_id}",
    )


def create_discovery_event(
    actor_id: str,
    clue_id: str,
    location_id: str,
    reveals: list[str],
    timestamp: datetime,
) -> WorldEvent:
    """创建发现事件"""
    return WorldEvent(
        event_type=EventType.CLUE_DISCOVERED,
        timestamp=timestamp,
        location_id=location_id,
        actor_id=actor_id,
        target_id=clue_id,
        properties={"reveals": reveals},
        source_action="discover_clue",
        description=f"{actor_id} discovered {clue_id}",
    )
