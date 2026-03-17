"""
Atlas Module - The Stage (布景组)

Read-only static map data. Once loaded, never modified during gameplay.
Contains:
- Geometric data (polygons, coordinates)
- Physical properties (materials, connectivity)
- Spatial queries (pathfinding, line of sight)
"""

from synthetic_socio_wind_tunnel.atlas.models import (
    Coord,
    Polygon,
    Material,
    Room,
    Building,
    OutdoorArea,
    Connection,
    Region,
)
from synthetic_socio_wind_tunnel.atlas.service import Atlas

__all__ = [
    "Coord",
    "Polygon",
    "Material",
    "Room",
    "Building",
    "OutdoorArea",
    "Connection",
    "Region",
    "Atlas",
]
