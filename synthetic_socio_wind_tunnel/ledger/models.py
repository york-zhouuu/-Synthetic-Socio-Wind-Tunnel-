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


class DynamicConnection(BaseModel):
    """
    A connection added at runtime (e.g., Space Unlock experiment).

    Dynamic connections live in Ledger because Atlas is frozen.
    NavigationService should check both Atlas.connections AND
    Ledger.dynamic_connections when building its graph.
    """
    connection_id: str
    from_id: str
    to_id: str
    path_type: str = "path"
    distance: float = 10.0
    bidirectional: bool = True
    description: str = ""
    added_at_tick: int | None = None


class BorderOverride(BaseModel):
    """
    Runtime override for a border zone's permeability.

    Used by Space Unlock experiments to dynamically change border permeability
    without modifying the frozen Atlas data.
    """
    border_id: str
    permeability: float  # 0.0 = impassable, 1.0 = fully open
    changed_at_tick: int | None = None
    reason: str = ""


# ============================================================
# 场所痕迹系统 (Location Trace — social layer written by agents)
# ============================================================

class TraceEvent(BaseModel):
    """
    A single event recorded at a location by agent activity.

    These accumulate over time to form the social history of a place.
    They are narrative (non-structured) so the LLM can interpret them freely.

    Written by: SimulationService when agents visit, converse, leave objects, etc.
    Read by: MapService when an agent queries what happened at a location.
    """
    sim_time: str  # e.g. "Day 1 09:30"
    event_type: str  # "visit", "conversation", "object_placed", "activity", "incident"
    agent_id: str | None = None  # who caused this event (None = environment)
    description: str  # free-text narrative, e.g. "陈大爷在长椅上坐了40分钟，与路过的李阿姨聊了新街市的事"


class LocationTrace(BaseModel):
    """
    The accumulated social history of a location, written by agent behavior.

    This IS the social layer — it is not pre-defined in Atlas,
    it emerges from what agents actually do here.
    """
    loc_id: str
    events: list[TraceEvent] = Field(default_factory=list)

    def recent(self, n: int = 10) -> list[TraceEvent]:
        """Return the n most recent events."""
        return self.events[-n:]


# ============================================================
# Agent Knowledge Map (每个 agent 对地图的主观认知)
# ============================================================

class LocationFamiliarity(str, Enum):
    """How well an agent knows a location."""
    UNKNOWN = "unknown"           # Agent has no idea this place exists
    HEARD_OF = "heard_of"         # Someone mentioned it, or intervention notification
    SEEN_EXTERIOR = "seen_exterior"  # Walked past, saw the facade
    VISITED = "visited"           # Has been inside / spent time here
    REGULAR = "regular"           # Goes here often, knows the routines


class AgentLocationKnowledge(BaseModel):
    """
    An agent's subjective knowledge of a single location.

    This is NOT objective data — it is what THIS agent knows/believes
    about this location, which may be incomplete or outdated.
    """
    loc_id: str
    familiarity: LocationFamiliarity = LocationFamiliarity.UNKNOWN
    known_name: str | None = None  # what the agent calls this place
    known_affordances: list[str] = Field(default_factory=list)  # what agent thinks they can do here
    subjective_impression: str | None = None  # agent's own description/feeling (free text)
    last_visit: str | None = None  # sim_time of last visit
    visit_count: int = 0
    learned_from: str = "unknown"  # "self_visit" / "agent:chen_daye" / "intervention:policy_hack_1"


class AgentKnowledgeMap(BaseModel):
    """
    An agent's complete subjective map of the world.

    Agents literally don't know places exist until they walk past them,
    hear about them from others, or receive an intervention notification.
    This is the core of informational borders.
    """
    agent_id: str
    locations: dict[str, AgentLocationKnowledge] = Field(default_factory=dict)

    def get(self, loc_id: str) -> AgentLocationKnowledge:
        """Get knowledge about a location (returns UNKNOWN if not in map)."""
        return self.locations.get(loc_id, AgentLocationKnowledge(loc_id=loc_id))

    def knows(self, loc_id: str) -> bool:
        """Returns True if agent knows this place exists (familiarity != UNKNOWN)."""
        k = self.locations.get(loc_id)
        return k is not None and k.familiarity != LocationFamiliarity.UNKNOWN

    def update(
        self,
        loc_id: str,
        familiarity: LocationFamiliarity,
        learned_from: str = "self_visit",
        **kwargs,
    ) -> None:
        """Update or create knowledge entry. Only upgrades familiarity (never downgrades)."""
        existing = self.locations.get(loc_id)
        if existing is None:
            self.locations[loc_id] = AgentLocationKnowledge(
                loc_id=loc_id,
                familiarity=familiarity,
                learned_from=learned_from,
                **kwargs,
            )
        else:
            # Only upgrade familiarity
            order = list(LocationFamiliarity)
            if order.index(familiarity) > order.index(existing.familiarity):
                existing.familiarity = familiarity
            for key, val in kwargs.items():
                if hasattr(existing, key):
                    setattr(existing, key, val)

    def known_locations(self) -> list[AgentLocationKnowledge]:
        """Return all locations the agent knows about."""
        return [k for k in self.locations.values() if k.familiarity != LocationFamiliarity.UNKNOWN]


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

    # Dynamic connections (added at runtime, e.g., Space Unlock)
    dynamic_connections: dict[str, DynamicConnection] = Field(default_factory=dict)

    # Border overrides (runtime permeability changes)
    border_overrides: dict[str, BorderOverride] = Field(default_factory=dict)

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

    # Location social traces (agent-written social history of places)
    location_traces: dict[str, LocationTrace] = Field(default_factory=dict)

    # Agent knowledge maps (subjective per-agent map of the world)
    agent_knowledge_maps: dict[str, AgentKnowledgeMap] = Field(default_factory=dict)

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
