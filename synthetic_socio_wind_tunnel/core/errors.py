"""
Core Error Types - 结构化错误码

为 Agent 提供明确的错误信号，避免解析字符串。
"""

from enum import Enum


class SimulationErrorCode(str, Enum):
    """模拟操作错误码"""

    # 成功
    SUCCESS = "success"

    # 位置相关
    LOCATION_NOT_FOUND = "location_not_found"
    LOCATION_UNREACHABLE = "location_unreachable"
    ALREADY_AT_LOCATION = "already_at_location"

    # 门相关
    DOOR_NOT_FOUND = "door_not_found"
    DOOR_LOCKED = "door_locked"
    DOOR_ALREADY_OPEN = "door_already_open"
    DOOR_ALREADY_CLOSED = "door_already_closed"
    DOOR_CANNOT_LOCK = "door_cannot_lock"
    KEY_REQUIRED = "key_required"
    KEY_NOT_HELD = "key_not_held"

    # 实体相关
    ENTITY_NOT_FOUND = "entity_not_found"
    ENTITY_CANNOT_ACT = "entity_cannot_act"

    # 物品相关
    ITEM_NOT_FOUND = "item_not_found"
    ITEM_NOT_ACCESSIBLE = "item_not_accessible"
    ITEM_ALREADY_HELD = "item_already_held"
    CONTAINER_FULL = "container_full"
    CONTAINER_LOCKED = "container_locked"

    # 线索相关
    CLUE_NOT_FOUND = "clue_not_found"
    CLUE_ALREADY_DISCOVERED = "clue_already_discovered"
    SKILL_INSUFFICIENT = "skill_insufficient"

    # 通用
    INVALID_OPERATION = "invalid_operation"
    PRECONDITION_FAILED = "precondition_failed"
    UNKNOWN_ERROR = "unknown_error"


class EventType(str, Enum):
    """事件类型 - 用于描述副作用"""

    # 移动事件
    ENTITY_MOVED = "entity_moved"
    ENTITY_ENTERED_ROOM = "entity_entered_room"
    ENTITY_LEFT_ROOM = "entity_left_room"

    # 声音事件
    SOUND_FOOTSTEPS = "sound_footsteps"
    SOUND_DOOR_OPEN = "sound_door_open"
    SOUND_DOOR_CLOSE = "sound_door_close"
    SOUND_DOOR_LOCK = "sound_door_lock"
    SOUND_ITEM_PICKUP = "sound_item_pickup"
    SOUND_ITEM_DROP = "sound_item_drop"
    SOUND_CONVERSATION = "sound_conversation"

    # 视觉事件
    VISUAL_MOVEMENT_DETECTED = "visual_movement_detected"
    VISUAL_LIGHT_CHANGE = "visual_light_change"

    # 状态变化
    DOOR_STATE_CHANGED = "door_state_changed"
    CONTAINER_STATE_CHANGED = "container_state_changed"
    ITEM_STATE_CHANGED = "item_state_changed"

    # 发现事件
    CLUE_DISCOVERED = "clue_discovered"
    EVIDENCE_FOUND = "evidence_found"
    SECRET_REVEALED = "secret_revealed"

    # 反应事件 (NPC 反应)
    NPC_ALERTED = "npc_alerted"
    NPC_FLED = "npc_fled"
    NPC_NOTICED_PLAYER = "npc_noticed_player"

    # 数字注意力通道事件 (attention-channel 能力，走 digital 通道，不经物理传播)
    NOTIFICATION_RECEIVED = "notification_received"
    FEED_VIEWED = "feed_viewed"
    ATTENTION_TARGET_CHANGED = "attention_target_changed"
