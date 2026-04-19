"""
Map Service — Agent-friendly query interface for the world map.

This module provides the single query layer agents use to make decisions.
It combines Atlas (static physical facts) + Ledger (dynamic state + agent knowledge)
into structured, agent-usable responses.

Key principle: Map returns OBSERVABLE FACTS.
The agent (LLM) makes its own judgment about what to do with them.
"""

from synthetic_socio_wind_tunnel.map_service.service import MapService
from synthetic_socio_wind_tunnel.map_service.models import (
    KnownDestination,
    CurrentScene,
    LocationDetail,
)

__all__ = [
    "MapService",
    "KnownDestination",
    "CurrentScene",
    "LocationDetail",
]
