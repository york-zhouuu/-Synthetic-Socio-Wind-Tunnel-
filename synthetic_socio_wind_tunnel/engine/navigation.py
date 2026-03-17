"""
NavigationService - 导航与路线规划

提供完整的导航功能:
- 自动推断房间到建筑入口的连接
- 考虑门的状态 (开/关/锁)
- 生成详细的导航指令
- 支持多种路径策略

Reads: Atlas (地图), Ledger (门状态)
Writes: None (纯查询)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING
import heapq

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.atlas import Atlas
    from synthetic_socio_wind_tunnel.ledger import Ledger


class PathStrategy(str, Enum):
    """路径策略"""
    SHORTEST = "shortest"      # 最短距离
    FEWEST_DOORS = "fewest_doors"  # 最少门
    AVOID_LOCKED = "avoid_locked"  # 避开锁门


@dataclass
class NavigationStep:
    """导航步骤"""
    from_location: str
    to_location: str
    action: str  # "walk", "enter_building", "exit_building", "open_door", "unlock_door"
    distance: float
    door_id: str | None = None
    description: str = ""


@dataclass
class NavigationResult:
    """导航结果"""
    success: bool
    from_location: str
    to_location: str
    steps: list[NavigationStep] = field(default_factory=list)
    total_distance: float = 0.0
    doors_to_pass: int = 0
    locked_doors: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def path(self) -> list[str]:
        """获取路径位置列表"""
        if not self.steps:
            return [self.from_location]
        locations = [self.from_location]
        for step in self.steps:
            if step.to_location not in locations:
                locations.append(step.to_location)
        return locations

    def describe(self) -> str:
        """生成人类可读的导航描述"""
        if not self.success:
            return f"无法到达 {self.to_location}: {self.error}"

        lines = [f"从 {self.from_location} 到 {self.to_location}:"]
        for i, step in enumerate(self.steps, 1):
            lines.append(f"  {i}. {step.description}")
        lines.append(f"总距离: {self.total_distance:.1f}m, 经过 {self.doors_to_pass} 道门")

        if self.locked_doors:
            lines.append(f"⚠️ 需要钥匙: {', '.join(self.locked_doors)}")

        return "\n".join(lines)


class NavigationService:
    """
    导航服务 - 提供完整的路线规划功能

    自动处理:
    - 房间内部连接 (通过 connected_rooms)
    - 房间到建筑入口的连接
    - 建筑到外部区域的连接
    - 门的状态检查

    Example:
        nav = NavigationService(atlas, ledger)
        result = nav.find_route("reading_room", "kitchen")
        print(result.describe())
    """

    __slots__ = ("_atlas", "_ledger", "_full_graph")

    def __init__(self, atlas: "Atlas", ledger: "Ledger"):
        self._atlas = atlas
        self._ledger = ledger
        self._full_graph = self._build_full_graph()

    def _build_full_graph(self) -> dict[str, list[tuple[str, float, str | None, str]]]:
        """
        构建完整的连接图

        Returns:
            {location_id: [(neighbor_id, distance, door_id, action), ...]}
        """
        graph: dict[str, list[tuple[str, float, str | None, str]]] = {}

        def add_edge(from_id: str, to_id: str, dist: float, door_id: str | None, action: str):
            if from_id not in graph:
                graph[from_id] = []
            graph[from_id].append((to_id, dist, door_id, action))

        region = self._atlas._region

        # 1. 添加显式连接 (atlas.json 中定义的)
        for conn in region.connections:
            action = "open_door" if conn.path_type == "door" else "walk"

            # 查找门 ID
            door_id = None
            if conn.path_type == "door":
                door = region.get_door_between(conn.from_id, conn.to_id)
                door_id = door.door_id if door else None

            add_edge(conn.from_id, conn.to_id, conn.distance, door_id, action)
            if conn.bidirectional:
                add_edge(conn.to_id, conn.from_id, conn.distance, door_id, action)

        # 2. 添加房间内部连接 (通过 connected_rooms)
        for building in region.buildings.values():
            for room in building.rooms.values():
                for neighbor_id in room.connected_rooms:
                    # 检查是否已有连接
                    existing = graph.get(room.id, [])
                    if not any(n[0] == neighbor_id for n in existing):
                        # 查找门
                        door = region.get_door_between(room.id, neighbor_id)
                        door_id = door.door_id if door else None

                        # 计算距离 (房间中心到房间中心)
                        neighbor_room = building.rooms.get(neighbor_id)
                        if neighbor_room:
                            dist = room.center.distance_to(neighbor_room.center)
                        else:
                            dist = 3.0  # 默认门距离

                        add_edge(room.id, neighbor_id, dist, door_id, "open_door" if door_id else "walk")
                        add_edge(neighbor_id, room.id, dist, door_id, "open_door" if door_id else "walk")

        # 3. 添加房间到建筑入口的连接
        for building in region.buildings.values():
            if building.entrance_coord:
                # 找到最近入口的房间 (通常是 lobby)
                entrance_room = None
                min_dist = float('inf')

                for room in building.rooms.values():
                    dist = room.center.distance_to(building.entrance_coord)
                    if dist < min_dist:
                        min_dist = dist
                        entrance_room = room

                if entrance_room:
                    # 连接入口房间到建筑
                    add_edge(entrance_room.id, building.id, 2.0, None, "exit_building")
                    add_edge(building.id, entrance_room.id, 2.0, None, "enter_building")

        # 4. 确保建筑级连接存在
        for conn in region.connections:
            # 如果是建筑到外部的连接，确保双向
            if conn.from_id in region.buildings or conn.to_id in region.buildings:
                if conn.from_id not in graph:
                    graph[conn.from_id] = []
                if conn.to_id not in graph:
                    graph[conn.to_id] = []

        return graph

    def find_route(
        self,
        from_location: str,
        to_location: str,
        strategy: PathStrategy = PathStrategy.SHORTEST,
        check_doors: bool = True,
    ) -> NavigationResult:
        """
        查找从起点到终点的路线

        Args:
            from_location: 起始位置 ID
            to_location: 目标位置 ID
            strategy: 路径策略
            check_doors: 是否检查门状态

        Returns:
            NavigationResult 包含详细路线
        """
        if from_location == to_location:
            return NavigationResult(
                success=True,
                from_location=from_location,
                to_location=to_location,
                total_distance=0.0,
            )

        if from_location not in self._full_graph:
            return NavigationResult(
                success=False,
                from_location=from_location,
                to_location=to_location,
                error=f"未知位置: {from_location}",
            )

        # A* 搜索
        # Priority queue: (cost, counter, location, path)
        open_set: list[tuple[float, int, str, list[tuple[str, str, float, str | None, str]]]] = [
            (0, 0, from_location, [])
        ]
        visited: set[str] = set()
        counter = 0

        while open_set:
            cost, _, current, path = heapq.heappop(open_set)

            if current == to_location:
                return self._build_result(from_location, to_location, path, check_doors)

            if current in visited:
                continue
            visited.add(current)

            for neighbor, dist, door_id, action in self._full_graph.get(current, []):
                if neighbor in visited:
                    continue

                # 计算代价
                edge_cost = dist
                if strategy == PathStrategy.FEWEST_DOORS and door_id:
                    edge_cost += 10.0  # 门的额外代价
                elif strategy == PathStrategy.AVOID_LOCKED and door_id:
                    if self._ledger.is_door_locked(door_id):
                        edge_cost += 100.0  # 锁门的高代价

                new_cost = cost + edge_cost
                new_path = path + [(current, neighbor, dist, door_id, action)]

                # 启发式: 到目标的估计距离
                h = self._heuristic(neighbor, to_location)

                counter += 1
                heapq.heappush(open_set, (new_cost + h, counter, neighbor, new_path))

        return NavigationResult(
            success=False,
            from_location=from_location,
            to_location=to_location,
            error=f"无法找到从 {from_location} 到 {to_location} 的路径",
        )

    def _heuristic(self, from_id: str, to_id: str) -> float:
        """A* 启发式函数"""
        from_center = self._atlas.get_center(from_id)
        to_center = self._atlas.get_center(to_id)
        if from_center and to_center:
            return from_center.distance_to(to_center)
        return 0.0

    def _build_result(
        self,
        from_location: str,
        to_location: str,
        path: list[tuple[str, str, float, str | None, str]],
        check_doors: bool,
    ) -> NavigationResult:
        """构建导航结果"""
        steps: list[NavigationStep] = []
        total_distance = 0.0
        doors_to_pass = 0
        locked_doors: list[str] = []

        for from_loc, to_loc, dist, door_id, action in path:
            total_distance += dist

            # 生成描述
            if action == "enter_building":
                desc = f"进入 {self._get_name(to_loc)}"
            elif action == "exit_building":
                desc = f"离开建筑，前往 {self._get_name(to_loc)}"
            elif action == "open_door":
                doors_to_pass += 1
                door_name = door_id or "门"

                # 检查门状态
                if check_doors and door_id:
                    if self._ledger.is_door_locked(door_id):
                        locked_doors.append(door_id)
                        desc = f"🔒 打开 {door_name} (已锁) 进入 {self._get_name(to_loc)}"
                        action = "unlock_door"
                    elif not self._ledger.is_door_open(door_id):
                        desc = f"打开 {door_name} 进入 {self._get_name(to_loc)}"
                    else:
                        desc = f"穿过 {door_name} 进入 {self._get_name(to_loc)}"
                else:
                    desc = f"穿过门进入 {self._get_name(to_loc)}"
            else:
                desc = f"步行到 {self._get_name(to_loc)} ({dist:.1f}m)"

            steps.append(NavigationStep(
                from_location=from_loc,
                to_location=to_loc,
                action=action,
                distance=dist,
                door_id=door_id,
                description=desc,
            ))

        return NavigationResult(
            success=True,
            from_location=from_location,
            to_location=to_location,
            steps=steps,
            total_distance=total_distance,
            doors_to_pass=doors_to_pass,
            locked_doors=locked_doors,
        )

    def _get_name(self, location_id: str) -> str:
        """获取位置名称"""
        loc = self._atlas.get_location(location_id)
        return loc.name if loc else location_id

    def get_reachable_locations(
        self,
        from_location: str,
        max_distance: float | None = None,
        include_locked: bool = False,
    ) -> list[tuple[str, float]]:
        """
        获取从某位置可到达的所有位置

        Args:
            from_location: 起始位置
            max_distance: 最大距离限制
            include_locked: 是否包含需要钥匙的位置

        Returns:
            [(location_id, distance), ...] 按距离排序
        """
        reachable: dict[str, float] = {}
        visited: set[str] = set()
        queue: list[tuple[float, str]] = [(0, from_location)]

        while queue:
            dist, current = heapq.heappop(queue)

            if current in visited:
                continue
            visited.add(current)

            if max_distance and dist > max_distance:
                continue

            reachable[current] = dist

            for neighbor, edge_dist, door_id, _ in self._full_graph.get(current, []):
                if neighbor in visited:
                    continue

                # 检查锁门
                if not include_locked and door_id:
                    if self._ledger.is_door_locked(door_id):
                        continue

                new_dist = dist + edge_dist
                heapq.heappush(queue, (new_dist, neighbor))

        # 排序并返回 (排除起点)
        result = [(loc, d) for loc, d in reachable.items() if loc != from_location]
        result.sort(key=lambda x: x[1])
        return result

    def get_nearby_locations(
        self,
        from_location: str,
        radius: float = 20.0,
    ) -> list[tuple[str, float]]:
        """获取附近位置 (在指定半径内)"""
        return self.get_reachable_locations(from_location, max_distance=radius)

    def can_reach(
        self,
        from_location: str,
        to_location: str,
        check_locked: bool = True,
    ) -> tuple[bool, str | None]:
        """
        检查是否可以到达目标

        Returns:
            (can_reach, reason_if_not)
        """
        result = self.find_route(
            from_location,
            to_location,
            strategy=PathStrategy.AVOID_LOCKED if check_locked else PathStrategy.SHORTEST,
            check_doors=check_locked,
        )

        if not result.success:
            return False, result.error

        if check_locked and result.locked_doors:
            return False, f"需要钥匙: {', '.join(result.locked_doors)}"

        return True, None
