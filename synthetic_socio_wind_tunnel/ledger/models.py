"""
Ledger Data Models - Mutable world state.

These models represent the current state of the world.
They are:
- Mutable during gameplay
- The single source of truth
- Objective facts (if door is open in Ledger, it's open for everyone)

Key principle: Ledger stores WHAT IS, not HOW IT LOOKS.
Perception layer handles the "how it looks" part.
"""

from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field, model_validator, field_validator

# Import from core to avoid cross-layer dependency
from synthetic_socio_wind_tunnel.core.types import Coord


class TimeOfDay(str, Enum):
    """Time periods affecting lighting and activity."""
    DAWN = "dawn"
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"
    NIGHT = "night"


class Weather(str, Enum):
    """Weather conditions affecting visibility and sound."""
    CLEAR = "clear"
    CLOUDY = "cloudy"
    RAIN = "rain"
    HEAVY_RAIN = "heavy_rain"
    FOG = "fog"
    SNOW = "snow"


class EntityState(BaseModel):
    """State of a movable entity (character, NPC, creature)."""
    entity_id: str
    location_id: str
    position: Coord
    activity: str | None = None  # "reading", "working", "hiding"
    facing: str | None = None  # direction facing
    arrived_at: datetime | None = None


class ItemState(BaseModel):
    """State of an item in the world."""
    item_id: str
    name: str

    # Location (exactly one should be set)
    location_id: str | None = None
    container_id: str | None = None
    held_by: str | None = None

    position: Coord | None = None

    # Visibility
    is_visible: bool = True
    is_hidden: bool = False  # Requires investigation to find
    discovery_skill: float = 0.0  # Skill threshold to notice

    # State tracking
    examined_by: list[str] = Field(default_factory=list)
    state: dict[str, Any] = Field(default_factory=dict)  # Open, locked, etc.

    @model_validator(mode='after')
    def validate_location_exclusive(self) -> 'ItemState':
        """Ensure only one location type is set."""
        count = sum([
            self.location_id is not None,
            self.container_id is not None,
            self.held_by is not None,
        ])
        if count > 1:
            raise ValueError(
                "Item can only be in one place: location_id, container_id, or held_by. "
                f"Got: location_id={self.location_id}, container_id={self.container_id}, held_by={self.held_by}"
            )
        return self


class GeneratedDetail(BaseModel):
    """
    A Schrödinger detail that has collapsed into existence.

    Before observation, details don't exist. When examined,
    they are generated and recorded here permanently.
    """
    detail_id: str
    target_id: str  # What was examined (location, container, item)
    content: str  # The generated description
    generated_by: str  # Who triggered generation
    generated_at: datetime
    is_permanent: bool = True  # Once collapsed, stays collapsed


class ClueState(BaseModel):
    """A clue that can be discovered."""
    clue_id: str
    location_id: str
    reveals: list[str] = Field(default_factory=list)  # Facts revealed
    min_skill: float = 0.3  # Investigation skill required
    discovered_by: str | None = None
    discovered_at: datetime | None = None


# ============================================================
# 容器动态状态 (Container Runtime State)
# ============================================================

class ContainerState(BaseModel):
    """
    Dynamic state of a container (furniture that holds items).

    This is the DYNAMIC state in Ledger - what has happened to the container.
    The STATIC definition (capacity, type) is in Atlas.ContainerDef.

    Design principle: Atlas defines WHAT containers exist,
    Ledger tracks WHAT HAS HAPPENED to them.
    """
    container_id: str

    # Interaction state
    is_open: bool = False          # Drawer pulled out, cabinet door open
    is_locked: bool = False        # Requires key/skill to open
    # Note: lock_key_id is in Atlas.ContainerDef (static definition)

    # Examination tracking
    examined_by: list[str] = Field(default_factory=list)
    examination_depth: dict[str, float] = Field(default_factory=dict)
    # ^ How thoroughly each character searched (0-1)

    # Schrödinger state
    contents_collapsed: bool = False   # Has content been generated?
    collapsed_at: datetime | None = None
    collapsed_by: str | None = None


# ============================================================
# 门动态状态 (Door Runtime State)
# ============================================================

class DoorState(BaseModel):
    """
    Dynamic state of a door between rooms.

    This is the DYNAMIC state in Ledger - current door state.
    The STATIC definition (which rooms, can_lock) is in Atlas.DoorDef.
    """
    door_id: str
    is_open: bool = True       # Door is physically open
    is_locked: bool = False    # Door is locked (requires key)
    last_opened_by: str | None = None
    last_opened_at: datetime | None = None


# ============================================================
# 证据蓝图系统 (Evidence Blueprint System)
# ============================================================

class EvidenceBlueprint(BaseModel):
    """
    Blueprint for plot-required evidence.

    Problem: In a Schrödinger system, how do we ensure the murder weapon
    exists when Emma searches the killer's desk?

    Solution: EvidenceBlueprint defines WHAT MUST EXIST and WHERE,
    but LLM generates HOW IT APPEARS during collapse.

    Example:
        EvidenceBlueprint(
            evidence_id="murder_weapon",
            required_in="linda_desk_drawer",
            must_contain=["poison bottle", "remains of substance"],
            appearance_hints=["hidden under papers", "wrapped in cloth"],
            discoverable_facts=["The poison was purchased recently"],
            min_discovery_skill=0.6
        )

    When CollapseService generates contents of "linda_desk_drawer",
    it MUST include items matching this blueprint, but can vary details.
    """
    evidence_id: str
    required_in: str  # Container ID where evidence must appear

    # Content constraints
    must_contain: list[str]  # Items that MUST be generated
    appearance_hints: list[str] = Field(default_factory=list)  # How it might look
    forbidden_details: list[str] = Field(default_factory=list)  # What NOT to generate

    # Discovery
    discoverable_facts: list[str] = Field(default_factory=list)  # Facts revealed on discovery
    min_discovery_skill: float = 0.5  # Skill required to notice

    # State
    discovered: bool = False
    discovered_by: str | None = None
    discovered_at: datetime | None = None

    # Generation result (filled after collapse)
    generated_description: str | None = None


class LedgerData(BaseModel):
    """Complete world state. Serializable for save/load."""
    # Time
    current_time: datetime = Field(default_factory=datetime.now)
    time_of_day: TimeOfDay = TimeOfDay.MORNING
    weather: Weather = Weather.CLEAR

    # Entities
    entities: dict[str, EntityState] = Field(default_factory=dict)

    # Items
    items: dict[str, ItemState] = Field(default_factory=dict)

    # Container states (dynamic state, definitions in Atlas)
    container_states: dict[str, ContainerState] = Field(default_factory=dict)

    # Door states (dynamic state, definitions in Atlas)
    door_states: dict[str, DoorState] = Field(default_factory=dict)

    # Evidence blueprints (plot-required evidence)
    evidence_blueprints: dict[str, EvidenceBlueprint] = Field(default_factory=dict)

    # Generated content (Schrödinger collapses)
    details: dict[str, GeneratedDetail] = Field(default_factory=dict)

    # Clues
    clues: dict[str, ClueState] = Field(default_factory=dict)
    discovered_clue_ids: set[str] = Field(default_factory=set)

    # Plot state
    plot_tags: dict[str, set[str]] = Field(default_factory=dict)

    # Exploration tracking (认知地图)
    # Maps entity_id -> set of location_ids they have explored
    explored_locations: dict[str, set[str]] = Field(default_factory=dict)

    # Event log
    events: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator('discovered_clue_ids', mode='before')
    @classmethod
    def convert_discovered_clues_to_set(cls, v):
        """Convert list to set when deserializing from JSON."""
        if isinstance(v, list):
            return set(v)
        return v

    @field_validator('plot_tags', mode='before')
    @classmethod
    def convert_plot_tags_to_set(cls, v):
        """Convert inner lists to sets when deserializing from JSON."""
        if isinstance(v, dict):
            return {k: set(vals) if isinstance(vals, list) else vals for k, vals in v.items()}
        return v

    @field_validator('explored_locations', mode='before')
    @classmethod
    def convert_explored_locations_to_set(cls, v):
        """Convert inner lists to sets when deserializing from JSON."""
        if isinstance(v, dict):
            return {k: set(vals) if isinstance(vals, list) else vals for k, vals in v.items()}
        return v
