"""Physical perception filters (visibility, sound)."""

from __future__ import annotations
from typing import TYPE_CHECKING

from synthetic_socio_wind_tunnel.perception.filters.base import Filter

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.atlas import Atlas
    from synthetic_socio_wind_tunnel.ledger import Ledger
    from synthetic_socio_wind_tunnel.perception.models import ObserverContext, Observation


class PhysicalFilter(Filter):
    """Filter based on physical constraints (line of sight, distance)."""

    def __init__(self, atlas: "Atlas", ledger: "Ledger"):
        self._atlas = atlas
        self._ledger = ledger

    def apply(
        self,
        observation: "Observation",
        context: "ObserverContext",
    ) -> "Observation | None":
        """Apply physical visibility constraints."""
        # Distance check
        max_range = self._get_max_range(context)
        if observation.distance > max_range:
            return None

        # Lighting affects confidence
        time_of_day = self._ledger.time_of_day
        from synthetic_socio_wind_tunnel.ledger.models import TimeOfDay

        if time_of_day == TimeOfDay.NIGHT:
            observation.confidence *= 0.5
        elif time_of_day in [TimeOfDay.DAWN, TimeOfDay.EVENING]:
            observation.confidence *= 0.8

        # Weather affects visibility
        from synthetic_socio_wind_tunnel.ledger.models import Weather
        weather = self._ledger.weather
        if weather == Weather.FOG:
            observation.confidence *= 0.4
        elif weather in [Weather.RAIN, Weather.HEAVY_RAIN]:
            observation.confidence *= 0.7

        return observation

    def _get_max_range(self, context: "ObserverContext") -> float:
        """Calculate maximum visible range."""
        base = 50.0

        # Vision impairment
        if context.vision_impaired:
            base *= 0.5

        # Weather
        from synthetic_socio_wind_tunnel.ledger.models import Weather
        weather = self._ledger.weather
        if weather == Weather.FOG:
            base *= 0.3
        elif weather == Weather.HEAVY_RAIN:
            base *= 0.5

        return base
