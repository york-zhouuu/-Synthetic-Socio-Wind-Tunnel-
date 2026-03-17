"""
Exploration Service - 探索与认知地图

处理"角色知道什么"的问题：
- 角色不会立刻知道建筑的所有布局
- 需要探索才能发现新区域
- 认知地图记录已发现的位置

设计原则：
1. 公开信息：建筑名称、类型（可以从外面看到）
2. 可见信息：当前位置 + 相邻位置（通过门/窗）
3. 记忆信息：之前探索过的位置

这是 Perception 层的一部分，只读不写。
写操作（记录探索）由 SimulationService 处理。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.atlas import Atlas
    from synthetic_socio_wind_tunnel.ledger import Ledger


@dataclass
class LocationVisibility:
    """位置可见性信息"""
    location_id: str
    name: str
    location_type: str  # "building", "room", "outdoor"
    visibility_level: str  # "full", "partial", "name_only", "unknown"

    # 完整信息 (visibility_level == "full")
    details: dict = field(default_factory=dict)

    # 部分信息 (visibility_level == "partial")
    # 只有名称、类型、连接的门
    partial_info: dict = field(default_factory=dict)


@dataclass
class VisibleLayout:
    """
    从某个位置能看到的布局信息

    这是 Agent 应该使用的接口，而不是直接调用 Atlas.get_building_info()
    """
    observer_location: str
    observer_location_name: str

    # 当前位置的完整信息
    current_room: dict | None = None

    # 可见的相邻位置（通过门/窗能看到）
    visible_adjacent: list[dict] = field(default_factory=list)

    # 已知但当前不可见的位置（记忆）
    known_locations: list[dict] = field(default_factory=list)

    # 公开信息（建筑名称等）
    public_info: dict = field(default_factory=dict)

    def get_all_known_room_ids(self) -> list[str]:
        """获取所有已知房间 ID"""
        ids = []
        if self.current_room:
            ids.append(self.current_room.get("id", ""))
        ids.extend(r.get("id", "") for r in self.visible_adjacent)
        ids.extend(r.get("id", "") for r in self.known_locations)
        return [i for i in ids if i]


class ExplorationService:
    """
    探索服务 - 提供基于位置的可见性查询

    Agent 应该使用这个服务来了解环境，而不是直接查询 Atlas。
    这确保了信息的获取符合游戏逻辑（需要探索才能发现）。

    Example:
        exploration = ExplorationService(atlas, ledger)

        # 角色在 lobby，想知道能看到什么
        layout = exploration.get_visible_layout("emma", "lobby")

        # 返回：
        # - lobby 的完整信息（当前位置）
        # - office, reading_room 的部分信息（通过门能看到）
        # - 之前探索过的其他房间（记忆）
    """

    __slots__ = ("_atlas", "_ledger")

    def __init__(self, atlas: "Atlas", ledger: "Ledger"):
        self._atlas = atlas
        self._ledger = ledger

    def get_visible_layout(
        self,
        observer_id: str,
        location_id: str,
    ) -> VisibleLayout:
        """
        获取从当前位置能看到的布局信息。

        Args:
            observer_id: 观察者 ID（用于查询记忆）
            location_id: 当前位置 ID

        Returns:
            VisibleLayout 包含分层的位置信息
        """
        location = self._atlas.get_location(location_id)
        if not location:
            return VisibleLayout(
                observer_location=location_id,
                observer_location_name="Unknown",
            )

        result = VisibleLayout(
            observer_location=location_id,
            observer_location_name=location.name,
        )

        # 1. 当前位置的完整信息
        room = self._atlas.get_room(location_id)
        if room:
            result.current_room = self._get_room_full_info(room.id)

            # 2. 通过门能看到的相邻房间
            for connected_id in room.connected_rooms:
                adjacent_info = self._get_room_partial_info(connected_id, location_id)
                if adjacent_info:
                    result.visible_adjacent.append(adjacent_info)

            # 获取所在建筑的公开信息
            building = self._atlas.get_building_for_room(location_id)
            if building:
                result.public_info = {
                    "building_id": building.id,
                    "building_name": building.name,
                }
        else:
            # 可能是建筑入口或户外区域
            building = self._atlas.get_building(location_id)
            if building:
                result.public_info = {
                    "building_id": building.id,
                    "building_name": building.name,
                }
                # 从建筑入口能看到入口房间
                entrance_room = self._find_entrance_room(building)
                if entrance_room:
                    result.visible_adjacent.append(
                        self._get_room_partial_info(entrance_room.id, location_id)
                    )

        # 3. 已探索的位置（记忆）
        explored = self._ledger.get_explored_locations(observer_id)
        for exp_id in explored:
            if exp_id != location_id and exp_id not in [r.get("id") for r in result.visible_adjacent]:
                memory_info = self._get_room_memory_info(exp_id)
                if memory_info:
                    result.known_locations.append(memory_info)

        return result

    def get_building_public_info(self, building_id: str) -> dict | None:
        """
        获取建筑的公开信息（不需要进入就能知道的）。

        这是角色从外面能看到/询问得知的信息。
        """
        building = self._atlas.get_building(building_id)
        if not building:
            return None

        return {
            "id": building.id,
            "name": building.name,
            "has_entrance": building.entrance_coord is not None,
            # 不包含内部房间信息！
        }

    def get_area_public_info(self, area_id: str) -> dict | None:
        """获取户外区域的公开信息。"""
        area = self._atlas.get_outdoor_area(area_id)
        if not area:
            return None

        return {
            "id": area.id,
            "name": area.name,
            "surface": area.surface,
        }

    def what_can_i_see(self, observer_id: str, location_id: str) -> dict:
        """
        简化接口：我能看到什么？

        返回一个 Agent 友好的字典，描述当前能看到的一切。
        """
        layout = self.get_visible_layout(observer_id, location_id)

        return {
            "current_location": {
                "id": layout.observer_location,
                "name": layout.observer_location_name,
                "details": layout.current_room,
            },
            "visible_exits": [
                {
                    "id": adj.get("id"),
                    "name": adj.get("name"),
                    "door": adj.get("door"),
                    "can_see_inside": adj.get("visibility") == "partial",
                }
                for adj in layout.visible_adjacent
            ],
            "remembered_locations": [
                {"id": loc.get("id"), "name": loc.get("name")}
                for loc in layout.known_locations
            ],
            "building": layout.public_info.get("building_name") if layout.public_info else None,
        }

    def discover_location(self, observer_id: str, location_id: str) -> bool:
        """
        记录发现新位置。

        注意：这会修改 Ledger，但为了 API 一致性放在这里。
        实际上应该由 SimulationService.move_entity 自动调用。
        """
        return self._ledger.add_explored_location(observer_id, location_id)

    # ========== Private Methods ==========

    def _get_room_full_info(self, room_id: str) -> dict | None:
        """获取房间的完整信息（当前位置）"""
        room = self._atlas.get_room(room_id)
        if not room:
            return None

        containers = []
        if room.containers:
            for c in room.containers.values():
                container_state = self._ledger.get_container_state(c.container_id)
                containers.append({
                    "id": c.container_id,
                    "name": c.name,
                    "type": c.container_type,
                    "is_open": container_state.is_open if container_state else False,
                    "is_locked": container_state.is_locked if container_state else False,
                    "search_difficulty": c.search_difficulty,
                })

        doors = []
        for door in self._atlas.get_doors_for_room(room_id):
            other_room = door.to_room if door.from_room == room_id else door.from_room
            door_state_open = self._ledger.is_door_open(door.door_id)
            door_state_locked = self._ledger.is_door_locked(door.door_id)
            doors.append({
                "id": door.door_id,
                "to": other_room,
                "to_name": self._get_location_name(other_room),
                "is_open": door_state_open,
                "is_locked": door_state_locked,
                "can_lock": door.can_lock,
            })

        return {
            "id": room.id,
            "name": room.name,
            "containers": containers,
            "doors": doors,
            "sounds": room.typical_sounds,
            "smells": room.typical_smells,
        }

    def _get_room_partial_info(self, room_id: str, from_room_id: str) -> dict | None:
        """
        获取房间的部分信息（通过门能看到的）。

        只包含：名称、类型、连接的门的状态。
        不包含：容器详情、完整布局。
        """
        room = self._atlas.get_room(room_id)
        if not room:
            return None

        # 找到连接两个房间的门
        door = self._atlas.get_door_between(from_room_id, room_id)
        door_info = None
        if door:
            door_info = {
                "id": door.door_id,
                "is_open": self._ledger.is_door_open(door.door_id),
                "is_locked": self._ledger.is_door_locked(door.door_id),
            }

        return {
            "id": room.id,
            "name": room.name,
            "door": door_info,
            "visibility": "partial",  # 只能看到部分
            # 如果门是开的，可以看到一些内容
            "glimpse": self._get_room_glimpse(room_id) if door_info and door_info["is_open"] else None,
        }

    def _get_room_glimpse(self, room_id: str) -> dict | None:
        """
        获取房间的一瞥（门开着时能看到的）。

        非常有限的信息：大概的布局、明显的物品。
        """
        room = self._atlas.get_room(room_id)
        if not room:
            return None

        # 只返回最明显的信息
        visible_containers = []
        if room.containers:
            for c in list(room.containers.values())[:2]:  # 最多2个
                visible_containers.append(c.name)

        return {
            "apparent_size": "small" if len(room.containers or {}) <= 2 else "medium",
            "visible_furniture": visible_containers,
        }

    def _get_room_memory_info(self, room_id: str) -> dict | None:
        """获取房间的记忆信息（之前探索过的）"""
        room = self._atlas.get_room(room_id)
        if not room:
            return None

        return {
            "id": room.id,
            "name": room.name,
            "visibility": "memory",
        }

    def _find_entrance_room(self, building) -> "Room | None":
        """找到建筑的入口房间"""
        if not building.entrance_coord:
            return None

        # 找最近入口的房间
        min_dist = float('inf')
        entrance_room = None

        for room in building.rooms.values():
            dist = room.center.distance_to(building.entrance_coord)
            if dist < min_dist:
                min_dist = dist
                entrance_room = room

        return entrance_room

    def _get_location_name(self, location_id: str) -> str:
        """获取位置名称"""
        loc = self._atlas.get_location(location_id)
        return loc.name if loc else location_id
