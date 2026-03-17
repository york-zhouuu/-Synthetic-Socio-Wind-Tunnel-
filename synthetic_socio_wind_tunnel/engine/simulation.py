"""
SimulationService - The Physical Director (物理导演)

Handles all physical interactions:
- Entity movement
- Item manipulation
- Physical state changes (doors, switches)

Reads: Atlas (for validation), Ledger (for current state)
Writes: Ledger only

v0.4.0: Added structured error codes and event system
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from synthetic_socio_wind_tunnel.core.types import Coord
from synthetic_socio_wind_tunnel.core.errors import SimulationErrorCode, EventType
from synthetic_socio_wind_tunnel.core.events import (
    WorldEvent,
    create_movement_event,
    create_door_event,
    create_discovery_event,
)
from synthetic_socio_wind_tunnel.ledger.models import EntityState, ItemState

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.atlas import Atlas
    from synthetic_socio_wind_tunnel.ledger import Ledger


@dataclass
class SimulationResult:
    """
    Result of a simulation action.

    v0.4.0: Added error_code and events for Agent-friendly responses.
    """

    success: bool
    message: str = ""
    error_code: SimulationErrorCode = SimulationErrorCode.SUCCESS
    data: dict = field(default_factory=dict)
    events: list[WorldEvent] = field(default_factory=list)

    @classmethod
    def ok(cls, message: str = "Success", events: list[WorldEvent] | None = None, **data) -> "SimulationResult":
        return cls(
            success=True,
            message=message,
            error_code=SimulationErrorCode.SUCCESS,
            data=data,
            events=events or [],
        )

    @classmethod
    def fail(
        cls,
        message: str,
        error_code: SimulationErrorCode = SimulationErrorCode.UNKNOWN_ERROR,
        **data,
    ) -> "SimulationResult":
        return cls(
            success=False,
            message=message,
            error_code=error_code,
            data=data,
            events=[],
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "message": self.message,
            "error_code": self.error_code.value,
            "data": self.data,
            "events": [e.to_dict() for e in self.events],
        }


class SimulationService:
    """
    Physical simulation service.

    Handles movement, interactions, and physical state changes.
    All operations validate against Atlas (static rules) and
    check/modify Ledger (dynamic state).

    v0.4.0 Changes:
    - SimulationResult now includes error_code (SimulationErrorCode enum)
    - SimulationResult now includes events (list[WorldEvent])
    - Events describe side effects that other systems can react to

    Thread-safe if Ledger access is externally synchronized.
    """

    __slots__ = ("_atlas", "_ledger")

    def __init__(self, atlas: "Atlas", ledger: "Ledger"):
        """
        Initialize with data sources.

        Args:
            atlas: Read-only static map data
            ledger: Read-write dynamic state
        """
        self._atlas = atlas
        self._ledger = ledger

    # ========== Entity Movement ==========

    def move_entity(
        self,
        entity_id: str,
        to_location: str,
        position: Coord | None = None,
        activity: str | None = None,
    ) -> SimulationResult:
        """
        Move an entity to a new location.

        Args:
            entity_id: ID of entity to move
            to_location: Target location ID
            position: Exact position (uses center if None)
            activity: What entity is doing at new location

        Returns:
            SimulationResult with error_code and events
        """
        # Validate target location exists
        if self._atlas.get_location(to_location) is None:
            return SimulationResult.fail(
                f"Unknown location: {to_location}",
                SimulationErrorCode.LOCATION_NOT_FOUND,
                location_id=to_location,
            )

        # Get position
        if position is None:
            position = self._atlas.get_center(to_location)
            if position is None:
                return SimulationResult.fail(
                    f"Cannot find center of: {to_location}",
                    SimulationErrorCode.LOCATION_NOT_FOUND,
                )

        # Get current state or create new
        current = self._ledger.get_entity(entity_id)
        from_location = current.location_id if current else None

        # Check if already at location
        if from_location == to_location:
            return SimulationResult.fail(
                f"{entity_id} is already at {to_location}",
                SimulationErrorCode.ALREADY_AT_LOCATION,
            )

        # Create new state
        timestamp = self._ledger.current_time
        new_state = EntityState(
            entity_id=entity_id,
            location_id=to_location,
            position=position,
            activity=activity,
            arrived_at=timestamp,
        )

        # Write to ledger
        self._ledger.set_entity(new_state)

        # Record exploration (认知地图)
        is_new_discovery = self._ledger.add_explored_location(entity_id, to_location)

        # Generate events
        events = []
        if from_location:
            events = create_movement_event(
                actor_id=entity_id,
                from_location=from_location,
                to_location=to_location,
                timestamp=timestamp,
            )

        return SimulationResult.ok(
            f"Moved {entity_id} to {to_location}",
            events=events,
            from_location=from_location,
            to_location=to_location,
            is_new_discovery=is_new_discovery,
        )

    def set_entity_activity(self, entity_id: str, activity: str | None) -> SimulationResult:
        """Update what an entity is doing."""
        entity = self._ledger.get_entity(entity_id)
        if entity is None:
            return SimulationResult.fail(
                f"Entity not found: {entity_id}",
                SimulationErrorCode.ENTITY_NOT_FOUND,
            )

        # Create updated state (EntityState is immutable-ish)
        new_state = EntityState(
            entity_id=entity.entity_id,
            location_id=entity.location_id,
            position=entity.position,
            activity=activity,
            arrived_at=entity.arrived_at,
        )
        self._ledger.set_entity(new_state)

        return SimulationResult.ok(f"{entity_id} is now {activity or 'idle'}")

    def remove_entity(self, entity_id: str) -> SimulationResult:
        """Remove an entity from the world."""
        if self._ledger.remove_entity(entity_id):
            return SimulationResult.ok(f"Removed {entity_id}")
        return SimulationResult.fail(
            f"Entity not found: {entity_id}",
            SimulationErrorCode.ENTITY_NOT_FOUND,
        )

    # ========== Item Manipulation ==========

    def place_item(
        self,
        item_id: str,
        name: str,
        location_id: str,
        position: Coord | None = None,
        is_hidden: bool = False,
        discovery_skill: float = 0.0,
    ) -> SimulationResult:
        """
        Place a new item in the world.

        Args:
            item_id: Unique item ID
            name: Display name
            location_id: Where to place
            position: Exact position (uses center if None)
            is_hidden: Requires investigation to find
            discovery_skill: Skill threshold to notice
        """
        if self._atlas.get_location(location_id) is None:
            return SimulationResult.fail(
                f"Unknown location: {location_id}",
                SimulationErrorCode.LOCATION_NOT_FOUND,
            )

        if position is None:
            position = self._atlas.get_center(location_id)

        item = ItemState(
            item_id=item_id,
            name=name,
            location_id=location_id,
            position=position,
            is_hidden=is_hidden,
            discovery_skill=discovery_skill,
        )
        self._ledger.set_item(item)

        return SimulationResult.ok(f"Placed {name} at {location_id}")

    def move_item_to_location(
        self,
        item_id: str,
        location_id: str,
        position: Coord | None = None,
    ) -> SimulationResult:
        """Move item to a location."""
        item = self._ledger.get_item(item_id)
        if item is None:
            return SimulationResult.fail(
                f"Item not found: {item_id}",
                SimulationErrorCode.ITEM_NOT_FOUND,
            )

        if self._atlas.get_location(location_id) is None:
            return SimulationResult.fail(
                f"Unknown location: {location_id}",
                SimulationErrorCode.LOCATION_NOT_FOUND,
            )

        # Update item
        item.location_id = location_id
        item.container_id = None
        item.held_by = None
        item.position = position or self._atlas.get_center(location_id)
        self._ledger.set_item(item)

        return SimulationResult.ok(f"Moved {item_id} to {location_id}")

    def move_item_to_container(self, item_id: str, container_id: str) -> SimulationResult:
        """Move item into a container."""
        item = self._ledger.get_item(item_id)
        if item is None:
            return SimulationResult.fail(
                f"Item not found: {item_id}",
                SimulationErrorCode.ITEM_NOT_FOUND,
            )

        # Check container capacity
        container_def = self._atlas.get_container_def(container_id)
        if container_def:
            current_count = self._ledger.count_items_in(container_id)
            if current_count >= container_def.item_capacity:
                return SimulationResult.fail(
                    f"Container {container_id} is full",
                    SimulationErrorCode.CONTAINER_FULL,
                    container_id=container_id,
                    capacity=container_def.item_capacity,
                    current=current_count,
                )

        item.location_id = None
        item.container_id = container_id
        item.held_by = None
        item.position = None
        self._ledger.set_item(item)

        return SimulationResult.ok(f"Put {item_id} in {container_id}")

    def give_item_to_entity(self, item_id: str, entity_id: str) -> SimulationResult:
        """Give item to an entity."""
        item = self._ledger.get_item(item_id)
        if item is None:
            return SimulationResult.fail(
                f"Item not found: {item_id}",
                SimulationErrorCode.ITEM_NOT_FOUND,
            )

        entity = self._ledger.get_entity(entity_id)
        if entity is None:
            return SimulationResult.fail(
                f"Entity not found: {entity_id}",
                SimulationErrorCode.ENTITY_NOT_FOUND,
            )

        item.location_id = None
        item.container_id = None
        item.held_by = entity_id
        item.position = None
        self._ledger.set_item(item)

        return SimulationResult.ok(f"Gave {item_id} to {entity_id}")

    def mark_item_examined(self, item_id: str, by: str) -> SimulationResult:
        """Mark that someone examined an item."""
        item = self._ledger.get_item(item_id)
        if item is None:
            return SimulationResult.fail(
                f"Item not found: {item_id}",
                SimulationErrorCode.ITEM_NOT_FOUND,
            )

        if by not in item.examined_by:
            item.examined_by.append(by)
            self._ledger.set_item(item)

        return SimulationResult.ok(f"{by} examined {item_id}")

    # ========== Clue Management ==========

    def inject_clue(
        self,
        clue_id: str,
        location_id: str,
        reveals: list[str],
        min_skill: float = 0.3,
    ) -> SimulationResult:
        """Inject a clue into the world."""
        from synthetic_socio_wind_tunnel.ledger.models import ClueState

        if self._atlas.get_location(location_id) is None:
            return SimulationResult.fail(
                f"Unknown location: {location_id}",
                SimulationErrorCode.LOCATION_NOT_FOUND,
            )

        clue = ClueState(
            clue_id=clue_id,
            location_id=location_id,
            reveals=reveals,
            min_skill=min_skill,
        )
        self._ledger.set_clue(clue)

        return SimulationResult.ok(f"Injected clue {clue_id} at {location_id}")

    def discover_clue(self, clue_id: str, by: str) -> SimulationResult:
        """Mark a clue as discovered."""
        clue = self._ledger.get_clue(clue_id)
        if clue is None:
            return SimulationResult.fail(
                f"Clue not found: {clue_id}",
                SimulationErrorCode.CLUE_NOT_FOUND,
            )

        if by in clue.discovered_by:
            return SimulationResult.fail(
                f"Clue already discovered by {by}",
                SimulationErrorCode.CLUE_ALREADY_DISCOVERED,
            )

        if self._ledger.mark_clue_discovered(clue_id, by):
            # Create discovery event
            event = create_discovery_event(
                actor_id=by,
                clue_id=clue_id,
                location_id=clue.location_id,
                reveals=clue.reveals,
                timestamp=self._ledger.current_time,
            )
            return SimulationResult.ok(
                f"{by} discovered {clue_id}",
                events=[event],
                reveals=clue.reveals,
            )

        return SimulationResult.fail(
            f"Failed to discover clue: {clue_id}",
            SimulationErrorCode.UNKNOWN_ERROR,
        )

    def process_discoveries(
        self,
        entity_id: str,
        clue_ids: list[str],
    ) -> list[SimulationResult]:
        """
        Process multiple clue discoveries from a perception view.

        This is the write-back path from perception to state:
        1. Perception finds clues (read-only)
        2. Caller decides which to discover
        3. This method records discoveries (write)

        Args:
            entity_id: Who is discovering
            clue_ids: List of clue IDs to discover

        Returns:
            List of SimulationResult for each clue
        """
        results = []
        for clue_id in clue_ids:
            result = self.discover_clue(clue_id, entity_id)
            results.append(result)
        return results

    # ========== Environment ==========

    def set_weather(self, weather: str) -> SimulationResult:
        """Change weather."""
        from synthetic_socio_wind_tunnel.ledger.models import Weather
        try:
            self._ledger.weather = Weather(weather)
            return SimulationResult.ok(f"Weather is now {weather}")
        except ValueError:
            return SimulationResult.fail(
                f"Unknown weather: {weather}",
                SimulationErrorCode.INVALID_OPERATION,
            )

    def advance_time(self, minutes: int) -> SimulationResult:
        """Advance simulation time."""
        from datetime import timedelta
        new_time = self._ledger.current_time + timedelta(minutes=minutes)
        self._ledger.current_time = new_time
        return SimulationResult.ok(
            f"Time is now {new_time}",
            time_of_day=self._ledger.time_of_day.value,
        )

    # ========== Door Operations ==========

    def open_door(self, door_id: str, entity_id: str) -> SimulationResult:
        """
        Open a door.

        Checks if door exists in Atlas and if it's locked.
        """
        # Verify door exists in Atlas
        door_def = self._atlas.get_door(door_id)
        if door_def is None:
            return SimulationResult.fail(
                f"Unknown door: {door_id}",
                SimulationErrorCode.DOOR_NOT_FOUND,
            )

        # Check if already open
        if self._ledger.is_door_open(door_id):
            return SimulationResult.fail(
                f"Door {door_id} is already open",
                SimulationErrorCode.DOOR_ALREADY_OPEN,
            )

        # Check if locked
        if self._ledger.is_door_locked(door_id):
            return SimulationResult.fail(
                f"Door {door_id} is locked",
                SimulationErrorCode.DOOR_LOCKED,
                door_id=door_id,
                key_required=door_def.lock_key_id,
            )

        # Open it
        self._ledger.open_door(door_id, entity_id)

        # Create event
        entity = self._ledger.get_entity(entity_id)
        location_id = entity.location_id if entity else door_def.from_room
        event = create_door_event(
            actor_id=entity_id,
            door_id=door_id,
            location_id=location_id,
            action="open",
            timestamp=self._ledger.current_time,
        )

        return SimulationResult.ok(
            f"{entity_id} opened {door_id}",
            events=[event],
        )

    def close_door(self, door_id: str, entity_id: str) -> SimulationResult:
        """Close a door."""
        door_def = self._atlas.get_door(door_id)
        if door_def is None:
            return SimulationResult.fail(
                f"Unknown door: {door_id}",
                SimulationErrorCode.DOOR_NOT_FOUND,
            )

        if not self._ledger.is_door_open(door_id):
            return SimulationResult.fail(
                f"Door {door_id} is already closed",
                SimulationErrorCode.DOOR_ALREADY_CLOSED,
            )

        self._ledger.close_door(door_id, entity_id)

        # Create event
        entity = self._ledger.get_entity(entity_id)
        location_id = entity.location_id if entity else door_def.from_room
        event = create_door_event(
            actor_id=entity_id,
            door_id=door_id,
            location_id=location_id,
            action="close",
            timestamp=self._ledger.current_time,
        )

        return SimulationResult.ok(
            f"{entity_id} closed {door_id}",
            events=[event],
        )

    def lock_door(self, door_id: str, entity_id: str, key_id: str | None = None) -> SimulationResult:
        """
        Lock a door.

        If door requires a key (has lock_key_id in Atlas), checks entity has it.
        """
        door_def = self._atlas.get_door(door_id)
        if door_def is None:
            return SimulationResult.fail(
                f"Unknown door: {door_id}",
                SimulationErrorCode.DOOR_NOT_FOUND,
            )

        if not door_def.can_lock:
            return SimulationResult.fail(
                f"Door {door_id} cannot be locked",
                SimulationErrorCode.DOOR_CANNOT_LOCK,
            )

        # Check if key is required
        if door_def.lock_key_id:
            # Verify entity has the key
            key_item = self._ledger.get_item(door_def.lock_key_id)
            if key_item is None or key_item.held_by != entity_id:
                return SimulationResult.fail(
                    f"Need key {door_def.lock_key_id} to lock {door_id}",
                    SimulationErrorCode.KEY_NOT_HELD,
                    door_id=door_id,
                    key_required=door_def.lock_key_id,
                )

        self._ledger.lock_door(door_id, entity_id)

        # Create event
        entity = self._ledger.get_entity(entity_id)
        location_id = entity.location_id if entity else door_def.from_room
        event = create_door_event(
            actor_id=entity_id,
            door_id=door_id,
            location_id=location_id,
            action="lock",
            timestamp=self._ledger.current_time,
        )

        return SimulationResult.ok(
            f"{entity_id} locked {door_id}",
            events=[event],
        )

    def unlock_door(self, door_id: str, entity_id: str, key_id: str | None = None) -> SimulationResult:
        """
        Unlock a door.

        If door requires a key, checks entity has it.
        """
        door_def = self._atlas.get_door(door_id)
        if door_def is None:
            return SimulationResult.fail(
                f"Unknown door: {door_id}",
                SimulationErrorCode.DOOR_NOT_FOUND,
            )

        if not self._ledger.is_door_locked(door_id):
            return SimulationResult.fail(
                f"Door {door_id} is not locked",
                SimulationErrorCode.INVALID_OPERATION,
            )

        # Check if key is required
        if door_def.lock_key_id:
            key_item = self._ledger.get_item(door_def.lock_key_id)
            if key_item is None or key_item.held_by != entity_id:
                return SimulationResult.fail(
                    f"Need key {door_def.lock_key_id} to unlock {door_id}",
                    SimulationErrorCode.KEY_NOT_HELD,
                    door_id=door_id,
                    key_required=door_def.lock_key_id,
                )

        self._ledger.unlock_door(door_id, entity_id)

        # Create event
        entity = self._ledger.get_entity(entity_id)
        location_id = entity.location_id if entity else door_def.from_room
        event = create_door_event(
            actor_id=entity_id,
            door_id=door_id,
            location_id=location_id,
            action="unlock",
            timestamp=self._ledger.current_time,
        )

        return SimulationResult.ok(
            f"{entity_id} unlocked {door_id}",
            events=[event],
        )

    def can_pass_through_door(self, door_id: str) -> bool:
        """Check if a door can be passed through (open and unlocked)."""
        return self._ledger.is_door_open(door_id) and not self._ledger.is_door_locked(door_id)
