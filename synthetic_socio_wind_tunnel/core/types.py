"""
Core types shared across all layers.

These fundamental types are used by both Atlas (static) and Ledger (dynamic)
layers without creating cross-layer dependencies.
"""

from __future__ import annotations
from pydantic import BaseModel


class Coord(BaseModel):
    """2D coordinate in game space. Units are approximately meters."""
    x: float
    y: float

    model_config = {"frozen": True}

    def distance_to(self, other: "Coord") -> float:
        """Euclidean distance to another coordinate."""
        return ((self.x - other.x) ** 2 + (self.y - other.y) ** 2) ** 0.5

    def __hash__(self) -> int:
        return hash((self.x, self.y))


class Polygon(BaseModel):
    """Closed polygon for collision/containment. Vertices in clockwise order."""
    vertices: tuple[Coord, ...]

    model_config = {"frozen": True}

    def contains(self, point: Coord) -> bool:
        """Ray casting algorithm for point-in-polygon test."""
        n = len(self.vertices)
        if n < 3:
            return False
        inside = False
        j = n - 1
        for i in range(n):
            vi, vj = self.vertices[i], self.vertices[j]
            if ((vi.y > point.y) != (vj.y > point.y) and
                point.x < (vj.x - vi.x) * (point.y - vi.y) / (vj.y - vi.y) + vi.x):
                inside = not inside
            j = i
        return inside

    @property
    def center(self) -> Coord:
        """Centroid of the polygon."""
        if not self.vertices:
            return Coord(x=0, y=0)
        return Coord(
            x=sum(v.x for v in self.vertices) / len(self.vertices),
            y=sum(v.y for v in self.vertices) / len(self.vertices),
        )

    @property
    def bounds(self) -> tuple[Coord, Coord]:
        """Bounding box as (min, max) corners."""
        if not self.vertices:
            return Coord(x=0, y=0), Coord(x=0, y=0)
        return (
            Coord(x=min(v.x for v in self.vertices), y=min(v.y for v in self.vertices)),
            Coord(x=max(v.x for v in self.vertices), y=max(v.y for v in self.vertices)),
        )
