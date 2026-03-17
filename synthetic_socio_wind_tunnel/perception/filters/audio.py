"""Audio perception filter (sound propagation, walls)."""

from __future__ import annotations
from typing import TYPE_CHECKING

from synthetic_socio_wind_tunnel.perception.filters.base import Filter
from synthetic_socio_wind_tunnel.perception.models import SenseType

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.atlas import Atlas
    from synthetic_socio_wind_tunnel.ledger import Ledger
    from synthetic_socio_wind_tunnel.perception.models import ObserverContext, Observation


class AudioFilter(Filter):
    """
    Filter based on sound propagation.

    Adjusts auditory observation confidence based on:
    - Distance (sound attenuates with distance)
    - Wall materials (sound absorption)
    - Doors (open vs closed)
    - Ambient noise levels
    """

    def __init__(self, atlas: "Atlas", ledger: "Ledger"):
        self._atlas = atlas
        self._ledger = ledger

    def apply(
        self,
        observation: "Observation",
        context: "ObserverContext",
    ) -> "Observation | None":
        """Apply audio propagation constraints."""
        # Only affects auditory observations
        if observation.sense != SenseType.AUDITORY:
            return observation

        # Distance attenuation
        distance = observation.distance
        if distance > 50:
            # Sound doesn't travel far
            observation.confidence *= 0.1
        elif distance > 30:
            observation.confidence *= 0.3
        elif distance > 15:
            observation.confidence *= 0.6
        elif distance > 5:
            observation.confidence *= 0.8

        # Check if sound must pass through walls/doors
        if context.location_id and observation.source_location:
            if context.location_id != observation.source_location:
                # Sound is from a different room
                wall_penalty = self._compute_wall_attenuation(
                    context.location_id,
                    observation.source_location
                )
                observation.confidence *= wall_penalty
                if wall_penalty < 0.5:
                    observation.tags.append("muffled")

        # Ambient noise affects ability to hear
        room = self._atlas.get_room(context.location_id) if context.location_id else None
        if room and room.typical_sounds:
            # More ambient sounds = harder to distinguish specific sounds
            noise_level = len(room.typical_sounds)
            if noise_level > 3:
                observation.confidence *= 0.7
                observation.tags.append("noisy_environment")

        # Filter out inaudible sounds
        if observation.confidence < 0.1:
            return None

        return observation

    def _compute_wall_attenuation(self, from_room: str, to_room: str) -> float:
        """
        Compute sound attenuation through walls/doors between rooms.

        Returns a multiplier (0-1) for confidence.
        """
        # Check if rooms are directly connected
        from_room_obj = self._atlas.get_room(from_room)
        if not from_room_obj:
            return 0.3  # Default for unknown topology

        if to_room in from_room_obj.connected_rooms:
            # Connected rooms - check door state
            door = self._atlas._region.get_door_between(from_room, to_room)
            if door:
                if self._ledger.is_door_open(door.door_id):
                    return 0.9  # Open door - almost no attenuation
                else:
                    return 0.4  # Closed door - significant attenuation
            return 0.7  # No door, but connected (archway?)

        # Not directly connected - sound must go through walls
        to_room_obj = self._atlas.get_room(to_room)
        if to_room_obj:
            # Wall material affects sound
            material = from_room_obj.wall_material
            return 1.0 - material.sound_absorption

        return 0.2  # Default heavy attenuation
