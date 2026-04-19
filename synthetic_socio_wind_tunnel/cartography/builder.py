"""
RegionBuilder - Programmatic map construction for community simulation.

Fluent API for building maps in code, with support for:
- Buildings with functional types
- Street segments
- Open spaces (parks, plazas)
- Connections (auto-distance or manual)
- Border zones

Completely separate from runtime — outputs Atlas data.
"""

from __future__ import annotations

from synthetic_socio_wind_tunnel.atlas.models import (
    Region,
    Building,
    Room,
    OutdoorArea,
    Connection,
    Coord,
    Polygon,
    Material,
    ActivityAffordance,
    EntrySignals,
    ContainerDef,
    BorderType,
    BorderZone,
)


class RegionBuilder:
    """
    Fluent builder for constructing map regions.

    Example:
        region = (
            RegionBuilder("my_community", "My Community")
            .add_building("cafe", "Sunrise Café", building_type="cafe")
                .polygon([(0,0), (10,0), (10,8), (0,8)])
                .end_building()
            .add_street("main_st_1", "Main Street (1)", road_name="Main Street")
                .polygon([(12,0), (30,0), (30,6), (12,6)])
                .segment_index(0)
                .end_outdoor()
            .add_outdoor("park", "Central Park", area_type="park")
                .polygon([(35,0), (55,0), (55,20), (35,20)])
                .end_outdoor()
            .connect("cafe", "main_st_1", "entrance")
            .connect("main_st_1", "park", "entrance")
            .add_border("railway", "Railway Divide", BorderType.PHYSICAL)
                .border_sides(["cafe", "main_st_1"], ["park"])
                .border_permeability(0.2)
                .end_border()
            .build()
        )
    """

    def __init__(self, region_id: str, region_name: str):
        self._region_id = region_id
        self._region_name = region_name
        self._buildings: dict[str, dict] = {}
        self._outdoor_areas: dict[str, dict] = {}
        self._connections: list[dict] = []
        self._borders: dict[str, dict] = {}

        # Current context
        self._current_building: str | None = None
        self._current_room: str | None = None
        self._current_outdoor: str | None = None
        self._current_border: str | None = None

    # ========== Building ==========

    def add_building(
        self,
        building_id: str,
        name: str,
        building_type: str = "generic",
    ) -> "RegionBuilder":
        """Start adding a building."""
        self._finalize_current()
        self._current_building = building_id
        self._buildings[building_id] = {
            "id": building_id,
            "name": name,
            "polygon": [],
            "material": Material.BRICK,
            "building_type": building_type,
            "osm_tags": {},
            "description": "",
            "floors": 1,
            "rooms": {},
            "entrance": None,
            "active_hours": None,
            "typical_sounds": (),
            "typical_smells": (),
            "affordances": [],
            "entry_signals": None,
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

    def building_description(self, desc: str) -> "RegionBuilder":
        """Set building description."""
        if self._current_building:
            self._buildings[self._current_building]["description"] = desc
        return self

    def active_hours(self, start: int, end: int) -> "RegionBuilder":
        """Set active hours (24h format)."""
        if self._current_building:
            self._buildings[self._current_building]["active_hours"] = (start, end)
        return self

    def osm_tags(self, tags: dict[str, str]) -> "RegionBuilder":
        """Set OSM tags on current building or outdoor area."""
        if self._current_building:
            self._buildings[self._current_building]["osm_tags"] = tags
        elif self._current_outdoor:
            self._outdoor_areas[self._current_outdoor]["osm_tags"] = tags
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

    def sounds(self, *sounds: str) -> "RegionBuilder":
        """Set typical sounds for current building or outdoor area."""
        if self._current_building:
            self._buildings[self._current_building]["typical_sounds"] = sounds
        elif self._current_outdoor:
            self._outdoor_areas[self._current_outdoor]["typical_sounds"] = sounds
        return self

    def smells(self, *smells: str) -> "RegionBuilder":
        """Set typical smells for current building or outdoor area."""
        if self._current_building:
            self._buildings[self._current_building]["typical_smells"] = smells
        elif self._current_outdoor:
            self._outdoor_areas[self._current_outdoor]["typical_smells"] = smells
        return self

    def entry_signals(
        self,
        visible_from_street: list[str] | tuple = (),
        signage: list[str] | tuple = (),
        price_visible: str | None = None,
        facade_description: str = "",
    ) -> "RegionBuilder":
        """Set what is observable from outside (street view) for current location."""
        data = {
            "visible_from_street": tuple(visible_from_street),
            "signage": tuple(signage),
            "price_visible": price_visible,
            "facade_description": facade_description,
        }
        if self._current_building:
            self._buildings[self._current_building]["entry_signals"] = data
        elif self._current_outdoor:
            self._outdoor_areas[self._current_outdoor]["entry_signals"] = data
        return self

    def add_affordance(
        self,
        activity_type: str,
        time_range: tuple[int, int] = (0, 24),
        capacity: int | None = None,
        requires: list[str] | tuple = (),
        language_of_service: list[str] | tuple = (),
        description: str = "",
    ) -> "RegionBuilder":
        """Add an activity affordance to the current building or outdoor area."""
        aff = ActivityAffordance(
            activity_type=activity_type,
            time_range=time_range,
            capacity=capacity,
            requires=tuple(requires),
            language_of_service=tuple(language_of_service),
            description=description,
        )
        if self._current_building:
            self._buildings[self._current_building]["affordances"].append(aff)
        elif self._current_outdoor:
            self._outdoor_areas[self._current_outdoor]["affordances"].append(aff)
        return self

    def end_building(self) -> "RegionBuilder":
        """Finish current building."""
        self._current_building = None
        self._current_room = None
        return self

    # ========== Room ==========

    def add_room(
        self, room_id: str, name: str, room_type: str = "generic",
    ) -> "RegionBuilder":
        """Add room to current building."""
        if not self._current_building:
            raise ValueError("No building context")
        self._current_room = room_id
        self._buildings[self._current_building]["rooms"][room_id] = {
            "id": room_id,
            "name": name,
            "room_type": room_type,
            "polygon": [],
            "floor": 0,
            "floor_material": Material.WOOD,
            "wall_material": Material.BRICK,
            "has_windows": True,
            "connected_rooms": set(),
            "containers": {},
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
        """Add containers by ID only (creates minimal ContainerDef)."""
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
        """Add a container with full ContainerDef specification."""
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

    def add_outdoor(
        self,
        area_id: str,
        name: str,
        area_type: str = "park",
    ) -> "RegionBuilder":
        """Add outdoor area (park, plaza, etc.)."""
        self._finalize_current()
        self._current_outdoor = area_id
        self._outdoor_areas[area_id] = {
            "id": area_id,
            "name": name,
            "polygon": [],
            "area_type": area_type,
            "osm_tags": {},
            "description": "",
            "surface": "grass",
            "vegetation": 0.3,
            "road_name": None,
            "segment_index": None,
            "typical_sounds": (),
            "typical_smells": (),
            "affordances": [],
            "entry_signals": None,
        }
        return self

    def add_street(
        self,
        seg_id: str,
        name: str,
        road_name: str | None = None,
    ) -> "RegionBuilder":
        """Add a street segment (convenience wrapper around add_outdoor)."""
        self.add_outdoor(seg_id, name, area_type="street")
        if self._current_outdoor:
            self._outdoor_areas[self._current_outdoor]["surface"] = "asphalt"
            self._outdoor_areas[self._current_outdoor]["vegetation"] = 0.0
            self._outdoor_areas[self._current_outdoor]["road_name"] = road_name
        return self

    def segment_index(self, index: int) -> "RegionBuilder":
        """Set segment index (for ordering segments on a road)."""
        if self._current_outdoor:
            self._outdoor_areas[self._current_outdoor]["segment_index"] = index
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

    def outdoor_description(self, desc: str) -> "RegionBuilder":
        """Set outdoor area description."""
        if self._current_outdoor:
            self._outdoor_areas[self._current_outdoor]["description"] = desc
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

    # ========== Border Zones ==========

    def add_border(
        self,
        border_id: str,
        name: str,
        border_type: BorderType,
    ) -> "RegionBuilder":
        """Start adding a border zone."""
        self._finalize_current()
        self._current_border = border_id
        self._borders[border_id] = {
            "border_id": border_id,
            "name": name,
            "border_type": border_type,
            "side_a": [],
            "side_b": [],
            "permeability": 0.0,
            "crossing_connections": [],
            "description": "",
        }
        return self

    def border_sides(
        self, side_a: list[str], side_b: list[str],
    ) -> "RegionBuilder":
        """Set locations on each side of the border."""
        if self._current_border:
            self._borders[self._current_border]["side_a"] = side_a
            self._borders[self._current_border]["side_b"] = side_b
        return self

    def border_permeability(self, value: float) -> "RegionBuilder":
        """Set border permeability (0=impassable, 1=fully open)."""
        if self._current_border:
            self._borders[self._current_border]["permeability"] = value
        return self

    def border_crossings(self, connection_ids: list[str]) -> "RegionBuilder":
        """Set which connections cross this border."""
        if self._current_border:
            self._borders[self._current_border]["crossing_connections"] = connection_ids
        return self

    def border_description(self, desc: str) -> "RegionBuilder":
        """Set border description."""
        if self._current_border:
            self._borders[self._current_border]["description"] = desc
        return self

    def end_border(self) -> "RegionBuilder":
        """Finish current border."""
        self._current_border = None
        return self

    # ========== Build ==========

    def _finalize_current(self) -> None:
        """Finalize any open context."""
        self._current_room = None
        self._current_building = None
        self._current_outdoor = None
        self._current_border = None

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
                    room_type=rdata["room_type"],
                    polygon=Polygon(vertices=tuple(rdata["polygon"])),
                    floor=rdata["floor"],
                    floor_material=rdata["floor_material"],
                    wall_material=rdata["wall_material"],
                    has_windows=rdata["has_windows"],
                    connected_rooms=frozenset(rdata["connected_rooms"]),
                    containers=dict(rdata["containers"]),
                )

            polygon = Polygon(vertices=tuple(bdata["polygon"]))
            es_data = bdata.get("entry_signals")
            buildings[bid] = Building(
                id=bid,
                name=bdata["name"],
                polygon=polygon,
                building_type=bdata["building_type"],
                osm_tags=bdata["osm_tags"],
                description=bdata["description"],
                exterior_material=bdata["material"],
                floors=bdata["floors"],
                rooms=rooms,
                entrance_coord=bdata["entrance"] or polygon.center,
                active_hours=bdata["active_hours"],
                typical_sounds=tuple(bdata.get("typical_sounds", ())),
                typical_smells=tuple(bdata.get("typical_smells", ())),
                affordances=tuple(bdata.get("affordances", [])),
                entry_signals=EntrySignals(**es_data) if es_data else EntrySignals(),
            )

        # Convert outdoor areas
        outdoor_areas: dict[str, OutdoorArea] = {}
        for aid, adata in self._outdoor_areas.items():
            es_data = adata.get("entry_signals")
            outdoor_areas[aid] = OutdoorArea(
                id=aid,
                name=adata["name"],
                polygon=Polygon(vertices=tuple(adata["polygon"])),
                area_type=adata["area_type"],
                osm_tags=adata["osm_tags"],
                description=adata["description"],
                surface=adata["surface"],
                vegetation_density=adata["vegetation"],
                road_name=adata["road_name"],
                segment_index=adata["segment_index"],
                typical_sounds=tuple(adata.get("typical_sounds", ())),
                typical_smells=tuple(adata.get("typical_smells", ())),
                affordances=tuple(adata.get("affordances", [])),
                entry_signals=EntrySignals(**es_data) if es_data else EntrySignals(),
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

        # Build borders
        borders: dict[str, BorderZone] = {}
        for brd_id, brd_data in self._borders.items():
            borders[brd_id] = BorderZone(
                border_id=brd_data["border_id"],
                name=brd_data["name"],
                border_type=brd_data["border_type"],
                side_a=tuple(brd_data["side_a"]),
                side_b=tuple(brd_data["side_b"]),
                permeability=brd_data["permeability"],
                crossing_connections=tuple(brd_data["crossing_connections"]),
                description=brd_data["description"],
            )

        return Region(
            id=self._region_id,
            name=self._region_name,
            bounds_min=bounds_min,
            bounds_max=bounds_max,
            buildings=buildings,
            outdoor_areas=outdoor_areas,
            connections=tuple(connections),
            borders=borders,
        )
