"""
Atlas Service - Read-only queries on static map data.

Atlas is the "Stage" — it provides spatial queries but never modifies data.
All methods are pure functions with no side effects.

Designed for urban community social simulation:
- Location queries (buildings, streets, outdoor areas)
- Spatial queries (radius search, containment)
- Pathfinding (A* with connection graph)
- Line of sight / sound propagation
- Border zone queries
"""

from __future__ import annotations
import json
from pathlib import Path
import heapq

from synthetic_socio_wind_tunnel.atlas.models import (
    Region,
    Building,
    Room,
    OutdoorArea,
    Connection,
    Coord,
    Polygon,
    Material,
    ContainerDef,
    DoorDef,
    BorderZone,
    BorderType,
)


class Atlas:
    """
    Read-only service for querying static map data.

    Atlas is immutable after construction. Thread-safe (no mutable state).
    """

    __slots__ = ("_region", "_connection_graph")

    def __init__(self, region: Region):
        """Initialize with a Region. Use from_json() for file loading."""
        self._region = region
        self._connection_graph = self._build_graph()

    @classmethod
    def from_json(cls, path: str | Path) -> "Atlas":
        """Load Atlas from a JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        region = Region.model_validate(data)
        return cls(region)

    @classmethod
    def from_dict(cls, data: dict) -> "Atlas":
        """Create Atlas from a dictionary."""
        region = Region.model_validate(data)
        return cls(region)

    # ========== Properties ==========

    @property
    def region_id(self) -> str:
        return self._region.id

    @property
    def region_name(self) -> str:
        return self._region.name

    @property
    def region(self) -> Region:
        return self._region

    # ========== Location Queries ==========

    def get_building(self, building_id: str) -> Building | None:
        """Get building by ID."""
        return self._region.buildings.get(building_id)

    def get_room(self, room_id: str) -> Room | None:
        """Get room by ID (searches all buildings)."""
        for building in self._region.buildings.values():
            if room_id in building.rooms:
                return building.rooms[room_id]
        return None

    def get_outdoor_area(self, area_id: str) -> OutdoorArea | None:
        """Get outdoor area by ID."""
        return self._region.outdoor_areas.get(area_id)

    def get_location(self, location_id: str) -> Building | Room | OutdoorArea | None:
        """Get any location type by ID."""
        return self._region.get_location(location_id)

    def get_center(self, location_id: str) -> Coord | None:
        """Get center coordinate of a location."""
        return self._region.get_location_center(location_id)

    def list_buildings(self) -> list[str]:
        """List all building IDs."""
        return list(self._region.buildings.keys())

    def list_outdoor_areas(self) -> list[str]:
        """List all outdoor area IDs."""
        return list(self._region.outdoor_areas.keys())

    def list_rooms(self, building_id: str) -> list[str]:
        """List all room IDs in a building."""
        building = self.get_building(building_id)
        return list(building.rooms.keys()) if building else []

    def get_building_for_room(self, room_id: str) -> Building | None:
        """Find which building contains a room."""
        for building in self._region.buildings.values():
            if room_id in building.rooms:
                return building
        return None

    # ========== Type-based Queries (按类型查询) ==========

    def list_buildings_by_type(self, building_type: str) -> list[Building]:
        """List all buildings of a given type (cafe, residential, etc.)."""
        return [
            b for b in self._region.buildings.values()
            if b.building_type == building_type
        ]

    def list_residential_buildings(self) -> list[Building]:
        """All residential buildings, as candidate homes for agent placement.

        Used by orchestrators / agent factories to assign `AgentProfile.home_location`.
        Each residential building carries a default `reside` affordance with a
        `capacity` hint so callers can spread agents without overfilling.
        Phase 2 (see openspec/changes/phase-2-roadmap) will layer tenant and
        household demographics on top of this list.
        """
        return self.list_buildings_by_type("residential")

    def list_street_segments(self) -> list[OutdoorArea]:
        """List all street segments."""
        return [
            a for a in self._region.outdoor_areas.values()
            if a.is_street
        ]

    def list_street_segments_by_road(self, road_name: str) -> list[OutdoorArea]:
        """List all segments of a specific road, ordered by segment_index."""
        segments = [
            a for a in self._region.outdoor_areas.values()
            if a.is_street and a.road_name == road_name
        ]
        segments.sort(key=lambda s: s.segment_index or 0)
        return segments

    def list_open_spaces(self) -> list[OutdoorArea]:
        """List all non-street outdoor areas (parks, plazas, etc.)."""
        return [
            a for a in self._region.outdoor_areas.values()
            if not a.is_street
        ]

    def list_road_names(self) -> list[str]:
        """List all unique road names."""
        names: set[str] = set()
        for area in self._region.outdoor_areas.values():
            if area.is_street and area.road_name:
                names.add(area.road_name)
        return sorted(names)

    # ========== Hierarchical Queries (层级查询) ==========

    def get_building_info(self, building_id: str) -> dict | None:
        """
        获取建筑的完整信息，包括所有房间摘要。
        Agent 到达新建筑时调用此方法了解内部结构。
        """
        building = self.get_building(building_id)
        if not building:
            return None

        rooms_info = []
        for room in building.rooms.values():
            rooms_info.append({
                "id": room.id,
                "name": room.name,
                "type": room.room_type,
                "connected_to": list(room.connected_rooms),
                "containers": list(room.containers.keys()) if room.containers else [],
            })

        doors_info = []
        for door in self._region.doors.values():
            if door.from_room in building.rooms or door.to_room in building.rooms:
                doors_info.append({
                    "id": door.door_id,
                    "from": door.from_room,
                    "to": door.to_room,
                    "can_lock": door.can_lock,
                    "key_required": door.lock_key_id,
                })

        return {
            "id": building.id,
            "name": building.name,
            "type": building.building_type,
            "description": building.description,
            "rooms": rooms_info,
            "entrance": {
                "x": building.entrance_coord.x,
                "y": building.entrance_coord.y,
            } if building.entrance_coord else None,
            "doors": doors_info,
            "active_hours": building.active_hours,
        }

    def get_room_info(self, room_id: str) -> dict | None:
        """
        获取房间的完整信息，包括容器和连接。
        Agent 进入房间时调用此方法了解可交互对象。
        """
        room = self.get_room(room_id)
        if not room:
            return None

        building = self.get_building_for_room(room_id)

        containers_info = []
        if room.containers:
            for container in room.containers.values():
                containers_info.append({
                    "id": container.container_id,
                    "name": container.name,
                    "type": container.container_type,
                    "can_lock": container.can_lock,
                    "search_difficulty": container.search_difficulty,
                })

        doors_info = []
        for door in self.get_doors_for_room(room_id):
            other_room = door.to_room if door.from_room == room_id else door.from_room
            doors_info.append({
                "id": door.door_id,
                "to": other_room,
                "can_lock": door.can_lock,
                "key_required": door.lock_key_id,
            })

        return {
            "id": room.id,
            "name": room.name,
            "type": room.room_type,
            "building_id": building.id if building else None,
            "connected_rooms": list(room.connected_rooms),
            "containers": containers_info,
            "doors": doors_info,
            "typical_sounds": room.typical_sounds,
            "typical_smells": room.typical_smells,
        }

    def get_region_overview(self) -> dict:
        """
        获取整个区域的概览。
        Agent 初始化时调用此方法了解世界结构。
        """
        buildings_info = []
        for building in self._region.buildings.values():
            buildings_info.append({
                "id": building.id,
                "name": building.name,
                "type": building.building_type,
                "room_count": len(building.rooms),
                "description": building.description,
            })

        outdoor_info = []
        for area in self._region.outdoor_areas.values():
            outdoor_info.append({
                "id": area.id,
                "name": area.name,
                "type": area.area_type,
                "is_street": area.is_street,
                "road_name": area.road_name,
            })

        connections_info = []
        for conn in self._region.connections:
            connections_info.append({
                "from": conn.from_id,
                "to": conn.to_id,
                "type": conn.path_type,
                "distance": conn.distance,
                "bidirectional": conn.bidirectional,
            })

        borders_info = []
        for border in self._region.borders.values():
            borders_info.append({
                "id": border.border_id,
                "name": border.name,
                "type": border.border_type.value,
                "permeability": border.permeability,
            })

        return {
            "id": self._region.id,
            "name": self._region.name,
            "buildings": buildings_info,
            "outdoor_areas": outdoor_info,
            "connections": connections_info,
            "borders": borders_info,
            "road_names": self.list_road_names(),
        }

    def list_containers_in_room(self, room_id: str) -> list[dict]:
        """列出房间内所有容器的摘要信息。"""
        room = self.get_room(room_id)
        if not room or not room.containers:
            return []

        return [
            {
                "id": c.container_id,
                "name": c.name,
                "type": c.container_type,
                "can_lock": c.can_lock,
                "search_difficulty": c.search_difficulty,
            }
            for c in room.containers.values()
        ]

    def list_all_locations(self) -> list[dict]:
        """列出所有可访问的位置。"""
        locations = []

        for building in self._region.buildings.values():
            locations.append({
                "id": building.id,
                "name": building.name,
                "type": "building",
                "building_type": building.building_type,
                "parent": None,
            })
            for room in building.rooms.values():
                locations.append({
                    "id": room.id,
                    "name": room.name,
                    "type": "room",
                    "room_type": room.room_type,
                    "parent": building.id,
                })

        for area in self._region.outdoor_areas.values():
            locations.append({
                "id": area.id,
                "name": area.name,
                "type": "street" if area.is_street else "outdoor",
                "area_type": area.area_type,
                "parent": None,
                "road_name": area.road_name,
            })

        return locations

    def get_container_def(self, container_id: str) -> ContainerDef | None:
        """Get container definition by ID (searches all rooms)."""
        return self._region.get_container_def(container_id)

    def get_room_for_container(self, container_id: str) -> Room | None:
        """Find which room contains a container."""
        return self._region.get_room_for_container(container_id)

    # ========== Door Queries ==========

    def get_door(self, door_id: str) -> DoorDef | None:
        """Get door definition by ID."""
        return self._region.get_door(door_id)

    def get_doors_for_room(self, room_id: str) -> list[DoorDef]:
        """Get all doors connected to a room."""
        return self._region.get_doors_for_room(room_id)

    def get_door_between(self, room_a: str, room_b: str) -> DoorDef | None:
        """Get door connecting two rooms, if any."""
        return self._region.get_door_between(room_a, room_b)

    # ========== Border Queries (边界查询) ==========

    def get_border(self, border_id: str) -> BorderZone | None:
        """Get border zone by ID."""
        return self._region.borders.get(border_id)

    def list_borders(self, border_type: BorderType | None = None) -> list[BorderZone]:
        """List all borders, optionally filtered by type."""
        borders = list(self._region.borders.values())
        if border_type is not None:
            borders = [b for b in borders if b.border_type == border_type]
        return borders

    def get_border_between_locations(
        self, loc_a: str, loc_b: str,
    ) -> BorderZone | None:
        """Find a border that separates two locations (one on each side)."""
        for border in self._region.borders.values():
            a_in_a = loc_a in border.side_a
            a_in_b = loc_a in border.side_b
            b_in_a = loc_b in border.side_a
            b_in_b = loc_b in border.side_b
            if (a_in_a and b_in_b) or (a_in_b and b_in_a):
                return border
        return None

    def get_border_side(self, border_id: str, location_id: str) -> str | None:
        """Determine which side of a border a location is on. Returns 'a', 'b', or None."""
        border = self._region.borders.get(border_id)
        if not border:
            return None
        if location_id in border.side_a:
            return "a"
        if location_id in border.side_b:
            return "b"
        return None

    def locations_on_same_side(self, border_id: str, loc_a: str, loc_b: str) -> bool | None:
        """Check if two locations are on the same side of a border. None if either not in border."""
        side_a = self.get_border_side(border_id, loc_a)
        side_b = self.get_border_side(border_id, loc_b)
        if side_a is None or side_b is None:
            return None
        return side_a == side_b

    # ========== Spatial Queries ==========

    def find_location_at(self, coord: Coord) -> str | None:
        """Find which location contains a coordinate."""
        # Check rooms first (most specific)
        for building in self._region.buildings.values():
            for room in building.rooms.values():
                if room.polygon.contains(coord):
                    return room.id
        # Check buildings
        for building in self._region.buildings.values():
            if building.polygon.contains(coord):
                return building.id
        # Check outdoor areas
        for area in self._region.outdoor_areas.values():
            if area.polygon.contains(coord):
                return area.id
        return None

    def distance(self, from_coord: Coord, to_coord: Coord) -> float:
        """Euclidean distance between two coordinates."""
        return from_coord.distance_to(to_coord)

    def distance_between(self, from_id: str, to_id: str) -> float | None:
        """Distance between centers of two locations."""
        from_center = self.get_center(from_id)
        to_center = self.get_center(to_id)
        if from_center is None or to_center is None:
            return None
        return from_center.distance_to(to_center)

    def locations_within_radius(
        self, center: Coord, radius: float,
    ) -> list[tuple[str, float]]:
        """
        Find all locations whose center is within radius of a point.

        Returns list of (location_id, distance) sorted by distance.
        """
        results: list[tuple[str, float]] = []

        for building in self._region.buildings.values():
            d = building.center.distance_to(center)
            if d <= radius:
                results.append((building.id, d))

        for area in self._region.outdoor_areas.values():
            d = area.center.distance_to(center)
            if d <= radius:
                results.append((area.id, d))

        results.sort(key=lambda x: x[1])
        return results

    def locations_within_radius_of(
        self, location_id: str, radius: float,
    ) -> list[tuple[str, float]]:
        """Find all locations within radius of another location's center."""
        center = self.get_center(location_id)
        if center is None:
            return []
        return [
            (lid, d) for lid, d in self.locations_within_radius(center, radius)
            if lid != location_id
        ]

    # ========== Line of Sight ==========

    def can_see(self, from_coord: Coord, to_coord: Coord) -> tuple[bool, list[str]]:
        """
        Check line of sight between two points.
        Returns (can_see, list of blocking obstacle IDs).
        """
        obstacles: list[str] = []
        for building in self._region.buildings.values():
            if self._line_intersects_polygon(from_coord, to_coord, building.polygon):
                from_inside = building.polygon.contains(from_coord)
                to_inside = building.polygon.contains(to_coord)
                if not (from_inside and to_inside):
                    obstacles.append(building.id)
        for area in self._region.outdoor_areas.values():
            if area.vegetation_density > 0.7:
                if self._line_intersects_polygon(from_coord, to_coord, area.polygon):
                    obstacles.append(area.id)
        return len(obstacles) == 0, obstacles

    # ========== Sound Propagation ==========

    def sound_attenuation(self, from_coord: Coord, to_coord: Coord) -> float:
        """
        Calculate sound attenuation between two points.
        Returns factor from 0.0 (silent) to 1.0 (full volume).
        """
        dist = from_coord.distance_to(to_coord)
        base = min(1.0, 10.0 / max(1.0, dist))

        factor = 1.0
        for building in self._region.buildings.values():
            if self._line_intersects_polygon(from_coord, to_coord, building.polygon):
                from_in = building.polygon.contains(from_coord)
                to_in = building.polygon.contains(to_coord)
                if not (from_in and to_in):
                    factor *= (1.0 - building.exterior_material.sound_absorption)

        return base * factor

    # ========== Pathfinding ==========

    def find_path(self, from_id: str, to_id: str) -> tuple[bool, list[str], float]:
        """
        Find shortest path between two locations.
        Returns (success, path as list of location IDs, total distance).
        """
        if from_id == to_id:
            return True, [from_id], 0.0

        if from_id not in self._connection_graph:
            return False, [], 0.0

        # A* search
        open_set: list[tuple[float, int, str]] = [(0, 0, from_id)]
        came_from: dict[str, tuple[str, float]] = {}
        g_score: dict[str, float] = {from_id: 0}
        counter = 0

        while open_set:
            _, _, current = heapq.heappop(open_set)
            if current == to_id:
                path = [current]
                total_dist = g_score[current]
                while current in came_from:
                    current, _ = came_from[current]
                    path.append(current)
                path.reverse()
                return True, path, total_dist

            for neighbor, cost in self._connection_graph.get(current, []):
                tentative = g_score[current] + cost
                if neighbor not in g_score or tentative < g_score[neighbor]:
                    came_from[neighbor] = (current, cost)
                    g_score[neighbor] = tentative
                    h = self._heuristic(neighbor, to_id)
                    counter += 1
                    heapq.heappush(open_set, (tentative + h, counter, neighbor))

        return False, [], 0.0

    def get_connections(self, location_id: str) -> list[tuple[str, float]]:
        """Get all connections from a location as (neighbor_id, distance)."""
        return self._connection_graph.get(location_id, [])

    def are_adjacent(self, a: str, b: str) -> bool:
        """Check if two locations are directly connected."""
        return any(n == b for n, _ in self.get_connections(a))

    # ========== Serialization ==========

    def to_dict(self) -> dict:
        """Export as dictionary."""
        return self._region.model_dump(mode="json")

    def to_json(self, path: str | Path) -> None:
        """Save to JSON file."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    # ========== Private Methods ==========

    def _build_graph(self) -> dict[str, list[tuple[str, float]]]:
        """Build adjacency list from connections."""
        graph: dict[str, list[tuple[str, float]]] = {}
        for conn in self._region.connections:
            if conn.from_id not in graph:
                graph[conn.from_id] = []
            graph[conn.from_id].append((conn.to_id, conn.distance))
            if conn.bidirectional:
                if conn.to_id not in graph:
                    graph[conn.to_id] = []
                graph[conn.to_id].append((conn.from_id, conn.distance))
        return graph

    def _heuristic(self, from_id: str, to_id: str) -> float:
        """A* heuristic: straight-line distance."""
        a = self.get_center(from_id)
        b = self.get_center(to_id)
        return a.distance_to(b) if a and b else 0.0

    def _line_intersects_polygon(self, p1: Coord, p2: Coord, poly: Polygon) -> bool:
        """Check if line segment intersects polygon edges."""
        verts = poly.vertices
        n = len(verts)
        for i in range(n):
            if self._segments_intersect(p1, p2, verts[i], verts[(i + 1) % n]):
                return True
        return False

    @staticmethod
    def _segments_intersect(a1: Coord, a2: Coord, b1: Coord, b2: Coord) -> bool:
        """Check if two line segments intersect."""
        def ccw(p: Coord, q: Coord, r: Coord) -> bool:
            return (r.y - p.y) * (q.x - p.x) > (q.y - p.y) * (r.x - p.x)
        return ccw(a1, b1, b2) != ccw(a2, b1, b2) and ccw(a1, a2, b1) != ccw(a1, a2, b2)
