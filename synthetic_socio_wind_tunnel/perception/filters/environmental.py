"""Environmental perception filter (lighting, weather, time)."""

from __future__ import annotations
from typing import TYPE_CHECKING

from synthetic_socio_wind_tunnel.perception.filters.base import Filter
from synthetic_socio_wind_tunnel.perception.models import SenseType

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.atlas import Atlas
    from synthetic_socio_wind_tunnel.ledger import Ledger
    from synthetic_socio_wind_tunnel.perception.models import ObserverContext, Observation


class EnvironmentalFilter(Filter):
    """
    Filter based on environmental conditions.

    Adjusts observation confidence based on:
    - Lighting (room typical_lighting, time of day)
    - Weather (rain, fog affects outdoor visibility)
    - Room properties (windows, materials)
    """

    def __init__(self, atlas: "Atlas", ledger: "Ledger"):
        self._atlas = atlas
        self._ledger = ledger

    def apply(
        self,
        observation: "Observation",
        context: "ObserverContext",
    ) -> "Observation | None":
        """Apply environmental constraints."""
        # Get location info
        location_id = context.location_id
        location = self._atlas.get_location(location_id) if location_id else None

        # Calculate effective lighting
        lighting = self._compute_lighting(context, location)

        # Apply lighting penalty to visual observations
        if observation.sense == SenseType.VISUAL:
            if lighting == "dark":
                observation.confidence *= 0.2
                observation.tags.append("dark_conditions")
            elif lighting == "dim":
                observation.confidence *= 0.6
                observation.tags.append("dim_lighting")
            elif lighting == "bright":
                # Bright lighting slightly helps
                observation.confidence = min(1.0, observation.confidence * 1.1)

        # Weather affects outdoor observations
        if self._is_outdoor(location_id):
            weather = self._ledger.weather

            from synthetic_socio_wind_tunnel.ledger.models import Weather

            if observation.sense == SenseType.VISUAL:
                if weather == Weather.FOG:
                    observation.confidence *= 0.3
                    observation.tags.append("foggy")
                elif weather == Weather.HEAVY_RAIN:
                    observation.confidence *= 0.5
                    observation.tags.append("heavy_rain")
                elif weather == Weather.RAIN:
                    observation.confidence *= 0.7

            # Rain affects auditory
            if observation.sense == SenseType.AUDITORY:
                if weather in [Weather.RAIN, Weather.HEAVY_RAIN]:
                    observation.confidence *= 0.5
                    observation.tags.append("rain_noise")

        # Filter out very low confidence observations
        if observation.confidence < 0.1:
            return None

        return observation

    def _compute_lighting(self, context: "ObserverContext", location) -> str:
        """
        Compute effective lighting level.

        Combines room typical_lighting with time of day.
        """
        from synthetic_socio_wind_tunnel.ledger.models import TimeOfDay

        # Get room's typical lighting if available
        typical = "normal"
        if location and hasattr(location, "typical_lighting"):
            typical = location.typical_lighting

        # Time of day modifier
        time_of_day = self._ledger.time_of_day

        # Indoor lighting mostly depends on room
        if not self._is_outdoor(context.location_id):
            # Unless it's a dark room at night
            if typical == "dark":
                return "dark"
            elif time_of_day == TimeOfDay.NIGHT and typical != "bright":
                return "dim"
            return typical

        # Outdoor lighting depends on time
        if time_of_day == TimeOfDay.NIGHT:
            return "dark"
        elif time_of_day in [TimeOfDay.DAWN, TimeOfDay.EVENING]:
            return "dim"
        return "normal"

    def _is_outdoor(self, location_id: str | None) -> bool:
        """Check if location is outdoors."""
        if not location_id:
            return False
        return self._atlas.get_outdoor_area(location_id) is not None
