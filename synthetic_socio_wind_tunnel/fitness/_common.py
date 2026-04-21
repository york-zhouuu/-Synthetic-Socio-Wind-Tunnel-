"""Shared helpers for fitness audits — atlas loading, signatures, small utilities."""

from __future__ import annotations

import hashlib
import math
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.atlas import Atlas


def atlas_signature(path: Path) -> str:
    """SHA-256 of the atlas JSON bytes. Used to mark reports as reproducible."""
    path = Path(path)
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_atlas(path: Path) -> "Atlas":
    """Load Atlas from JSON path using the canonical Atlas.from_json entry."""
    from synthetic_socio_wind_tunnel.atlas import Atlas
    return Atlas.from_json(path)


@contextmanager
def timed():
    """Yield a callable returning elapsed wall seconds."""
    start = time.perf_counter()
    result: dict[str, float] = {"elapsed": 0.0}
    def _get() -> float:
        return result["elapsed"]
    try:
        yield _get
    finally:
        result["elapsed"] = time.perf_counter() - start


def percentile(values: list[float], p: float) -> float:
    """Simple percentile (nearest-rank). Empty list → 0.0."""
    if not values:
        return 0.0
    sorted_v = sorted(values)
    k = max(0, min(len(sorted_v) - 1, math.ceil(p * len(sorted_v)) - 1))
    return sorted_v[k]


def iso_now() -> datetime:
    return datetime.now()
