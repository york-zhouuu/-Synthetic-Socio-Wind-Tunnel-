"""
RegionBuilder - Programmatic map construction.

Fluent API for building maps in code.
Completely separate from runtime - outputs Atlas data.
"""

from __future__ import annotations
from typing import Any

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
)


class RegionBuilder:
    """
    Fluent builder for constructing map regions.

    Example:
        region = (
            RegionBuilder("maple_creek", "Maple Creek")
            .add_building("library", "Public Library")
                .material(Material.BRICK)
                .polygon([(0,0), (20,0), (20,15), (0,15)])
                .add_room("lobby", "Lobby")
                    .room_polygon([(0,0), (10,0), (10,15), (0,15)])
                    .containers(["desk", "bookshelf"])
                    .end_room()
                .end_building()
            .add_outdoor("park", "Memorial Park")
                .polygon([(30,0), (60,0), (60,30), (30,30)])
                .surface("grass")
                .end_outdoor()
            .connect("library", "park", distance=15.0)
            .build()
        )
    """

    def __init__(self, region_id: str, region_name: str):
        self._region_id = region_id
        self._region_name = region_name
        self._buildings: dict[str, dict] = {}
        self._outdoor_areas: dict[str, dict] = {}
        self._connections: list[dict] = []

        # Current context
        self._current_building: str | None = None
        self._current_room: str | None = None
        self._current_outdoor: str | None = None

    # ========== Building ==========

    def add_building(self, building_id: str, name: str) -> "RegionBuilder":
        """Start adding a building."""
        self._finalize_current()
        self._current_building = building_id
        self._buildings[building_id] = {
            "id": building_id,
            "name": name,
            "polygon": [],
            "material": Material.BRICK,
            "floors": 1,
            "rooms": {},
            "entrance": None,
        }
        return self

    def material(self, mat: Material) -> "RegionBuilder":
        """Set building material."""
        if self._current_building:
            self._buildings[self._current_building]["material"] = mat
        return self

    def floors(self, n: int) -> "RegionBuilder":
        """Set number of floors."""
        if self._current_building:
            self._buildings[self._current_building]["floors"] = n
        return self

    def polygon(self, vertices: list[tuple[float, float]]) -> "RegionBuilder":
        """Set polygon for current building or outdoor area."""
        coords = [Coord(x=v[0], y=v[1]) for v in vertices]
        if self._current_building:
            self._buildings[self._current_building]["polygon"] = coords
        elif self._current_outdoor:
            self._outdoor_areas[self._current_outdoor]["polygon"] = coords
        return self

    def entrance(self, coord: tuple[float, float]) -> "RegionBuilder":
        """Set entrance coordinate."""
        if self._current_building:
            self._buildings[self._current_building]["entrance"] = Coord(x=coord[0], y=coord[1])
        return self

    def end_building(self) -> "RegionBuilder":
        """Finish current building."""
        self._current_building = None
        self._current_room = None
        return self

    # ========== Room ==========

    def add_room(self, room_id: str, name: str) -> "RegionBuilder":
        """Add room to current building."""
        if not self._current_building:
            raise ValueError("No building context")
        self._current_room = room_id
        self._buildings[self._current_building]["rooms"][room_id] = {
            "id": room_id,
            "name": name,
            "polygon": [],
            "floor": 0,
            "floor_material": Material.WOOD,
            "wall_material": Material.BRICK,
            "has_windows": True,
            "connected_rooms": set(),
            "containers": {},  # dict[str, ContainerDef]
        }
        return self

    def room_polygon(self, vertices: list[tuple[float, float]]) -> "RegionBuilder":
        """Set room polygon."""
        if self._current_building and self._current_room:
            coords = [Coord(x=v[0], y=v[1]) for v in vertices]
            self._buildings[self._current_building]["rooms"][self._current_room]["polygon"] = coords
        return self

    def room_floor(self, floor: int) -> "RegionBuilder":
        """Set room floor level."""
        if self._current_building and self._current_room:
            self._buildings[self._current_building]["rooms"][self._current_room]["floor"] = floor
        return self

    def connects_to(self, *room_ids: str) -> "RegionBuilder":
        """Add door connections to other rooms."""
        if self._current_building and self._current_room:
            room = self._buildings[self._current_building]["rooms"][self._current_room]
            room["connected_rooms"].update(room_ids)
        return self

    def containers(self, container_ids: list[str]) -> "RegionBuilder":
        """
        Add containers by ID only (creates minimal ContainerDef).

        For full ContainerDef control, use add_container() instead.
        """
        if self._current_building and self._current_room:
            room = self._buildings[self._current_building]["rooms"][self._current_room]
            for cid in container_ids:
                if cid not in room["containers"]:
                    room["containers"][cid] = ContainerDef(
                        container_id=cid,
                        name=cid.replace("_", " ").title(),
                        container_type="generic",
                    )
        return self

    def add_container(
        self,
        container_id: str,
        name: str,
        container_type: str,
        item_capacity: int = 5,
        surface_capacity: int = 3,
        can_lock: bool = False,
        search_difficulty: float = 0.0,
        sub_containers: tuple[str, ...] = (),
    ) -> "RegionBuilder":
        """
        Add a container with full ContainerDef specification.

        Args:
            container_id: Unique container ID
            name: Display name
            container_type: Type (desk, drawer, bookshelf, cabinet, box, etc.)
            item_capacity: Max items inside
            surface_capacity: Max items on surface
            can_lock: Whether container can be locked
            search_difficulty: Skill required for thorough search (0-1)
            sub_containers: IDs of nested containers
        """
        if self._current_building and self._current_room:
            room = self._buildings[self._current_building]["rooms"][self._current_room]
            room["containers"][container_id] = ContainerDef(
                container_id=container_id,
                name=name,
                container_type=container_type,
                item_capacity=item_capacity,
                surface_capacity=surface_capacity,
                can_lock=can_lock,
                search_difficulty=search_difficulty,
                sub_containers=sub_containers,
            )
        return self

    def end_room(self) -> "RegionBuilder":
        """Finish current room."""
        self._current_room = None
        return self

    # ========== Outdoor Area ==========

    def add_outdoor(self, area_id: str, name: str) -> "RegionBuilder":
        """Add outdoor area."""
        self._finalize_current()
        self._current_outdoor = area_id
        self._outdoor_areas[area_id] = {
            "id": area_id,
            "name": name,
            "polygon": [],
            "surface": "grass",
            "vegetation": 0.3,
        }
        return self

    def surface(self, surface: str) -> "RegionBuilder":
        """Set outdoor surface type."""
        if self._current_outdoor:
            self._outdoor_areas[self._current_outdoor]["surface"] = surface
        return self

    def vegetation(self, density: float) -> "RegionBuilder":
        """Set vegetation density (0-1)."""
        if self._current_outdoor:
            self._outdoor_areas[self._current_outdoor]["vegetation"] = density
        return self

    def end_outdoor(self) -> "RegionBuilder":
        """Finish current outdoor area."""
        self._current_outdoor = None
        return self

    # ========== Connections ==========

    def connect(
        self,
        from_id: str,
        to_id: str,
        path_type: str = "path",
        distance: float | None = None,
    ) -> "RegionBuilder":
        """Add connection between locations."""
        self._connections.append({
            "from_id": from_id,
            "to_id": to_id,
            "path_type": path_type,
            "distance": distance,
        })
        return self

    # ========== Build ==========

    def _finalize_current(self) -> None:
        """Finalize any open context."""
        self._current_room = None
        self._current_building = None
        self._current_outdoor = None

    def build(self) -> Region:
        """Build the final Region."""
        self._finalize_current()

        # Convert buildings
        buildings: dict[str, Building] = {}
        for bid, bdata in self._buildings.items():
            rooms: dict[str, Room] = {}
            for rid, rdata in bdata["rooms"].items():
                rooms[rid] = Room(
                    id=rid,
                    name=rdata["name"],
                    polygon=Polygon(vertices=tuple(rdata["polygon"])),
                    floor=rdata["floor"],
                    floor_material=rdata["floor_material"],
                    wall_material=rdata["wall_material"],
                    has_windows=rdata["has_windows"],
                    connected_rooms=frozenset(rdata["connected_rooms"]),
                    containers=dict(rdata["containers"]),  # dict[str, ContainerDef]
                )

            polygon = Polygon(vertices=tuple(bdata["polygon"]))
            buildings[bid] = Building(
                id=bid,
                name=bdata["name"],
                polygon=polygon,
                exterior_material=bdata["material"],
                floors=bdata["floors"],
                rooms=rooms,
                entrance_coord=bdata["entrance"] or polygon.center,
            )

        # Convert outdoor areas
        outdoor_areas: dict[str, OutdoorArea] = {}
        for aid, adata in self._outdoor_areas.items():
            outdoor_areas[aid] = OutdoorArea(
                id=aid,
                name=adata["name"],
                polygon=Polygon(vertices=tuple(adata["polygon"])),
                surface=adata["surface"],
                vegetation_density=adata["vegetation"],
            )

        # Calculate bounds
        all_coords = []
        for b in buildings.values():
            all_coords.extend(b.polygon.vertices)
        for a in outdoor_areas.values():
            all_coords.extend(a.polygon.vertices)

        if all_coords:
            bounds_min = Coord(
                x=min(c.x for c in all_coords),
                y=min(c.y for c in all_coords),
            )
            bounds_max = Coord(
                x=max(c.x for c in all_coords),
                y=max(c.y for c in all_coords),
            )
        else:
            bounds_min = bounds_max = Coord(x=0, y=0)

        # Build connections (calculate distances if needed)
        connections = []
        for conn in self._connections:
            distance = conn["distance"]
            if distance is None:
                from_loc = buildings.get(conn["from_id"]) or outdoor_areas.get(conn["from_id"])
                to_loc = buildings.get(conn["to_id"]) or outdoor_areas.get(conn["to_id"])
                if from_loc and to_loc:
                    distance = from_loc.center.distance_to(to_loc.center)
                else:
                    distance = 10.0

            connections.append(Connection(
                from_id=conn["from_id"],
                to_id=conn["to_id"],
                path_type=conn["path_type"],
                distance=distance,
            ))

        return Region(
            id=self._region_id,
            name=self._region_name,
            bounds_min=bounds_min,
            bounds_max=bounds_max,
            buildings=buildings,
            outdoor_areas=outdoor_areas,
            connections=tuple(connections),
        )
