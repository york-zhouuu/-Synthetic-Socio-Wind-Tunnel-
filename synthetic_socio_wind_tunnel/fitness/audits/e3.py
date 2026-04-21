"""E3 Shared Perception 可行性审计。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.fitness.report import AuditResult, AuditStatus, CategoryResult
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState, ItemState
from synthetic_socio_wind_tunnel.perception import PerceptionPipeline
from synthetic_socio_wind_tunnel.perception.models import ObserverContext

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.atlas import Atlas


def audit_e3_shared_perception(atlas: "Atlas") -> CategoryResult:
    """
    Two checks:
    - looking-for-propagation:    setting ObserverContext.looking_for on a group
                                  aligns their is_notable judgements on same item
    - shared-task-memory-seam:    SKIP — Phase 1 has no persistent per-agent task
                                  store; mitigation points at memory change
    """
    results: list[AuditResult] = []

    # Shared-task-memory-seam: skip with mitigation pointer
    results.append(AuditResult(
        id="e3.shared-task-memory-seam",
        status=AuditStatus.SKIP,
        detail="Phase 1 has no persistent per-agent task store; see memory change",
        mitigation_change="memory",
    ))

    # Looking-for-propagation: find a location and place a 'lost_cat_poster' item
    outdoor_ids = list(atlas.region.outdoor_areas.keys())
    building_ids = list(atlas.region.buildings.keys())
    candidates = outdoor_ids + building_ids
    if not candidates:
        results.append(AuditResult(
            id="e3.looking-for-propagation",
            status=AuditStatus.SKIP,
            detail="atlas has no locations",
            mitigation_change="cartography",
        ))
        return CategoryResult(category="e3-shared-perception", results=tuple(results))

    loc_id = candidates[0]

    ledger = Ledger()
    ledger.current_time = datetime(2026, 4, 20, 12, 0, 0)
    # Place a shared target item at the location
    ledger.set_item(ItemState(
        item_id="lost_cat_poster",
        name="lost_cat_poster",
        location_id=loc_id,
        position=Coord(x=0.5, y=0.5),
    ))

    # Three agents all co-located
    for i, aid in enumerate(["alpha", "beta", "gamma"]):
        ledger.set_entity(EntityState(
            entity_id=aid,
            location_id=loc_id,
            position=Coord(x=float(i), y=float(i)),
        ))

    pipeline = PerceptionPipeline(atlas, ledger)

    notable_counts: dict[str, int] = {}
    for aid in ["alpha", "beta", "gamma"]:
        ctx = ObserverContext(
            entity_id=aid,
            position=Coord(x=0.0, y=0.0),
            location_id=loc_id,
            looking_for=["lost_cat_poster"],
        )
        view = pipeline.render(ctx)
        # Item observations that target the poster
        notable_obs = [
            o for o in view.observations
            if o.source_id == "lost_cat_poster" and o.is_notable
        ]
        notable_counts[aid] = len(notable_obs)

    if all(c >= 1 for c in notable_counts.values()):
        results.append(AuditResult(
            id="e3.looking-for-propagation",
            status=AuditStatus.PASS,
            detail=f"all three agents flagged poster as notable ({notable_counts})",
            extras={"notable_counts": notable_counts},
        ))
    else:
        results.append(AuditResult(
            id="e3.looking-for-propagation",
            status=AuditStatus.FAIL,
            detail=f"expected all three agents to notable-flag shared target; got {notable_counts}",
            mitigation_change="perception",
        ))

    return CategoryResult(category="e3-shared-perception", results=tuple(results))
