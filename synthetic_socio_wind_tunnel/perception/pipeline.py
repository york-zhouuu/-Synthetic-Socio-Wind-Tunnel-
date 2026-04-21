"""
PerceptionPipeline - The Camera (摄影师)

Transforms objective world data into subjective experience.
This is the Rashomon engine.

Pipeline stages:
1. Gather: Collect raw data from Atlas + Ledger
2. Filter: Physical visibility, hearing, etc.
3. Interpret: Apply observer's skills, knowledge, emotions
4. Render: Generate narrative text

READ ONLY - never modifies Atlas or Ledger.
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Callable, Protocol

from synthetic_socio_wind_tunnel.atlas.models import Coord, Room
from synthetic_socio_wind_tunnel.ledger.models import TimeOfDay, Weather
from synthetic_socio_wind_tunnel.perception.models import (
    ObserverContext,
    SubjectiveView,
    Observation,
    SenseType,
)
from synthetic_socio_wind_tunnel.perception.filters.base import Filter

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.atlas import Atlas
    from synthetic_socio_wind_tunnel.attention import AttentionService
    from synthetic_socio_wind_tunnel.ledger import Ledger


class NarrativeRenderer(Protocol):
    """Protocol for narrative rendering callbacks."""

    def __call__(self, view: SubjectiveView, context: ObserverContext) -> str:
        """Render a subjective view into narrative text."""
        ...


def default_renderer(view: SubjectiveView, context: ObserverContext) -> str:
    """Simple template-based renderer."""
    lines = [f"You are in {view.location_name}."]

    if view.lighting == "dark":
        lines.append("It's dark here.")
    elif view.lighting == "dim":
        lines.append("The light is dim.")

    if view.entities_seen:
        lines.append(f"Present: {', '.join(view.entities_seen)}")

    for obs in view.get_notable_observations():
        lines.append(f"You notice: {obs.interpreted}")

    # Add emotional coloring for guilty observers
    if context.guilt_level > 0.5:
        for obs in view.observations:
            if "evidence" in obs.tags or obs.source_type == "item":
                lines.append("Everything feels suspicious...")
                break

    if view.clues_found:
        lines.append(f"You discover: {', '.join(view.clues_found)}")

    return " ".join(lines)


class PerceptionPipeline:
    """
    The main perception rendering pipeline.

    Transforms Atlas (static) + Ledger (dynamic) + ObserverContext
    into a SubjectiveView.

    This is a PURE READ operation - never modifies data.

    Pipeline stages:
    1. Gather: Collect raw observations from Atlas + Ledger
    2. Filter: Apply filter chain (physical, environmental, skill, etc.)
    3. Interpret: Apply observer's knowledge and emotions
    4. Render: Generate narrative text
    """

    __slots__ = (
        "_atlas",
        "_ledger",
        "_renderer",
        "_filters",
        "_include_digital_filter",
        "_attention_service",
    )

    def __init__(
        self,
        atlas: "Atlas",
        ledger: "Ledger",
        renderer: NarrativeRenderer | None = None,
        filters: list[Filter] | None = None,
        *,
        include_digital_filter: bool = False,
        attention_service: "AttentionService | None" = None,
    ):
        """
        Initialize pipeline.

        Args:
            atlas: Read-only static map
            ledger: Read-only access to dynamic state
            renderer: Narrative renderer (defaults to template)
            filters: Optional list of observation filters to apply
            include_digital_filter: If True, append DigitalAttentionFilter to
                the chain (Phase 1 default is False for backward compat).
            attention_service: Source of DIGITAL observations; required when
                include_digital_filter=True to gather pending notifications.
        """
        if include_digital_filter and attention_service is None:
            raise ValueError(
                "include_digital_filter=True requires attention_service to be "
                "provided; otherwise DIGITAL observations can't be gathered."
            )
        self._atlas = atlas
        self._ledger = ledger
        self._renderer = renderer or default_renderer
        self._filters = list(filters) if filters else []
        self._include_digital_filter = include_digital_filter
        self._attention_service = attention_service
        if include_digital_filter:
            from synthetic_socio_wind_tunnel.perception.filters.digital_attention import (
                DigitalAttentionFilter,
            )
            self._filters.append(DigitalAttentionFilter())

    def set_renderer(self, renderer: NarrativeRenderer) -> None:
        """Replace the narrative renderer (e.g., switch to LLM)."""
        self._renderer = renderer

    def set_filters(self, filters: list[Filter]) -> None:
        """Replace the filter chain."""
        self._filters = filters

    def add_filter(self, filter: Filter) -> None:
        """Add a filter to the chain."""
        self._filters.append(filter)

    def _apply_filters(
        self,
        observations: list[Observation],
        context: ObserverContext,
    ) -> list[Observation]:
        """
        Apply all filters to a list of observations.

        Filters may modify observations (e.g., adjust confidence)
        or return None to filter them out entirely.
        """
        if not self._filters:
            return observations

        result: list[Observation] = []
        for obs in observations:
            filtered_obs: Observation | None = obs
            for filter in self._filters:
                if filtered_obs is None:
                    break
                filtered_obs = filter.apply(filtered_obs, context)
            if filtered_obs is not None:
                result.append(filtered_obs)
        return result

    def render(self, context: ObserverContext) -> SubjectiveView:
        """
        Render a subjective view for an observer.

        This is the main entry point. Pipeline:
        1. Determine location
        2. Gather visible entities, items, clues
        3. Gather auditory and olfactory observations
        4. Gather container contents (if collapsed and open)
        5. Apply filters (physical, environmental, character)
        6. Generate narrative

        Args:
            context: Who is observing and how

        Returns:
            Complete subjective view
        """
        # Determine location
        location_id = context.location_id or self._atlas.find_location_at(context.position)
        if location_id is None:
            location_id = "unknown"

        # Update context with location_id for filters
        context.location_id = location_id

        loc = self._atlas.get_location(location_id)
        location_name = loc.name if loc else location_id

        # Get room info for ambient perception
        room = self._atlas.get_room(location_id)

        # Initialize view
        view = SubjectiveView(
            observer_id=context.entity_id,
            location_id=location_id,
            location_name=location_name,
            timestamp=self._ledger.current_time.isoformat(),
            weather=self._ledger.weather.value,
            lighting=self._compute_lighting(location_id),
        )

        # Set ambient sounds and smells from room
        if room:
            view.ambient_sounds = list(room.typical_sounds)
            view.ambient_smells = list(room.typical_smells)

        # Gather and filter observations (visual)
        view.observations = self._gather_observations(context, location_id)

        # Add auditory observations
        view.observations.extend(self._gather_auditory_observations(context, location_id))

        # Add olfactory observations
        view.observations.extend(self._gather_olfactory_observations(context, location_id))

        # Observe container contents (collapsed, open containers)
        view.observations.extend(self._observe_container_contents(context, location_id))

        # Gather DIGITAL observations (attention-channel).
        # Only runs when filter is enabled and attention_service is wired;
        # digital observations go through the filter chain like others.
        digital_feed_ids: list[str] = []
        if self._include_digital_filter and self._attention_service is not None:
            digital_observations = self._gather_digital_observations(context)
            view.observations.extend(digital_observations)
            digital_feed_ids = [o.source_id for o in digital_observations]

        # Apply filter chain to all observations
        view.observations = self._apply_filters(view.observations, context)

        # Extract entity/item lists
        view.entities_seen = [
            o.source_id for o in view.observations
            if o.source_type == "entity"
        ]
        view.items_noticed = [
            o.source_id for o in view.observations
            if o.source_type == "item"
        ]

        # Check clue discovery
        view.clues_found = self._check_clues(context, location_id)

        # Render narrative
        view.narrative = self._renderer(view, context)

        # Mark digital feed items as surfaced for this agent so they aren't
        # re-injected on the next render. Done after render (and after filter
        # chain) so any observation that was filtered out still counts as
        # "consumed"—the agent's digital attention processed it either way.
        if digital_feed_ids and self._attention_service is not None:
            self._attention_service.mark_consumed(
                context.entity_id, digital_feed_ids
            )

        return view

    def _gather_observations(
        self,
        context: ObserverContext,
        location_id: str,
    ) -> list[Observation]:
        """Gather all observations for the location."""
        observations: list[Observation] = []

        # Observe entities
        for entity in self._ledger.entities_at(location_id):
            if entity.entity_id == context.entity_id:
                continue  # Don't observe self

            obs = self._observe_entity(context, entity)
            if obs:
                observations.append(obs)

        # Observe items
        for item in self._ledger.items_at(location_id):
            obs = self._observe_item(context, item)
            if obs:
                observations.append(obs)

        return observations

    def _observe_entity(
        self,
        context: ObserverContext,
        entity: "EntityState",
    ) -> Observation | None:
        """Create observation for an entity."""
        from synthetic_socio_wind_tunnel.ledger.models import EntityState

        # Line of sight check
        can_see, _ = self._atlas.can_see(context.position, entity.position)
        if not can_see:
            return None

        distance = context.position.distance_to(entity.position)

        # Determine if notable
        is_notable = entity.entity_id in context.suspicions

        # Generate interpretation based on observer
        if context.guilt_level > 0.5 and entity.entity_id in context.suspicions:
            interpreted = f"{entity.entity_id} is watching... do they know?"
        elif entity.activity:
            interpreted = f"{entity.entity_id} is {entity.activity}"
        else:
            interpreted = f"{entity.entity_id} is here"

        return Observation(
            sense=SenseType.VISUAL,
            source_id=entity.entity_id,
            source_type="entity",
            distance=distance,
            raw=f"{entity.entity_id} at {entity.location_id}",
            interpreted=interpreted,
            is_notable=is_notable,
        )

    def _observe_item(
        self,
        context: ObserverContext,
        item: "ItemState",
    ) -> Observation | None:
        """Create observation for an item."""
        from synthetic_socio_wind_tunnel.ledger.models import ItemState

        # Hidden items require investigation skill
        if item.is_hidden:
            if context.investigation_skill < item.discovery_skill:
                return None

        # Distance
        distance = 0.0
        if item.position:
            distance = context.position.distance_to(item.position)

        # Determine if notable
        is_notable = (
            item.item_id in context.looking_for or
            any(item.name.lower() in fact.lower() for fact in context.knowledge)
        )

        # Interpretation
        tags = []
        if is_notable:
            if context.investigation_skill > 0.7:
                interpreted = f"{item.name} - this could be important"
                tags.append("evidence")
            else:
                interpreted = f"{item.name} catches your attention"
        else:
            interpreted = item.name

        return Observation(
            sense=SenseType.VISUAL,
            source_id=item.item_id,
            source_type="item",
            distance=distance,
            raw=item.name,
            interpreted=interpreted,
            is_notable=is_notable,
            tags=tags,
        )

    def _check_clues(
        self,
        context: ObserverContext,
        location_id: str,
    ) -> list[str]:
        """Check for clue discoveries (READ only - doesn't mark discovered)."""
        found = []
        for clue in self._ledger.undiscovered_clues_at(location_id):
            if context.investigation_skill >= clue.min_skill:
                found.append(clue.clue_id)
        return found

    def _gather_auditory_observations(
        self,
        context: ObserverContext,
        location_id: str,
    ) -> list[Observation]:
        """Gather sounds from current and nearby locations."""
        observations: list[Observation] = []

        if context.hearing_impaired:
            return observations

        # Room ambient sounds
        room = self._atlas.get_room(location_id)
        if room and room.typical_sounds:
            for sound in room.typical_sounds:
                observations.append(Observation(
                    sense=SenseType.AUDITORY,
                    source_id=f"ambient:{location_id}:{sound}",
                    source_type="ambient",
                    source_location=location_id,
                    raw=sound,
                    interpreted=sound.replace("_", " "),
                    distance=0.0,
                ))

        # Sounds from nearby rooms (through open doors)
        if room:
            for neighbor_id in room.connected_rooms:
                # Check if door is open
                door = self._atlas.get_door_between(location_id, neighbor_id)
                if door and not self._ledger.is_door_open(door.door_id):
                    # Closed door - muffled sounds only
                    neighbor_room = self._atlas.get_room(neighbor_id)
                    if neighbor_room:
                        for entity in self._ledger.entities_at(neighbor_id):
                            if entity.activity and "loud" in entity.activity.lower():
                                observations.append(Observation(
                                    sense=SenseType.AUDITORY,
                                    source_id=f"muffled:{entity.entity_id}",
                                    source_type="entity",
                                    source_location=neighbor_id,
                                    raw=f"muffled sounds from {neighbor_id}",
                                    interpreted="You hear muffled sounds from nearby",
                                    distance=5.0,
                                    confidence=0.4,
                                    tags=["muffled"],
                                ))
                else:
                    # Open door or no door - can hear clearly
                    neighbor_room = self._atlas.get_room(neighbor_id)
                    if neighbor_room and neighbor_room.typical_sounds:
                        for sound in neighbor_room.typical_sounds:
                            observations.append(Observation(
                                sense=SenseType.AUDITORY,
                                source_id=f"nearby:{neighbor_id}:{sound}",
                                source_type="ambient",
                                source_location=neighbor_id,
                                raw=sound,
                                interpreted=f"{sound.replace('_', ' ')} from {neighbor_room.name}",
                                distance=5.0,
                                confidence=0.7,
                            ))

        return observations

    def _gather_olfactory_observations(
        self,
        context: ObserverContext,
        location_id: str,
    ) -> list[Observation]:
        """Gather smells from current and nearby locations."""
        observations: list[Observation] = []

        # Room ambient smells
        room = self._atlas.get_room(location_id)
        if room and room.typical_smells:
            for smell in room.typical_smells:
                observations.append(Observation(
                    sense=SenseType.OLFACTORY,
                    source_id=f"ambient:{location_id}:{smell}",
                    source_type="ambient",
                    source_location=location_id,
                    raw=smell,
                    interpreted=smell.replace("_", " "),
                    distance=0.0,
                ))

        # Smells from nearby rooms (through open doors)
        if room:
            for neighbor_id in room.connected_rooms:
                door = self._atlas.get_door_between(location_id, neighbor_id)
                if door and not self._ledger.is_door_open(door.door_id):
                    # Closed door - smells don't pass much
                    continue

                neighbor_room = self._atlas.get_room(neighbor_id)
                if neighbor_room and neighbor_room.typical_smells:
                    for smell in neighbor_room.typical_smells:
                        observations.append(Observation(
                            sense=SenseType.OLFACTORY,
                            source_id=f"nearby:{neighbor_id}:{smell}",
                            source_type="ambient",
                            source_location=neighbor_id,
                            raw=smell,
                            interpreted=f"faint smell of {smell.replace('_', ' ')}",
                            distance=5.0,
                            confidence=0.5,
                            tags=["faint"],
                        ))

        return observations

    def _observe_container_contents(
        self,
        context: ObserverContext,
        location_id: str,
    ) -> list[Observation]:
        """
        Observe items inside collapsed, open containers.

        Items in containers are only visible if:
        1. Container's contents have been collapsed (Schrödinger)
        2. Container is open (or transparent like glass display)
        """
        observations: list[Observation] = []

        room = self._atlas.get_room(location_id)
        if not room:
            return observations

        for container_id, container_def in room.containers.items():
            # Check if collapsed
            container_state = self._ledger.get_container_state(container_id)
            if not container_state or not container_state.contents_collapsed:
                continue

            # Check if open (or low search difficulty = visible contents)
            if not container_state.is_open and container_def.search_difficulty > 0.1:
                continue

            # Observe items in container
            for item in self._ledger.items_in(container_id):
                # Hidden items still require skill
                if item.is_hidden:
                    if context.investigation_skill < item.discovery_skill:
                        continue

                is_notable = (
                    item.item_id in context.looking_for or
                    any(item.name.lower() in fact.lower() for fact in context.knowledge)
                )

                tags = ["in_container", f"container:{container_id}"]
                if is_notable:
                    tags.append("evidence")

                observations.append(Observation(
                    sense=SenseType.VISUAL,
                    source_id=item.item_id,
                    source_type="item",
                    source_location=location_id,
                    raw=f"{item.name} in {container_def.name}",
                    interpreted=f"{item.name} in the {container_def.name}",
                    distance=1.0,
                    is_notable=is_notable,
                    tags=tags,
                ))

        return observations

    def _gather_digital_observations(
        self,
        context: ObserverContext,
    ) -> list[Observation]:
        """
        Pull pending FeedItems from AttentionService and convert each into
        an Observation(sense=DIGITAL).

        Confidence initialises from digital_state.notification_responsiveness
        (which AgentRuntime copies from profile.digital.notification_responsiveness).
        The filter chain (DigitalAttentionFilter) then applies missed tags.
        """
        if self._attention_service is None or context.digital_state is None:
            return []

        base_confidence = context.digital_state.notification_responsiveness

        observations: list[Observation] = []
        for feed_item_id in context.digital_state.pending_notifications:
            item = self._attention_service.get_feed_item(feed_item_id)
            if item is None:
                content = f"[unknown feed item {feed_item_id}]"
                source_category = "feed_item"
            else:
                content = item.content
                source_category = item.source
            observations.append(Observation(
                sense=SenseType.DIGITAL,
                source_id=feed_item_id,
                source_type="feed_item",
                confidence=base_confidence,
                raw=content,
                interpreted=content,
                is_notable=True,
                tags=[f"feed_source:{source_category}"],
            ))
        return observations

    def _compute_lighting(self, location_id: str) -> str:
        """Compute lighting level at location."""
        time = self._ledger.time_of_day
        loc = self._atlas.get_location(location_id)

        # Indoor lighting
        has_natural = True
        has_artificial = True
        if isinstance(loc, Room):
            has_natural = loc.has_windows
            has_artificial = True  # Assume artificial light

        if time == TimeOfDay.NIGHT:
            return "artificial" if has_artificial else "dark"
        elif time in [TimeOfDay.DAWN, TimeOfDay.EVENING]:
            return "dim" if has_natural else ("artificial" if has_artificial else "dark")
        else:
            return "normal" if has_natural else "dim"

    # ========== Comparison Utilities ==========

    def compare(
        self,
        context_a: ObserverContext,
        context_b: ObserverContext,
    ) -> dict:
        """
        Compare two observers' views (for debugging Rashomon).

        Returns dict showing differences.
        """
        view_a = self.render(context_a)
        view_b = self.render(context_b)

        return {
            "same_location": view_a.location_id == view_b.location_id,
            "a_sees_entities": set(view_a.entities_seen),
            "b_sees_entities": set(view_b.entities_seen),
            "a_sees_items": set(view_a.items_noticed),
            "b_sees_items": set(view_b.items_noticed),
            "a_finds_clues": set(view_a.clues_found),
            "b_finds_clues": set(view_b.clues_found),
            "only_a_sees": set(view_a.items_noticed) - set(view_b.items_noticed),
            "only_b_sees": set(view_b.items_noticed) - set(view_a.items_noticed),
        }
