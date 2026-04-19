"""
MapService — The single query interface for agent decision-making.

Agents call these 6 methods to get the information they need to plan and act.
All responses are agent-specific: what THIS agent knows, perceives, and can do.

Design: Observable facts in → LLM judgment out.
No numeric social scores. No pre-judged comfort levels. No god's-eye data.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from synthetic_socio_wind_tunnel.atlas.models import Building, OutdoorArea, ActivityAffordance
from synthetic_socio_wind_tunnel.atlas.service import Atlas
from synthetic_socio_wind_tunnel.ledger.service import Ledger
from synthetic_socio_wind_tunnel.ledger.models import (
    LocationFamiliarity,
    AgentKnowledgeMap,
)

_FAM_ORDER = [
    LocationFamiliarity.UNKNOWN,
    LocationFamiliarity.HEARD_OF,
    LocationFamiliarity.SEEN_EXTERIOR,
    LocationFamiliarity.VISITED,
    LocationFamiliarity.REGULAR,
]

def _fam_rank(f: LocationFamiliarity) -> int:
    try:
        return _FAM_ORDER.index(f)
    except ValueError:
        return -1
from synthetic_socio_wind_tunnel.map_service.models import (
    AffordanceInfo,
    KnownDestination,
    RouteStep,
    RouteWithPerception,
    NearbyEntity,
    LocationDetail,
    CurrentScene,
)


class MapService:
    """
    Agent-friendly query interface combining Atlas + Ledger.

    Usage:
        map_svc = MapService(atlas, ledger)

        # What does this agent know about the world?
        destinations = map_svc.get_known_destinations("chen_daye")

        # What can they do at their current location?
        scene = map_svc.get_current_scene("chen_daye", "old_market")

        # Detailed info about a specific place
        detail = map_svc.get_location_detail("alex", "sunrise_cafe")

        # Route planning
        route = map_svc.plan_route("chen_daye", "chen_home", "old_market")
    """

    def __init__(self, atlas: Atlas, ledger: Ledger):
        self._atlas = atlas
        self._ledger = ledger

    # ─── Query 1: What does this agent know about the world? ──────────────────

    def get_known_destinations(self, agent_id: str) -> list[KnownDestination]:
        """
        Return all locations this agent knows exist.

        Agents can only plan trips to places they know about.
        Unknown locations simply don't appear here — informational borders in action.
        """
        km = self._ledger.get_agent_knowledge_map(agent_id)
        results = []
        for k in km.known_locations():
            loc = self._atlas.get_building(k.loc_id) or self._atlas.get_outdoor_area(k.loc_id)
            if loc is None:
                continue
            loc_type = "building" if isinstance(loc, Building) else (
                "street" if isinstance(loc, OutdoorArea) and loc.is_street else "outdoor"
            )
            subtype = getattr(loc, "building_type", None) or getattr(loc, "area_type", "generic")
            results.append(KnownDestination(
                loc_id=k.loc_id,
                known_name=k.known_name or loc.name,
                familiarity=k.familiarity,
                loc_type=loc_type,
                subtype=subtype,
                known_affordances=k.known_affordances,
                subjective_impression=k.subjective_impression,
                last_visit=k.last_visit,
                visit_count=k.visit_count,
                learned_from=k.learned_from,
                center=[loc.center.x, loc.center.y],
            ))
        return results

    # ─── Query 2: Current scene (what agent perceives right now) ──────────────

    def get_current_scene(
        self,
        agent_id: str,
        location_id: str,
        sim_time: str = "",
    ) -> CurrentScene:
        """
        What an agent perceives at their current location.

        Includes: sensory environment, who else is here, what they can do,
        and what locations are visible/audible from here.
        """
        km = self._ledger.get_agent_knowledge_map(agent_id)
        knowledge = km.get(location_id)
        loc = self._atlas.get_building(location_id) or self._atlas.get_outdoor_area(location_id)

        loc_name = knowledge.known_name or (loc.name if loc else location_id)
        familiarity = knowledge.familiarity

        # Sensory environment
        sounds = list(loc.typical_sounds) if loc else []
        smells = list(loc.typical_smells) if loc else []

        # Affordances (time-aware — simplified: use all affordances)
        affordances = self._build_affordance_info(loc, sim_time) if loc else []

        # Entities present
        entities = self._get_entities_present(agent_id, location_id)

        # Perception scope (visible/audible from here)
        visible, audible = self._compute_perception_scope(location_id)

        # Recent social trace
        trace = self._ledger.get_location_trace(location_id)
        recent_activity = [e.description for e in trace.recent(5)] if trace else []

        return CurrentScene(
            agent_id=agent_id,
            location_id=location_id,
            location_name=loc_name,
            familiarity=familiarity,
            ambient_sounds=sounds,
            ambient_smells=smells,
            lighting="normal",
            weather=self._ledger.weather.value,
            entities_present=entities,
            affordances=affordances,
            visible_locations=list(visible),
            audible_locations=list(audible),
            recent_activity=recent_activity,
        )

    # ─── Query 3: Detailed location info ──────────────────────────────────────

    def get_location_detail(self, agent_id: str, loc_id: str) -> LocationDetail | None:
        """
        Detailed info about a location from this agent's perspective.

        Returns None if agent has no knowledge of this location.
        Content depth scales with familiarity level.
        """
        km = self._ledger.get_agent_knowledge_map(agent_id)
        knowledge = km.get(loc_id)

        if knowledge.familiarity == LocationFamiliarity.UNKNOWN:
            return None

        loc = self._atlas.get_building(loc_id) or self._atlas.get_outdoor_area(loc_id)
        if not loc:
            return None

        loc_type = "building" if isinstance(loc, Building) else (
            "street" if isinstance(loc, OutdoorArea) and loc.is_street else "outdoor"
        )
        subtype = getattr(loc, "building_type", None) or getattr(loc, "area_type", "generic")

        # Entry signals (available at SEEN_EXTERIOR+)
        es = loc.entry_signals if hasattr(loc, "entry_signals") else None
        entry_signals_dict: dict = {}
        if es and _fam_rank(knowledge.familiarity) >= _fam_rank(LocationFamiliarity.SEEN_EXTERIOR):
            entry_signals_dict = {
                "facade_description": es.facade_description,
                "signage": list(es.signage),
                "price_visible": es.price_visible,
                "visible_from_street": list(es.visible_from_street),
            }

        # Affordances (available at VISITED+ or if explicitly shared)
        affordances = []
        if _fam_rank(knowledge.familiarity) >= _fam_rank(LocationFamiliarity.VISITED):
            affordances = self._build_affordance_info(loc, "")

        # Active hours
        active_hours = None
        if isinstance(loc, Building) and loc.active_hours:
            active_hours = {"open": loc.active_hours[0], "close": loc.active_hours[1]}

        # Connections
        conns = self._get_connections(loc_id)

        # Social trace
        trace = self._ledger.get_location_trace(loc_id)
        recent_activity = [e.description for e in trace.recent(5)] if trace else []

        # Entities present
        entities = self._get_entities_present(agent_id, loc_id)

        return LocationDetail(
            loc_id=loc_id,
            name=loc.name,
            loc_type=loc_type,
            subtype=subtype,
            familiarity=knowledge.familiarity,
            description=loc.description,
            typical_sounds=list(loc.typical_sounds),
            typical_smells=list(loc.typical_smells),
            active_hours=active_hours,
            entry_signals=entry_signals_dict,
            affordances=affordances,
            recent_activity=recent_activity,
            connections=conns,
            entities_present=entities,
        )

    # ─── Query 4: Route planning ───────────────────────────────────────────────

    def plan_route(
        self, agent_id: str, from_id: str, to_id: str
    ) -> RouteWithPerception | None:
        """
        Plan a route between two locations.

        Returns None if no path exists.
        Also returns locations passed along the way (potential knowledge discoveries).
        """
        # Build adjacency from Atlas connections
        adj: dict[str, list[tuple[str, str, float]]] = {}  # id -> [(neighbor_id, path_type, dist)]
        for conn in self._atlas.region.connections:
            adj.setdefault(conn.from_id, []).append((conn.to_id, conn.path_type, conn.distance))
            if conn.bidirectional:
                adj.setdefault(conn.to_id, []).append((conn.from_id, conn.path_type, conn.distance))

        # Dijkstra
        import heapq
        dist: dict[str, float] = {from_id: 0.0}
        prev: dict[str, tuple[str, str, float] | None] = {from_id: None}
        heap = [(0.0, from_id)]
        while heap:
            d, u = heapq.heappop(heap)
            if d > dist.get(u, float("inf")):
                continue
            for v, ptype, edge_dist in adj.get(u, []):
                nd = d + edge_dist
                if nd < dist.get(v, float("inf")):
                    dist[v] = nd
                    prev[v] = (u, ptype, edge_dist)
                    heapq.heappush(heap, (nd, v))

        if to_id not in dist:
            return None

        # Reconstruct path
        path: list[tuple[str, str, float]] = []  # (loc_id, path_type_to_get_here, step_dist)
        cur = to_id
        while prev.get(cur) is not None:
            p = prev[cur]
            assert p is not None
            path.append((cur, p[1], p[2]))
            cur = p[0]
        path.append((from_id, "", 0.0))
        path.reverse()

        steps = []
        cumulative = 0.0
        for loc_id, ptype, step_dist in path:
            cumulative += step_dist
            loc = self._atlas.get_building(loc_id) or self._atlas.get_outdoor_area(loc_id)
            loc_name = loc.name if loc else loc_id
            loc_type = "building" if isinstance(loc, Building) else "outdoor"
            steps.append(RouteStep(
                loc_id=loc_id,
                loc_name=loc_name,
                loc_type=loc_type,
                path_type=ptype,
                distance_m=step_dist,
                cumulative_distance_m=cumulative,
            ))

        # Locations passed (intermediate stops, potential discoveries)
        locations_passed = [s.loc_id for s in steps[1:-1]]

        return RouteWithPerception(
            from_id=from_id,
                to_id=to_id,
            total_distance_m=dist[to_id],
            steps=steps,
            locations_passed=locations_passed,
        )

    # ─── Query 5: What can agent discover walking a route? ────────────────────

    def get_discoverable_locations(
        self, agent_id: str, route: RouteWithPerception
    ) -> list[str]:
        """
        Given a planned route, return location IDs the agent would pass that
        they don't yet know about — potential new discoveries.

        Used to determine if a route triggers knowledge updates.
        """
        km = self._ledger.get_agent_knowledge_map(agent_id)
        result = []
        for loc_id in route.locations_passed:
            if not km.knows(loc_id):
                result.append(loc_id)
        return result

    # ─── Query 6: What all agents are at a location (broadcast social) ────────

    def get_agents_at_location(self, location_id: str) -> list[str]:
        """
        Return all agent IDs currently at a location.

        This enables broadcast social interaction — the "room model"
        where all agents in the same space can interact.
        """
        return [
            e.entity_id
            for e in self._ledger.entities_at(location_id)
        ]

    # ─── Internal helpers ─────────────────────────────────────────────────────

    def _build_affordance_info(self, loc, sim_time: str) -> list[AffordanceInfo]:
        """Convert ActivityAffordance objects to AffordanceInfo response models."""
        if not hasattr(loc, "affordances"):
            return []
        results = []
        for a in loc.affordances:
            start, end = a.time_range
            available = True  # simplified — full sim would check current hour
            results.append(AffordanceInfo(
                activity_type=a.activity_type,
                available_now=available,
                time_range=f"{start:02d}:00 – {end:02d}:00",
                requires=list(a.requires),
                language_of_service=list(a.language_of_service),
                description=a.description,
                capacity=a.capacity,
            ))
        return results

    def _get_entities_present(self, agent_id: str, location_id: str) -> list[NearbyEntity]:
        """Get all other entities at this location."""
        results = []
        for entity in self._ledger.entities_at(location_id):
            if entity.entity_id == agent_id:
                continue
            results.append(NearbyEntity(
                entity_id=entity.entity_id,
                name=entity.entity_id,  # simplified — real system would have name lookup
                distance_m=0.0,
                activity=entity.activity,
                apparent_mood=None,
            ))
        return results

    def _get_connections(self, loc_id: str) -> list[dict]:
        """Get connections from a location."""
        results = []
        for conn in self._atlas.region.connections:
            other_id = None
            if conn.from_id == loc_id:
                other_id = conn.to_id
            elif conn.bidirectional and conn.to_id == loc_id:
                other_id = conn.from_id
            if other_id:
                other = self._atlas.get_building(other_id) or self._atlas.get_outdoor_area(other_id)
                if other:
                    results.append({
                        "to_id": other_id,
                        "to_name": other.name,
                        "path_type": conn.path_type,
                        "distance_m": round(conn.distance, 1),
                    })
        return results

    def _compute_perception_scope(
        self, location_id: str
    ) -> tuple[set[str], set[str]]:
        """Compute visible and audible locations from a given location."""
        adj: dict[str, set[str]] = {}
        for conn in self._atlas.region.connections:
            adj.setdefault(conn.from_id, set()).add(conn.to_id)
            if conn.bidirectional:
                adj.setdefault(conn.to_id, set()).add(conn.from_id)

        direct = adj.get(location_id, set())
        loc = self._atlas.get_building(location_id) or self._atlas.get_outdoor_area(location_id)
        is_building = isinstance(loc, Building)

        if is_building:
            visible = {n for n in direct
                      if isinstance(self._atlas.get_outdoor_area(n), OutdoorArea)}
        else:
            visible = set(direct)

        audible: set[str] = set()
        for v in visible:
            for n2 in adj.get(v, set()):
                if n2 != location_id and n2 not in visible:
                    audible.add(n2)

        return visible, audible
