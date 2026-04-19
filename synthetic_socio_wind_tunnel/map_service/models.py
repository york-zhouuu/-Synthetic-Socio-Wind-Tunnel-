"""
Map Service Response Models — What agents receive when querying the map.

Design principle:
  - All fields are observable FACTS, not social judgments
  - Free-text descriptions let the LLM interpret
  - No numeric scores for social attributes
  - Agent-specific: responses reflect what THIS agent knows
"""

from __future__ import annotations
from pydantic import BaseModel, Field

from synthetic_socio_wind_tunnel.ledger.models import LocationFamiliarity


class AffordanceInfo(BaseModel):
    """A single activity affordance as seen by an agent."""
    activity_type: str
    available_now: bool  # based on current sim time
    time_range: str  # human-readable: "07:00 – 22:00"
    requires: list[str]  # ["payment", "membership"]
    language_of_service: list[str]
    description: str
    capacity: int | None = None


class KnownDestination(BaseModel):
    """
    A location the agent KNOWS EXISTS and can potentially go to.

    Only locations in the agent's knowledge map appear here.
    Unknown locations are invisible to the agent.
    """
    loc_id: str
    known_name: str  # what the agent calls it
    familiarity: LocationFamiliarity
    loc_type: str  # "building", "street", "outdoor"
    subtype: str  # "cafe", "park", "residential"...
    known_affordances: list[str]  # what agent thinks they can do here
    subjective_impression: str | None  # agent's own words about this place
    last_visit: str | None
    visit_count: int
    learned_from: str  # how agent discovered this place
    center: list[float]  # [x, y] for map rendering


class RouteStep(BaseModel):
    """One step in a navigation route."""
    loc_id: str
    loc_name: str
    loc_type: str
    path_type: str  # "entrance", "path", "road"
    distance_m: float
    cumulative_distance_m: float


class RouteWithPerception(BaseModel):
    """A route with what the agent would perceive along the way."""
    from_id: str
    to_id: str
    total_distance_m: float
    steps: list[RouteStep]
    locations_passed: list[str]  # location IDs passed on the way (potential new discoveries)


class NearbyEntity(BaseModel):
    """Another agent/entity visible from current location."""
    entity_id: str
    name: str
    distance_m: float
    activity: str | None  # what they appear to be doing
    apparent_mood: str | None


class LocationDetail(BaseModel):
    """
    Detailed info about a location from an agent's perspective.

    Content depends on the agent's familiarity:
    - HEARD_OF: only known_name + what they were told
    - SEEN_EXTERIOR: entry_signals (what's visible from outside)
    - VISITED/REGULAR: full affordances + social trace
    """
    loc_id: str
    name: str  # official name
    loc_type: str
    subtype: str
    familiarity: LocationFamiliarity

    # Physical facts (always available once visible)
    description: str
    typical_sounds: list[str]
    typical_smells: list[str]
    active_hours: dict | None  # {"open": 7, "close": 22} or None

    # What's observable from outside (available at SEEN_EXTERIOR+)
    entry_signals: dict  # facade, signage, price_visible, visible_from_street

    # What can be done here (available at VISITED+, or if heard from someone)
    affordances: list[AffordanceInfo]

    # Social trace: what has happened here (accumulates from agent activity)
    recent_activity: list[str]  # narrative descriptions of recent events

    # Connections the agent knows about
    connections: list[dict]  # [{to_id, to_name, path_type, distance_m}]

    # Other agents here right now
    entities_present: list[NearbyEntity]


class CurrentScene(BaseModel):
    """
    What an agent perceives at their current location right now.

    This is the agent's immediate reality — not a query, but a push.
    """
    agent_id: str
    location_id: str
    location_name: str
    familiarity: LocationFamiliarity

    # Immediate sensory environment
    ambient_sounds: list[str]
    ambient_smells: list[str]
    lighting: str  # "bright", "normal", "dim", "dark"
    weather: str

    # Who else is here
    entities_present: list[NearbyEntity]

    # What agent can do here
    affordances: list[AffordanceInfo]

    # Locations visible / audible from here (for perception scope)
    visible_locations: list[str]
    audible_locations: list[str]

    # Recent social trace of this location
    recent_activity: list[str]
