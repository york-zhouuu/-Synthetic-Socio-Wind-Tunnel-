"""E1 Digital Lure 可行性审计。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.attention import (
    AttentionService,
    AttentionState,
    DigitalProfile,
    FeedItem,
)
from synthetic_socio_wind_tunnel.fitness.report import AuditResult, AuditStatus, CategoryResult
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.perception import PerceptionPipeline
from synthetic_socio_wind_tunnel.perception.models import ObserverContext, SenseType

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.atlas import Atlas


def _pick_two_locations(atlas: "Atlas") -> tuple[str, str] | None:
    """Return two distinct location ids (prefer outdoor areas)."""
    outdoor_ids = list(atlas.region.outdoor_areas.keys())
    if len(outdoor_ids) >= 2:
        return outdoor_ids[0], outdoor_ids[1]
    building_ids = list(atlas.region.buildings.keys())
    combined = outdoor_ids + building_ids
    if len(combined) >= 2:
        return combined[0], combined[1]
    return None


def audit_e1_digital_lure(atlas: "Atlas") -> CategoryResult:
    """
    Three checks:
    - push-reaches-target:        near agent SHALL see DIGITAL obs, far agent SHALL NOT
    - push-respects-attention-state: low-responsiveness agent gets missed tag
    - feed-log-extractable:       export_feed_log returns records with suppression flag
    """
    results: list[AuditResult] = []

    loc_pair = _pick_two_locations(atlas)
    if loc_pair is None:
        results.append(AuditResult(
            id="e1.push-reaches-target",
            status=AuditStatus.SKIP,
            detail="atlas has <2 locations",
            mitigation_change="cartography",
        ))
        results.append(AuditResult(
            id="e1.push-respects-attention-state",
            status=AuditStatus.SKIP,
            detail="skipped (no 2 locations)",
            mitigation_change="cartography",
        ))
        results.append(AuditResult(
            id="e1.feed-log-extractable",
            status=AuditStatus.SKIP,
            detail="skipped (no 2 locations)",
            mitigation_change="cartography",
        ))
        return CategoryResult(category="e1-digital-lure", results=tuple(results))

    near_loc, far_loc = loc_pair

    # ---- Setup ----
    ledger = Ledger()
    ledger.current_time = datetime(2026, 4, 20, 18, 0, 0)
    ledger.set_entity(EntityState(
        entity_id="near_agent",
        location_id=near_loc,
        position=Coord(x=0.0, y=0.0),
    ))
    ledger.set_entity(EntityState(
        entity_id="far_agent",
        location_id=far_loc,
        position=Coord(x=10.0, y=10.0),
    ))

    service = AttentionService(
        ledger,
        profiles={
            "near_agent": DigitalProfile(notification_responsiveness=0.8),
            "far_agent": DigitalProfile(notification_responsiveness=0.8),
        },
        seed=0,
    )
    pipeline = PerceptionPipeline(
        atlas,
        ledger,
        include_digital_filter=True,
        attention_service=service,
    )

    item = FeedItem(
        feed_item_id="f_e1_001",
        content="Local tasting event",
        source="commercial_push",
        hyperlocal_radius=300.0,
        created_at=ledger.current_time,
    )
    service.inject_feed_item(item, ["near_agent"])  # only near gets it

    # ---- Check 1: push-reaches-target ----
    near_ctx = ObserverContext(
        entity_id="near_agent",
        position=Coord(x=0.0, y=0.0),
        location_id=near_loc,
        digital_state=AttentionState(
            attention_target="phone_feed",
            pending_notifications=service.pending_for("near_agent"),
            notification_responsiveness=0.8,
        ),
    )
    far_ctx = ObserverContext(
        entity_id="far_agent",
        position=Coord(x=10.0, y=10.0),
        location_id=far_loc,
        digital_state=AttentionState(
            attention_target="phone_feed",
            pending_notifications=service.pending_for("far_agent"),
            notification_responsiveness=0.8,
        ),
    )
    near_view = pipeline.render(near_ctx)
    far_view = pipeline.render(far_ctx)

    near_digital = near_view.get_observations_by_sense(SenseType.DIGITAL)
    far_digital = far_view.get_observations_by_sense(SenseType.DIGITAL)

    if len(near_digital) == 1 and len(far_digital) == 0:
        results.append(AuditResult(
            id="e1.push-reaches-target",
            status=AuditStatus.PASS,
            detail=f"near agent saw 1 DIGITAL obs, far agent saw 0",
            extras={
                "near_digital_count": len(near_digital),
                "far_digital_count": len(far_digital),
            },
        ))
    else:
        results.append(AuditResult(
            id="e1.push-reaches-target",
            status=AuditStatus.FAIL,
            detail=f"expected (1, 0), got ({len(near_digital)}, {len(far_digital)})",
            mitigation_change="attention-channel",
            extras={
                "near_digital_count": len(near_digital),
                "far_digital_count": len(far_digital),
            },
        ))

    # ---- Check 2: push-respects-attention-state ----
    # Fresh agent with low responsiveness, phone in pocket (attention!=phone_feed)
    ledger.set_entity(EntityState(
        entity_id="lowresp_agent",
        location_id=near_loc,
        position=Coord(x=0.0, y=0.0),
    ))
    service.set_profile("lowresp_agent", DigitalProfile(notification_responsiveness=0.2))
    service.inject_feed_item(
        FeedItem(
            feed_item_id="f_e1_002",
            content="Another push",
            source="commercial_push",
            created_at=ledger.current_time,
        ),
        ["lowresp_agent"],
    )
    lowresp_ctx = ObserverContext(
        entity_id="lowresp_agent",
        position=Coord(x=0.0, y=0.0),
        location_id=near_loc,
        digital_state=AttentionState(
            attention_target="physical_world",
            pending_notifications=service.pending_for("lowresp_agent"),
            notification_responsiveness=0.2,
        ),
    )
    lowresp_view = pipeline.render(lowresp_ctx)
    lowresp_digital = lowresp_view.get_observations_by_sense(SenseType.DIGITAL)
    missed = [o for o in lowresp_digital if "missed" in o.tags]

    if len(missed) == 1:
        results.append(AuditResult(
            id="e1.push-respects-attention-state",
            status=AuditStatus.PASS,
            detail="low-responsiveness agent received push with missed tag",
        ))
    else:
        results.append(AuditResult(
            id="e1.push-respects-attention-state",
            status=AuditStatus.FAIL,
            detail=f"expected 1 missed-tagged observation, got {len(missed)}",
            mitigation_change="attention-channel",
        ))

    # ---- Check 3: feed-log-extractable ----
    log = service.export_feed_log()
    if len(log) >= 2 and any(r.delivered for r in log):
        results.append(AuditResult(
            id="e1.feed-log-extractable",
            status=AuditStatus.PASS,
            detail=f"exported {len(log)} records",
            extras={"records": len(log)},
        ))
    else:
        results.append(AuditResult(
            id="e1.feed-log-extractable",
            status=AuditStatus.FAIL,
            detail=f"expected >=2 records with at least one delivered; got {len(log)}",
            mitigation_change="attention-channel",
        ))

    return CategoryResult(category="e1-digital-lure", results=tuple(results))
