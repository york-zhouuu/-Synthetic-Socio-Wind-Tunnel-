"""
Atlas Data Models - Immutable geographic structures for community simulation.

These models define the physical reality of an urban community:
- Buildings with functional types (cafe, residential, library...)
- Outdoor areas with area types (park, plaza, street segment...)
- Connections between locations (paths, entrances, intersections)
- Border zones representing social/physical/informational boundaries

Key principles:
- Immutable after loading (frozen Pydantic models)
- Observer-independent (physics is the same for everyone)
- All queries go through the Atlas service
"""

from __future__ import annotations
from enum import Enum
from pydantic import BaseModel, Field

# Import core types and re-export for backward compatibility
from synthetic_socio_wind_tunnel.core.types import Coord, Polygon

__all__ = [
    "Coord", "Polygon",  # Re-exported from core
    "Material", "ActivityAffordance", "EntrySignals", "ContainerDef",
    "Room", "Building", "OutdoorArea", "Connection", "DoorDef", "Region",
    "BorderType", "BorderZone",
]


class Material(str, Enum):
    """Physical materials affecting sound/light propagation."""
    WOOD = "wood"
    STONE = "stone"
    GLASS = "glass"
    BRICK = "brick"
    METAL = "metal"
    FABRIC = "fabric"
    VEGETATION = "vegetation"
    CONCRETE = "concrete"
    ASPHALT = "asphalt"

    @property
    def sound_absorption(self) -> float:
        """How much this material absorbs sound (0=none, 1=full)."""
        return {
            Material.GLASS: 0.1,
            Material.WOOD: 0.3,
            Material.FABRIC: 0.5,
            Material.VEGETATION: 0.4,
            Material.BRICK: 0.6,
            Material.STONE: 0.7,
            Material.METAL: 0.8,
            Material.CONCRETE: 0.7,
            Material.ASPHALT: 0.5,
        }.get(self, 0.5)

    @property
    def light_transmission(self) -> float:
        """How much light passes through (0=opaque, 1=transparent)."""
        return {
            Material.GLASS: 0.9,
            Material.FABRIC: 0.2,
            Material.VEGETATION: 0.3,
        }.get(self, 0.0)


# ============================================================
# Activity Affordance (空间功能性编码 — 这里能做什么)
# ============================================================

class ActivityAffordance(BaseModel):
    """
    What activities this space physically supports, and under what conditions.

    This is NOT a social judgment — it is a physical fact about what can happen here.
    The agent (LLM) decides whether those conditions match their situation.

    Example:
        ActivityAffordance(
            activity_type="buy_coffee",
            time_range=(7, 22),
            requires=("payment",),
            language_of_service=("English", "Mandarin"),
            description="Espresso bar, table service. Average drink ¥38.",
        )
    """
    activity_type: str  # buy_food, work, rest, socialize, exercise, transit, shop, buy_coffee
    time_range: tuple[int, int] = (0, 24)  # hours when available
    capacity: int | None = None  # max simultaneous occupants, None = unlimited
    requires: tuple[str, ...] = ()  # physical prerequisites: "payment", "membership", "reservation"
    language_of_service: tuple[str, ...] = ()  # languages staff can serve in
    description: str = ""  # non-judgmental factual description

    model_config = {"frozen": True}


# ============================================================
# Entry Signals (从外部可观察到的信息)
# ============================================================

class EntrySignals(BaseModel):
    """
    What an agent can observe from outside before deciding to enter.

    These are physical, observable facts — NOT social judgments.
    The agent (LLM) interprets these signals based on their own background.

    Example:
        EntrySignals(
            visible_from_street=("glass facade", "people with laptops inside", "espresso machine"),
            signage=("SUNRISE CAFÉ", "Wi-Fi Available", "English menu posted outside"),
            price_visible="Coffee ¥35–48",
            facade_description="Modern glass storefront, chalk menu board in English and Mandarin, "
                               "bright interior with pendant lights.",
        )
    """
    visible_from_street: tuple[str, ...] = ()  # what you can see through windows / from entrance
    signage: tuple[str, ...] = ()  # text visible on signs, menus, boards
    price_visible: str | None = None  # price info legible from outside
    facade_description: str = ""  # physical description of exterior

    model_config = {"frozen": True}


# ============================================================
# Container (保留，供室内细节按需生成使用)
# ============================================================

class ContainerDef(BaseModel):
    """
    Definition of a container (furniture that holds items).

    This is the STATIC definition in Atlas - what the container IS.
    The DYNAMIC state (open/locked/examined) is in Ledger.ContainerState.
    """
    container_id: str
    name: str
    container_type: str  # "desk", "drawer", "bookshelf", "cabinet", "box"

    # Spatial budget for contents
    item_capacity: int = 5
    surface_capacity: int = 3

    # Interaction properties
    can_lock: bool = False
    lock_key_id: str | None = None
    search_difficulty: float = 0.0  # 0-1

    # Nested containers (e.g., desk has drawers)
    sub_containers: tuple[str, ...] = ()

    model_config = {"frozen": True}


# ============================================================
# Room (建筑内部空间，按需生成)
# ============================================================

class Room(BaseModel):
    """A room within a building. Pure geometry, no state."""
    id: str
    name: str
    polygon: Polygon
    room_type: str = "generic"  # lobby, office, kitchen, bedroom, storage...
    floor: int = 0
    ceiling_height: float = 2.8
    floor_material: Material = Material.WOOD
    wall_material: Material = Material.BRICK
    has_windows: bool = True
    connected_rooms: frozenset[str] = Field(default_factory=frozenset)

    # Container definitions - WHAT containers exist (static)
    containers: dict[str, ContainerDef] = Field(default_factory=dict)

    # Ambient properties affecting perception
    typical_lighting: str = "normal"  # "dark", "dim", "normal", "bright"
    typical_sounds: tuple[str, ...] = ()
    typical_smells: tuple[str, ...] = ()

    model_config = {"frozen": True}

    @property
    def center(self) -> Coord:
        return self.polygon.center

    @property
    def total_item_capacity(self) -> int:
        """Total items this room can hold across all containers."""
        return sum(c.item_capacity for c in self.containers.values())


class Building(BaseModel):
    """A building in the community."""
    id: str
    name: str
    polygon: Polygon

    # Functional classification
    building_type: str = "generic"  # residential, cafe, library, shop, school, office...
    osm_tags: dict[str, str] = Field(default_factory=dict)
    description: str = ""

    # Physical properties
    floors: int = 1
    exterior_material: Material = Material.BRICK
    entrance_coord: Coord | None = None

    # Rooms (may be empty initially, generated on-demand via CollapseService)
    rooms: dict[str, Room] = Field(default_factory=dict)

    # Activity schedule (24h format, None = always accessible)
    active_hours: tuple[int, int] | None = None  # e.g. (7, 22) = 7:00-22:00

    # Ambient properties for perception
    typical_sounds: tuple[str, ...] = ()
    typical_smells: tuple[str, ...] = ()

    # What this space affords (physical activities possible here)
    affordances: tuple[ActivityAffordance, ...] = Field(default_factory=tuple)

    # What is observable from outside before entering
    entry_signals: EntrySignals = Field(default_factory=EntrySignals)

    model_config = {"frozen": True}

    @property
    def center(self) -> Coord:
        return self.polygon.center


class OutdoorArea(BaseModel):
    """
    An outdoor area: park, plaza, street segment, or other open space.

    Street segments are the key innovation — roads are modeled as walkable
    OutdoorAreas so agents can encounter each other while traveling.
    """
    id: str
    name: str
    polygon: Polygon

    # Type classification
    area_type: str = "park"  # park, plaza, street, playground, garden, parking
    osm_tags: dict[str, str] = Field(default_factory=dict)
    description: str = ""

    # Physical properties
    surface: str = "grass"  # grass, asphalt, concrete, cobblestone, gravel
    vegetation_density: float = 0.3  # 0-1, affects visibility

    # Street-specific fields (only relevant when area_type == "street")
    road_name: str | None = None  # e.g. "Main Street"
    segment_index: int | None = None  # position in the road's segment sequence

    # Ambient properties for perception
    typical_sounds: tuple[str, ...] = ()
    typical_smells: tuple[str, ...] = ()

    # What this space affords (physical activities possible here)
    affordances: tuple[ActivityAffordance, ...] = Field(default_factory=tuple)

    # What is observable from outside / passing by
    entry_signals: EntrySignals = Field(default_factory=EntrySignals)

    model_config = {"frozen": True}

    @property
    def center(self) -> Coord:
        return self.polygon.center

    @property
    def is_street(self) -> bool:
        return self.area_type == "street"


class Connection(BaseModel):
    """Physical connection between two locations."""
    from_id: str
    to_id: str
    path_type: str = "path"  # path, road, entrance, intersection, door, stairs
    distance: float
    bidirectional: bool = True

    model_config = {"frozen": True}


class DoorDef(BaseModel):
    """
    Definition of a door between two rooms.

    This is the STATIC definition in Atlas - what the door IS.
    The DYNAMIC state (open/locked) is in Ledger.DoorState.
    """
    door_id: str
    from_room: str
    to_room: str
    can_lock: bool = False
    lock_key_id: str | None = None

    model_config = {"frozen": True}


# ============================================================
# Border Zone (社会/物理/信息边界)
# ============================================================

class BorderType(str, Enum):
    """Types of boundaries in the community."""
    PHYSICAL = "physical"          # walls, fences, roads, terrain
    SOCIAL = "social"              # class, culture, community rules
    INFORMATIONAL = "informational"  # information silos, attention gaps


class BorderZone(BaseModel):
    """
    A boundary between areas that affects movement and social interaction.

    Borders are the core research object — experiments test how digital
    interventions can strengthen, weaken, or dissolve these borders.

    Example:
        BorderZone(
            border_id="railway_divide",
            name="Railway Divide",
            border_type=BorderType.PHYSICAL,
            side_a=("block_a_seg_1", "block_a_seg_2", "house_1"),
            side_b=("block_b_seg_1", "block_b_seg_2", "shop_1"),
            permeability=0.2,
            crossing_connections=("railway_underpass",),
            description="The railway line divides the north and south neighborhoods.",
        )
    """
    border_id: str
    name: str
    border_type: BorderType
    side_a: tuple[str, ...] = ()  # location IDs on side A
    side_b: tuple[str, ...] = ()  # location IDs on side B
    permeability: float = 0.0  # 0.0 = impassable, 1.0 = fully open
    crossing_connections: tuple[str, ...] = ()  # Connection IDs that cross this border
    description: str = ""

    model_config = {"frozen": True}


# ============================================================
# Region (根数据结构)
# ============================================================

class Region(BaseModel):
    """Complete static map data for a region. The root Atlas data structure."""
    id: str
    name: str
    bounds_min: Coord
    bounds_max: Coord
    buildings: dict[str, Building] = Field(default_factory=dict)
    outdoor_areas: dict[str, OutdoorArea] = Field(default_factory=dict)
    connections: tuple[Connection, ...] = Field(default_factory=tuple)
    doors: dict[str, DoorDef] = Field(default_factory=dict)
    borders: dict[str, BorderZone] = Field(default_factory=dict)

    model_config = {"frozen": True}

    def get_location(self, location_id: str) -> Building | OutdoorArea | Room | None:
        """Get any location by ID."""
        if location_id in self.buildings:
            return self.buildings[location_id]
        if location_id in self.outdoor_areas:
            return self.outdoor_areas[location_id]
        for building in self.buildings.values():
            if location_id in building.rooms:
                return building.rooms[location_id]
        return None

    def get_location_center(self, location_id: str) -> Coord | None:
        """Get center of any location."""
        loc = self.get_location(location_id)
        if loc is None:
            return None
        if hasattr(loc, "center"):
            return loc.center
        if hasattr(loc, "polygon"):
            return loc.polygon.center
        return None

    def get_room(self, room_id: str) -> Room | None:
        """Find a room by ID."""
        for building in self.buildings.values():
            if room_id in building.rooms:
                return building.rooms[room_id]
        return None

    def get_container_def(self, container_id: str) -> ContainerDef | None:
        """Find a container definition anywhere in the region."""
        for building in self.buildings.values():
            for room in building.rooms.values():
                if container_id in room.containers:
                    return room.containers[container_id]
        return None

    def get_room_for_container(self, container_id: str) -> Room | None:
        """Find which room contains a container."""
        for building in self.buildings.values():
            for room in building.rooms.values():
                if container_id in room.containers:
                    return room
        return None

    def get_door(self, door_id: str) -> DoorDef | None:
        """Get a door definition by ID."""
        return self.doors.get(door_id)

    def get_doors_for_room(self, room_id: str) -> list[DoorDef]:
        """Get all doors connected to a room."""
        return [
            door for door in self.doors.values()
            if door.from_room == room_id or door.to_room == room_id
        ]

    def get_door_between(self, room_a: str, room_b: str) -> DoorDef | None:
        """Get door connecting two rooms, if any."""
        for door in self.doors.values():
            if (door.from_room == room_a and door.to_room == room_b) or \
               (door.from_room == room_b and door.to_room == room_a):
                return door
        return None
