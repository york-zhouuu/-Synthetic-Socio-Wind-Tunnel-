"""
Perception Module - Read Operations (感知层)

The "Camera" that renders subjective views:
- PerceptionPipeline: Main rendering pipeline
- ExplorationService: Visibility-based exploration queries
- Filters: Detective, Guilty, Normal perspectives
- ObserverContext: Who is observing and how
- SubjectiveView: The rendered output

READ ONLY - never modifies Atlas or Ledger.
(Exception: ExplorationService.discover_location writes to Ledger for API convenience)
"""

from synthetic_socio_wind_tunnel.perception.models import ObserverContext, SubjectiveView, Observation
from synthetic_socio_wind_tunnel.perception.pipeline import PerceptionPipeline
from synthetic_socio_wind_tunnel.perception.exploration import ExplorationService, VisibleLayout

__all__ = [
    "ObserverContext",
    "SubjectiveView",
    "Observation",
    "PerceptionPipeline",
    "ExplorationService",
    "VisibleLayout",
]
