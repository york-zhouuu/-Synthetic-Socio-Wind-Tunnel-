"""Base filter interface."""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.perception.models import ObserverContext, Observation


class Filter(ABC):
    """Base class for perception filters."""

    @abstractmethod
    def apply(
        self,
        observation: "Observation",
        context: "ObserverContext",
    ) -> "Observation | None":
        """
        Apply filter to an observation.

        Returns:
            Modified observation, or None to filter out
        """
        ...
