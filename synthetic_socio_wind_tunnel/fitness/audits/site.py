"""
Site fitness diagnostic - atlas adequacy snapshot.

Pure data report: named / residential / density. Not a gate. Lane Cove is the
confirmed site; notes flag only extreme values (e.g. density 0, empty atlas)
rather than comparing to any external target.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from synthetic_socio_wind_tunnel.fitness.report import (
    AuditResult,
    AuditStatus,
    CategoryResult,
    SiteFitness,
)

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.atlas import Atlas


_ANON_BUILDING_RE = re.compile(r"^(building_\d+|house)$", re.IGNORECASE)


def compute_site_fitness(atlas: "Atlas") -> SiteFitness:
    """Compute the diagnostic numbers; returned as SiteFitness for top-level report."""
    region = atlas.region
    buildings = list(region.buildings.values())
    total = len(buildings)

    if total == 0:
        return SiteFitness(
            named_building_ratio=0.0,
            residential_ratio=0.0,
            density_buildings_per_km2=0.0,
            notes=("atlas has no buildings",),
        )

    named = sum(1 for b in buildings if b.name and not _ANON_BUILDING_RE.match(b.name))
    residential = sum(1 for b in buildings if b.building_type == "residential")

    bmin = region.bounds_min
    bmax = region.bounds_max
    width_m = max(1e-6, bmax.x - bmin.x)
    height_m = max(1e-6, bmax.y - bmin.y)
    area_km2 = (width_m * height_m) / 1_000_000.0
    density = total / max(1e-6, area_km2)

    notes: list[str] = []
    if total < 100:
        notes.append(f"small atlas: only {total} buildings")
    if density < 1.0:
        notes.append(f"very low density: {density:.2f} buildings/km² (check bounds)")

    return SiteFitness(
        named_building_ratio=named / total,
        residential_ratio=residential / total,
        density_buildings_per_km2=density,
        notes=tuple(notes),
    )


def audit_site_fitness(atlas: "Atlas") -> tuple[CategoryResult, SiteFitness]:
    """
    Returns a CategoryResult (all pass — this is diagnostic, not a gate) plus the
    SiteFitness object for top-level inclusion in FitnessReport.
    """
    sf = compute_site_fitness(atlas)

    results: list[AuditResult] = []
    results.append(AuditResult(
        id="site.named-building-ratio",
        status=AuditStatus.PASS,
        detail=f"{sf.named_building_ratio:.2%}",
        extras={"value": sf.named_building_ratio},
    ))
    results.append(AuditResult(
        id="site.residential-ratio",
        status=AuditStatus.PASS,
        detail=f"{sf.residential_ratio:.2%}",
        extras={"value": sf.residential_ratio},
    ))
    results.append(AuditResult(
        id="site.density",
        status=AuditStatus.PASS,
        detail=f"{sf.density_buildings_per_km2:.0f} buildings/km²",
        extras={"value": sf.density_buildings_per_km2},
    ))
    if sf.notes:
        notes_text = "; ".join(sf.notes)
        results.append(AuditResult(
            id="site.notes",
            status=AuditStatus.PASS,
            detail=notes_text,
            extras={"notes": list(sf.notes)},
        ))

    return (
        CategoryResult(category="site-fitness", results=tuple(results)),
        sf,
    )
