"""
Atlas Data Models - Immutable geographic structures.

These models define the physical reality of the game world.
They are:
- Immutable after loading
- Observer-independent (physics is the same for everyone)
- Pure geometry and materials (no descriptions, no state)

Key principle: Atlas models have NO behavior, only data.
All queries go through the Atlas service.
"""

from __future__ import annotations
from enum import Enum
from pydantic import BaseModel, Field

# Import core types and re-export for backward compatibility
from synthetic_socio_wind_tunnel.core.types import Coord, Polygon

__all__ = [
    "Coord", "Polygon",  # Re-exported from core
    "Material", "SlotSize", "FurnitureSlot", "ContainerDef",
    "Room", "Building", "OutdoorArea", "Connection", "DoorDef", "Region",
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
# 空间预算系统 (Spatial Budget System)
# ============================================================

class SlotSize(str, Enum):
    """Furniture slot sizes."""
    LARGE = "large"      # Desk, bookshelf, bed
    MEDIUM = "medium"    # Chair, small table
    SMALL = "small"      # Lamp, vase
    SURFACE = "surface"  # Items on surfaces (unlimited conceptually)


class FurnitureSlot(BaseModel):
    """
    A slot where furniture can be placed.

    Part of the Spatial Budget System - limits what can exist in a room.
    """
    slot_id: str
    size: SlotSize
    position_hint: str = "any"  # "corner", "wall", "center", "window"
    suitable_for: tuple[str, ...] = ()  # "desk", "bookshelf", etc.

    model_config = {"frozen": True}


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
    item_capacity: int = 5          # Max number of items
    surface_capacity: int = 3       # Items that can sit on top

    # Interaction properties
    can_lock: bool = False
    lock_key_id: str | None = None  # Item ID that can unlock this container
    search_difficulty: float = 0.0  # 0-1, skill needed to search thoroughly

    # Nested containers (e.g., desk has drawers)
    sub_containers: tuple[str, ...] = ()  # IDs of nested containers

    model_config = {"frozen": True}


# ============================================================
# Room with Spatial Budget
# ============================================================

class Room(BaseModel):
    """A room within a building. Pure geometry, no state."""
    id: str
    name: str
    polygon: Polygon
    floor: int = 0
    ceiling_height: float = 2.8
    floor_material: Material = Material.WOOD
    wall_material: Material = Material.BRICK
    has_windows: bool = True
    connected_rooms: frozenset[str] = Field(default_factory=frozenset)

    # ===== Spatial Budget System =====
    # Furniture slots define WHERE things can be placed
    furniture_slots: dict[str, FurnitureSlot] = Field(default_factory=dict)

    # Container definitions - WHAT containers exist (static)
    # The actual state (filled, locked) is in Ledger
    containers: dict[str, ContainerDef] = Field(default_factory=dict)

    # Ambient properties affecting perception
    typical_lighting: str = "normal"  # "dark", "dim", "normal", "bright"
    typical_sounds: tuple[str, ...] = ()  # "clock_ticking", "traffic"
    typical_smells: tuple[str, ...] = ()  # "old_books", "coffee"

    model_config = {"frozen": True}

    @property
    def center(self) -> Coord:
        return self.polygon.center

    @property
    def total_item_capacity(self) -> int:
        """Total items this room can hold across all containers."""
        return sum(c.item_capacity for c in self.containers.values())


class Building(BaseModel):
    """A building structure containing rooms."""
    id: str
    name: str
    polygon: Polygon
    floors: int = 1
    exterior_material: Material = Material.BRICK
    rooms: dict[str, Room] = Field(default_factory=dict)
    entrance_coord: Coord | None = None

    model_config = {"frozen": True}

    @property
    def center(self) -> Coord:
        return self.polygon.center


class OutdoorArea(BaseModel):
    """An outdoor area (park, plaza, garden)."""
    id: str
    name: str
    polygon: Polygon
    surface: str = "grass"
    vegetation_density: float = 0.3  # 0-1, affects visibility

    model_config = {"frozen": True}

    @property
    def center(self) -> Coord:
        return self.polygon.center


class Connection(BaseModel):
    """Physical connection between two locations."""
    from_id: str
    to_id: str
    path_type: str = "path"  # path, road, door, stairs
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
    lock_key_id: str | None = None  # Item ID that can unlock this door

    model_config = {"frozen": True}


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
