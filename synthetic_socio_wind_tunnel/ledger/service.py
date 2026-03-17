"""
Ledger Service - CRUD operations on world state.

Ledger is the "Props Department" - it manages all mutable state.
This is a thin CRUD layer with minimal logic.
Business logic belongs in Engine services (Simulation, Collapse).
"""

from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.ledger.models import (
    LedgerData,
    EntityState,
    ItemState,
    GeneratedDetail,
    ClueState,
    ContainerState,
    DoorState,
    EvidenceBlueprint,
    TimeOfDay,
    Weather,
)


class Ledger:
    """
    CRUD service for dynamic world state.

    Ledger is the single source of truth for "what exists now".
    It provides:
    - Entity CRUD (create, read, update, delete)
    - Item CRUD
    - Detail storage (Schrödinger collapses)
    - Clue management
    - Save/Load

    NOT thread-safe. For concurrent access, use external locking.
    """

    __slots__ = ("_data",)

    def __init__(self, data: LedgerData | None = None):
        """Initialize with optional existing data."""
        self._data = data or LedgerData()

    @classmethod
    def from_json(cls, path: str | Path) -> "Ledger":
        """Load Ledger from JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        data = LedgerData.model_validate(raw)
        return cls(data)

    # ========== Time & Environment ==========

    @property
    def current_time(self) -> datetime:
        return self._data.current_time

    @current_time.setter
    def current_time(self, value: datetime) -> None:
        self._data.current_time = value
        self._update_time_of_day(value)

    @property
    def time_of_day(self) -> TimeOfDay:
        return self._data.time_of_day

    @property
    def weather(self) -> Weather:
        return self._data.weather

    @weather.setter
    def weather(self, value: Weather) -> None:
        self._data.weather = value
        self._log_event("weather_change", weather=value.value)

    def _update_time_of_day(self, time: datetime) -> None:
        hour = time.hour
        if 5 <= hour < 7:
            self._data.time_of_day = TimeOfDay.DAWN
        elif 7 <= hour < 12:
            self._data.time_of_day = TimeOfDay.MORNING
        elif 12 <= hour < 17:
            self._data.time_of_day = TimeOfDay.AFTERNOON
        elif 17 <= hour < 20:
            self._data.time_of_day = TimeOfDay.EVENING
        else:
            self._data.time_of_day = TimeOfDay.NIGHT

    # ========== Entity CRUD ==========

    def get_entity(self, entity_id: str) -> EntityState | None:
        """Get entity state by ID."""
        return self._data.entities.get(entity_id)

    def set_entity(self, state: EntityState) -> None:
        """Create or update entity state."""
        self._data.entities[state.entity_id] = state

    def remove_entity(self, entity_id: str) -> bool:
        """Remove entity. Returns True if existed."""
        if entity_id in self._data.entities:
            del self._data.entities[entity_id]
            return True
        return False

    def entities_at(self, location_id: str) -> Iterator[EntityState]:
        """Iterate entities at a location."""
        for entity in self._data.entities.values():
            if entity.location_id == location_id:
                yield entity

    def list_entity_ids(self) -> list[str]:
        """List all entity IDs."""
        return list(self._data.entities.keys())

    # ========== Item CRUD ==========

    def get_item(self, item_id: str) -> ItemState | None:
        """Get item state by ID."""
        return self._data.items.get(item_id)

    def set_item(self, state: ItemState) -> None:
        """Create or update item state."""
        self._data.items[state.item_id] = state

    def remove_item(self, item_id: str) -> bool:
        """Remove item. Returns True if existed."""
        if item_id in self._data.items:
            del self._data.items[item_id]
            return True
        return False

    def items_at(self, location_id: str) -> Iterator[ItemState]:
        """Iterate items at a location (not in containers)."""
        for item in self._data.items.values():
            if item.location_id == location_id and item.container_id is None:
                yield item

    def items_in(self, container_id: str) -> Iterator[ItemState]:
        """Iterate items in a container."""
        for item in self._data.items.values():
            if item.container_id == container_id:
                yield item

    def count_items_in(self, container_id: str) -> int:
        """Count items in a container (for capacity check)."""
        return sum(1 for _ in self.items_in(container_id))

    # ========== Container State CRUD ==========

    def get_container_state(self, container_id: str) -> ContainerState | None:
        """Get container state by ID."""
        return self._data.container_states.get(container_id)

    def get_or_create_container_state(self, container_id: str) -> ContainerState:
        """Get container state, creating if doesn't exist."""
        if container_id not in self._data.container_states:
            self._data.container_states[container_id] = ContainerState(
                container_id=container_id
            )
        return self._data.container_states[container_id]

    def set_container_state(self, state: ContainerState) -> None:
        """Create or update container state."""
        self._data.container_states[state.container_id] = state

    def is_container_collapsed(self, container_id: str) -> bool:
        """Check if container contents have been generated."""
        state = self._data.container_states.get(container_id)
        return state.contents_collapsed if state else False

    def mark_container_collapsed(self, container_id: str, by: str) -> None:
        """Mark container as having collapsed contents."""
        state = self.get_or_create_container_state(container_id)
        state.contents_collapsed = True
        state.collapsed_at = self._data.current_time
        state.collapsed_by = by
        self._log_event("container_collapsed", container_id=container_id, by=by)

    def record_examination(self, container_id: str, by: str, depth: float) -> None:
        """Record that someone examined a container."""
        state = self.get_or_create_container_state(container_id)
        if by not in state.examined_by:
            state.examined_by.append(by)
        state.examination_depth[by] = max(
            state.examination_depth.get(by, 0.0), depth
        )

    # ========== Door State CRUD ==========

    def get_door_state(self, door_id: str) -> DoorState | None:
        """Get door state by ID."""
        return self._data.door_states.get(door_id)

    def get_or_create_door_state(self, door_id: str) -> DoorState:
        """Get door state, creating if doesn't exist."""
        if door_id not in self._data.door_states:
            self._data.door_states[door_id] = DoorState(door_id=door_id)
        return self._data.door_states[door_id]

    def set_door_state(self, state: DoorState) -> None:
        """Create or update door state."""
        self._data.door_states[state.door_id] = state

    def is_door_open(self, door_id: str) -> bool:
        """Check if door is open (defaults to True if no state)."""
        state = self._data.door_states.get(door_id)
        return state.is_open if state else True

    def is_door_locked(self, door_id: str) -> bool:
        """Check if door is locked."""
        state = self._data.door_states.get(door_id)
        return state.is_locked if state else False

    def open_door(self, door_id: str, by: str) -> bool:
        """
        Open a door. Returns False if locked.

        Does not check for keys - that's business logic in SimulationService.
        """
        state = self.get_or_create_door_state(door_id)
        if state.is_locked:
            return False
        state.is_open = True
        state.last_opened_by = by
        state.last_opened_at = self._data.current_time
        self._log_event("door_opened", door_id=door_id, by=by)
        return True

    def close_door(self, door_id: str, by: str) -> None:
        """Close a door."""
        state = self.get_or_create_door_state(door_id)
        state.is_open = False
        self._log_event("door_closed", door_id=door_id, by=by)

    def lock_door(self, door_id: str, by: str) -> None:
        """Lock a door (also closes it)."""
        state = self.get_or_create_door_state(door_id)
        state.is_open = False
        state.is_locked = True
        self._log_event("door_locked", door_id=door_id, by=by)

    def unlock_door(self, door_id: str, by: str) -> None:
        """Unlock a door."""
        state = self.get_or_create_door_state(door_id)
        state.is_locked = False
        self._log_event("door_unlocked", door_id=door_id, by=by)

    # ========== Evidence Blueprint CRUD ==========

    def get_evidence(self, evidence_id: str) -> EvidenceBlueprint | None:
        """Get evidence blueprint by ID."""
        return self._data.evidence_blueprints.get(evidence_id)

    def set_evidence(self, evidence: EvidenceBlueprint) -> None:
        """Add or update evidence blueprint."""
        self._data.evidence_blueprints[evidence.evidence_id] = evidence

    def get_evidence_for_container(self, container_id: str) -> list[EvidenceBlueprint]:
        """Get all evidence blueprints that must appear in a container."""
        return [
            ev for ev in self._data.evidence_blueprints.values()
            if ev.required_in == container_id and not ev.discovered
        ]

    def mark_evidence_discovered(self, evidence_id: str, by: str) -> bool:
        """Mark evidence as discovered. Returns False if already discovered."""
        evidence = self._data.evidence_blueprints.get(evidence_id)
        if evidence and not evidence.discovered:
            evidence.discovered = True
            evidence.discovered_by = by
            evidence.discovered_at = self._data.current_time
            self._log_event("evidence_discovered", evidence_id=evidence_id, by=by)
            return True
        return False

    def list_undiscovered_evidence(self) -> list[EvidenceBlueprint]:
        """List all undiscovered evidence."""
        return [
            ev for ev in self._data.evidence_blueprints.values()
            if not ev.discovered
        ]

    # ========== Generated Details ==========

    def get_detail(self, detail_id: str) -> GeneratedDetail | None:
        """Get a generated detail."""
        return self._data.details.get(detail_id)

    def has_detail(self, detail_id: str) -> bool:
        """Check if detail exists (has been collapsed)."""
        return detail_id in self._data.details

    def set_detail(self, detail: GeneratedDetail) -> None:
        """Store a generated detail (collapse Schrödinger)."""
        self._data.details[detail.detail_id] = detail

    def details_for(self, target_id: str) -> Iterator[GeneratedDetail]:
        """Iterate all details for a target."""
        for detail in self._data.details.values():
            if detail.target_id == target_id:
                yield detail

    # ========== Clues ==========

    def get_clue(self, clue_id: str) -> ClueState | None:
        """Get clue state."""
        return self._data.clues.get(clue_id)

    def set_clue(self, clue: ClueState) -> None:
        """Add or update a clue."""
        self._data.clues[clue.clue_id] = clue

    def is_clue_discovered(self, clue_id: str) -> bool:
        """Check if clue has been discovered."""
        return clue_id in self._data.discovered_clue_ids

    def mark_clue_discovered(self, clue_id: str, by: str) -> bool:
        """Mark clue as discovered. Returns False if already discovered."""
        if clue_id in self._data.discovered_clue_ids:
            return False
        clue = self._data.clues.get(clue_id)
        if clue:
            clue.discovered_by = by
            clue.discovered_at = self._data.current_time
            self._data.discovered_clue_ids.add(clue_id)
            self._log_event("clue_discovered", clue_id=clue_id, by=by)
            return True
        return False

    def undiscovered_clues_at(self, location_id: str) -> Iterator[ClueState]:
        """Iterate undiscovered clues at location."""
        for clue in self._data.clues.values():
            if clue.location_id == location_id and clue.clue_id not in self._data.discovered_clue_ids:
                yield clue

    # ========== Plot Tags ==========

    def add_tag(self, location_id: str, tag: str) -> None:
        """Add plot tag to location."""
        if location_id not in self._data.plot_tags:
            self._data.plot_tags[location_id] = set()
        self._data.plot_tags[location_id].add(tag)

    def remove_tag(self, location_id: str, tag: str) -> None:
        """Remove plot tag from location."""
        if location_id in self._data.plot_tags:
            self._data.plot_tags[location_id].discard(tag)

    def has_tag(self, location_id: str, tag: str) -> bool:
        """Check if location has tag."""
        return tag in self._data.plot_tags.get(location_id, set())

    def get_tags(self, location_id: str) -> set[str]:
        """Get all tags for location."""
        return self._data.plot_tags.get(location_id, set()).copy()

    # ========== Exploration Tracking (认知地图) ==========

    def get_explored_locations(self, entity_id: str) -> set[str]:
        """
        Get all locations an entity has explored.

        Returns a copy to prevent external modification.
        """
        return self._data.explored_locations.get(entity_id, set()).copy()

    def add_explored_location(self, entity_id: str, location_id: str) -> bool:
        """
        Record that an entity has explored a location.

        Returns True if this is a new discovery, False if already explored.
        """
        if entity_id not in self._data.explored_locations:
            self._data.explored_locations[entity_id] = set()

        if location_id in self._data.explored_locations[entity_id]:
            return False

        self._data.explored_locations[entity_id].add(location_id)
        self._log_event("location_explored", entity_id=entity_id, location_id=location_id)
        return True

    def has_explored(self, entity_id: str, location_id: str) -> bool:
        """Check if an entity has explored a specific location."""
        return location_id in self._data.explored_locations.get(entity_id, set())

    def clear_exploration(self, entity_id: str) -> None:
        """Clear all exploration data for an entity (e.g., amnesia effect)."""
        if entity_id in self._data.explored_locations:
            del self._data.explored_locations[entity_id]
            self._log_event("exploration_cleared", entity_id=entity_id)

    # ========== Events ==========

    def _log_event(self, event_type: str, **data: Any) -> None:
        """Log an event (internal)."""
        self._data.events.append({
            "type": event_type,
            "time": self._data.current_time.isoformat(),
            **data
        })
        # Keep last 100 events
        if len(self._data.events) > 100:
            self._data.events = self._data.events[-100:]

    def get_recent_events(self, limit: int = 10) -> list[dict]:
        """Get recent events."""
        return self._data.events[-limit:]

    # ========== Serialization ==========

    def save(self, path: str | Path) -> None:
        """Save to JSON file."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._data.model_dump(mode="json"), f, indent=2, ensure_ascii=False)

    def to_dict(self) -> dict:
        """Export as dictionary."""
        return self._data.model_dump(mode="json")

    def clear(self) -> None:
        """Reset to empty state."""
        self._data = LedgerData()
