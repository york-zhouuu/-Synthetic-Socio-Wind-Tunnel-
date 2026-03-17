"""
Synthetic Socio Wind Tunnel - CQRS Cognitive Map System

A cognitive map system following the Theater Model:
- Atlas (布景组): Read-only static map data
- Ledger (道具组): Read-write dynamic state
- Engine (引擎层): Write operations (Simulation, Collapse) + Navigation
- Perception (感知层): Read operations (Pipeline, Filters, Exploration)
- Cartography (制图服务): Offline map building

Public API exports the main services and models.

v0.4.0: Added structured error codes, events, director context, snapshots
v0.4.1: Added ExplorationService for visibility-based exploration
"""

from synthetic_socio_wind_tunnel.atlas import Atlas
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.engine import (
    SimulationService,
    SimulationResult,
    CollapseService,
    DirectorContext,
    NavigationService,
)
from synthetic_socio_wind_tunnel.perception import (
    PerceptionPipeline,
    ObserverContext,
    SubjectiveView,
    ExplorationService,
)
from synthetic_socio_wind_tunnel.core.errors import SimulationErrorCode, EventType
from synthetic_socio_wind_tunnel.core.events import WorldEvent
from synthetic_socio_wind_tunnel.perception.models import (
    EntitySnapshot,
    ItemSnapshot,
    ContainerSnapshot,
    ClueSnapshot,
)

__version__ = "0.4.1"
__all__ = [
    # Data Layer
    "Atlas",
    "Ledger",
    # Engine Layer (Write + Navigation)
    "SimulationService",
    "SimulationResult",
    "CollapseService",
    "DirectorContext",
    "NavigationService",
    # Perception Layer (Read)
    "PerceptionPipeline",
    "ObserverContext",
    "SubjectiveView",
    "ExplorationService",
    # Snapshot Models
    "EntitySnapshot",
    "ItemSnapshot",
    "ContainerSnapshot",
    "ClueSnapshot",
    # Error & Event System
    "SimulationErrorCode",
    "EventType",
    "WorldEvent",
]
