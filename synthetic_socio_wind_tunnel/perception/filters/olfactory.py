"""Olfactory perception filter (smell propagation)."""

from __future__ import annotations
from typing import TYPE_CHECKING

from synthetic_socio_wind_tunnel.perception.filters.base import Filter
from synthetic_socio_wind_tunnel.perception.models import SenseType

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.atlas import Atlas
    from synthetic_socio_wind_tunnel.ledger import Ledger
    from synthetic_socio_wind_tunnel.perception.models import ObserverContext, Observation


class OlfactoryFilter(Filter):
    """
    Filter based on smell propagation.

    Adjusts olfactory observation confidence based on:
    - Distance (smells dissipate)
    - Ventilation (windows, doors)
    - Weather (rain dampens, wind carries)
    - Conflicting smells
    """

    def __init__(self, atlas: "Atlas", ledger: "Ledger"):
        self._atlas = atlas
        self._ledger = ledger

    def apply(
        self,
        observation: "Observation",
        context: "ObserverContext",
    ) -> "Observation | None":
        """Apply olfactory propagation constraints."""
        # Only affects olfactory observations
        if observation.sense != SenseType.OLFACTORY:
            return observation

        # Distance attenuation (smells fade quickly)
        distance = observation.distance
        if distance > 20:
            observation.confidence *= 0.1
        elif distance > 10:
            observation.confidence *= 0.3
        elif distance > 5:
            observation.confidence *= 0.6
        elif distance > 2:
            observation.confidence *= 0.8

        # Outdoor smells disperse faster
        if self._is_outdoor(context.location_id):
            from synthetic_socio_wind_tunnel.ledger.models import Weather
            weather = self._ledger.weather

            if weather in [Weather.RAIN, Weather.HEAVY_RAIN]:
                # Rain dampens smells
                observation.confidence *= 0.5
                observation.tags.append("rain_dampened")
            elif weather == Weather.CLEAR:
                # Clear day with wind disperses
                observation.confidence *= 0.7

        # Indoor smell persistence
        room = self._atlas.get_room(context.location_id) if context.location_id else None
        if room:
            # Rooms with windows are better ventilated
            if room.has_windows:
                observation.confidence *= 0.9
            else:
                # Enclosed spaces trap smells
                observation.confidence *= 1.1

            # Competing smells reduce specificity
            if room.typical_smells and len(room.typical_smells) > 2:
                observation.confidence *= 0.8
                observation.tags.append("mixed_smells")

        # Smells from other rooms
        if context.location_id and observation.source_location:
            if context.location_id != observation.source_location:
                # Smell from another room
                attenuation = self._compute_smell_attenuation(
                    context.location_id,
                    observation.source_location
                )
                observation.confidence *= attenuation
                if attenuation < 0.5:
                    observation.tags.append("faint")

        # Filter out imperceptible smells
        if observation.confidence < 0.1:
            return None

        return observation

    def _compute_smell_attenuation(self, from_room: str, to_room: str) -> float:
        """
        Compute smell attenuation between rooms.

        Open doors and connected rooms allow smell to pass.
        """
        from_room_obj = self._atlas.get_room(from_room)
        if not from_room_obj:
            return 0.2

        if to_room in from_room_obj.connected_rooms:
            # Connected rooms
            door = self._atlas._region.get_door_between(from_room, to_room)
            if door:
                if self._ledger.is_door_open(door.door_id):
                    return 0.7  # Open door
                else:
                    return 0.2  # Closed door blocks most smell
            return 0.5  # Archway or opening

        # Not connected - very little smell passes through walls
        return 0.1

    def _is_outdoor(self, location_id: str | None) -> bool:
        """Check if location is outdoors."""
        if not location_id:
            return False
        return self._atlas.get_outdoor_area(location_id) is not None
