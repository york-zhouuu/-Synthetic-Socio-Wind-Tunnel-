"""
Engine Module - Write Operations (引擎层)

Contains services that modify the world state:
- SimulationService: Movement, interaction, physics
- CollapseService: Schrödinger detail generation
- NavigationService: Route planning and pathfinding

Engine services READ from Atlas + Ledger, WRITE to Ledger only.
NavigationService is read-only (pure queries).

v0.4.0: Added DirectorContext for narrative control
"""

from synthetic_socio_wind_tunnel.engine.simulation import SimulationService, SimulationResult
from synthetic_socio_wind_tunnel.engine.collapse import CollapseService, DirectorContext
from synthetic_socio_wind_tunnel.engine.navigation import NavigationService, NavigationResult, PathStrategy

__all__ = [
    "SimulationService",
    "SimulationResult",
    "CollapseService",
    "DirectorContext",
    "NavigationService",
    "NavigationResult",
    "PathStrategy",
]
