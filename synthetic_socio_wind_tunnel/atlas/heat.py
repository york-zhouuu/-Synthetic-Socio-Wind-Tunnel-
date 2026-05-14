"""POIHeatModel — per-location occupancy tracker.

A3 / realism-poi-capacity. Records which agents are currently at which
location; used by:
- `simulation::move_entity` to check `is_full(loc)` before completing arrival
- `policy_hack::hyperlocal_push` (optional) to skip pushing to full locations
- `metrics` to record per-tick heat for visualization

This is a sim-level service (one instance per run); orchestrator constructs
and threads it through.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from synthetic_socio_wind_tunnel.atlas.service import Atlas


@dataclass
class POIHeatModel:
    """Tracks per-location occupancy in real time.

    Methods are O(1). Memory: O(N) where N = entities ever registered.
    """

    _atlas: Atlas
    _occupants_by_location: dict[str, set[str]] = field(
        default_factory=lambda: defaultdict(set),
    )
    _location_by_agent: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_atlas(cls, atlas: Atlas) -> "POIHeatModel":
        return cls(_atlas=atlas)

    def register_arrival(self, location_id: str, agent_id: str) -> None:
        """Record that agent_id is now at location_id.

        If agent was previously at another location, departure from there
        is recorded automatically.
        """
        prev = self._location_by_agent.get(agent_id)
        if prev == location_id:
            return  # idempotent
        if prev is not None:
            self._occupants_by_location[prev].discard(agent_id)
        self._occupants_by_location[location_id].add(agent_id)
        self._location_by_agent[agent_id] = location_id

    def register_departure(self, location_id: str, agent_id: str) -> None:
        """Record that agent_id has left location_id."""
        self._occupants_by_location[location_id].discard(agent_id)
        if self._location_by_agent.get(agent_id) == location_id:
            del self._location_by_agent[agent_id]

    def current_occupancy(self, location_id: str) -> int:
        return len(self._occupants_by_location.get(location_id, set()))

    def occupants_of(self, location_id: str) -> set[str]:
        """Return frozen copy of occupants for safe iteration."""
        return set(self._occupants_by_location.get(location_id, set()))

    def location_of(self, agent_id: str) -> str | None:
        return self._location_by_agent.get(agent_id)

    def is_full(self, location_id: str) -> bool:
        """True iff capacity is set AND current_occupancy >= capacity."""
        try:
            area = self._atlas.get_outdoor_area(location_id)
        except Exception:
            area = None
        if area is None:
            # Try as building
            try:
                area = self._atlas.get_building(location_id)
            except Exception:
                area = None
        if area is None:
            return False
        cap = getattr(area, "capacity", None)
        if cap is None:
            return False  # unbounded
        return self.current_occupancy(location_id) >= cap

    def total_locations_with_occupants(self) -> int:
        return sum(
            1 for occs in self._occupants_by_location.values() if occs
        )


# Default capacity by area_type — applied at atlas-load time (e.g. by
# cartography/lanecove.py). cafe / shop / restaurant get caps; outdoor open
# spaces stay unbounded.
DEFAULT_CAPACITY_BY_AREA_TYPE: dict[str, int | None] = {
    "cafe": 15,
    "restaurant": 20,
    "shop": 10,
    "park": None,
    "street": None,
    "square": None,
    "playground": 30,
    "garden": None,
    "parking": None,
    "library": 50,
    "school": None,
}


def default_capacity_for_area_type(area_type: str) -> int | None:
    """Lookup default capacity for a given area_type (None = unbounded)."""
    return DEFAULT_CAPACITY_BY_AREA_TYPE.get(area_type, None)


__all__ = [
    "POIHeatModel",
    "DEFAULT_CAPACITY_BY_AREA_TYPE",
    "default_capacity_for_area_type",
]
