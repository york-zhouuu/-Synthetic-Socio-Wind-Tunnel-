"""E2 Spatial Unlock 可行性审计。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from synthetic_socio_wind_tunnel.engine.navigation import NavigationService, PathStrategy
from synthetic_socio_wind_tunnel.fitness.report import AuditResult, AuditStatus, CategoryResult
from synthetic_socio_wind_tunnel.ledger import Ledger

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.atlas import Atlas


def _find_locked_door_pair(atlas: "Atlas", ledger: Ledger) -> tuple[str, str, str] | None:
    """
    Find a (from_id, to_id, door_id) triple where an Atlas door connects two
    locations and we can plausibly lock/unlock it.

    Returns None if the atlas has no doors.
    """
    doors = list(atlas.region.doors.values())
    if not doors:
        return None

    for door in doors:
        # DoorDef has from_loc and to_loc
        from_id = getattr(door, "from_loc", None) or getattr(door, "from_id", None)
        to_id = getattr(door, "to_loc", None) or getattr(door, "to_id", None)
        if from_id and to_id and from_id in atlas.region.outdoor_areas | atlas.region.buildings:
            if to_id in atlas.region.outdoor_areas | atlas.region.buildings:
                return from_id, to_id, door.door_id
    # Fallback: first door regardless
    door = doors[0]
    from_id = getattr(door, "from_loc", "") or getattr(door, "from_id", "")
    to_id = getattr(door, "to_loc", "") or getattr(door, "to_id", "")
    return from_id, to_id, door.door_id


def audit_e2_spatial_unlock(atlas: "Atlas") -> CategoryResult:
    """
    Three checks:
    - door-unlock-midrun:    unlock_door → next find_route passes through the door
    - path-diff-extractable: route distance after unlock SHOULD differ from before
    - desire-path-detectable: ledger records the unlock event in its event log
    """
    results: list[AuditResult] = []

    ledger = Ledger()
    ledger.current_time = datetime(2026, 4, 20, 9, 0, 0)
    navigation = NavigationService(atlas, ledger)

    # Check 1 setup
    triple = _find_locked_door_pair(atlas, ledger)
    if triple is None:
        msg = "atlas has no doors (expected for pure street atlases like Lane Cove OSM)"
        for cid in ("e2.door-unlock-midrun", "e2.path-diff-extractable",
                    "e2.desire-path-detectable"):
            results.append(AuditResult(
                id=cid,
                status=AuditStatus.SKIP,
                detail=msg,
                mitigation_change="cartography",
            ))
        return CategoryResult(category="e2-spatial-unlock", results=tuple(results))

    from_id, to_id, door_id = triple

    # Lock the door
    ledger.lock_door(door_id, by="audit")

    route_locked = navigation.find_route(from_id, to_id, strategy=PathStrategy.SHORTEST)
    ledger.unlock_door(door_id, by="audit")
    route_unlocked = navigation.find_route(from_id, to_id, strategy=PathStrategy.SHORTEST)

    # Check 1: door-unlock-midrun
    unlocked_doors = set(route_unlocked.doors_to_pass) if route_unlocked.success else set()
    if route_unlocked.success and door_id in unlocked_doors:
        results.append(AuditResult(
            id="e2.door-unlock-midrun",
            status=AuditStatus.PASS,
            detail=f"route after unlock passes through {door_id}",
            extras={"door_id": door_id},
        ))
    else:
        results.append(AuditResult(
            id="e2.door-unlock-midrun",
            status=AuditStatus.FAIL,
            detail=f"route did not pass through unlocked {door_id}; "
                   f"success={route_unlocked.success}",
            mitigation_change="navigation",
        ))

    # Check 2: path-diff-extractable
    locked_dist = route_locked.total_distance if route_locked.success else float("inf")
    unlocked_dist = route_unlocked.total_distance if route_unlocked.success else float("inf")
    if route_unlocked.success and unlocked_dist <= locked_dist:
        results.append(AuditResult(
            id="e2.path-diff-extractable",
            status=AuditStatus.PASS,
            detail=f"locked_dist={locked_dist:.2f}m, unlocked_dist={unlocked_dist:.2f}m",
            extras={
                "locked_distance": locked_dist if locked_dist != float("inf") else None,
                "unlocked_distance": unlocked_dist,
            },
        ))
    else:
        results.append(AuditResult(
            id="e2.path-diff-extractable",
            status=AuditStatus.FAIL,
            detail=f"unexpected: unlocked distance ({unlocked_dist}) > locked ({locked_dist})",
            mitigation_change="navigation",
        ))

    # Check 3: desire-path-detectable
    # Ledger._log_event is the canonical event log. After unlock_door,
    # "door_unlocked" SHALL appear in recent events.
    recent = ledger.get_recent_events(limit=20)
    unlocked_events = [ev for ev in recent if ev.get("type") == "door_unlocked"]
    if unlocked_events:
        results.append(AuditResult(
            id="e2.desire-path-detectable",
            status=AuditStatus.PASS,
            detail=f"ledger recorded {len(unlocked_events)} door_unlocked events",
        ))
    else:
        results.append(AuditResult(
            id="e2.desire-path-detectable",
            status=AuditStatus.FAIL,
            detail="no door_unlocked event in recent ledger events",
            mitigation_change="ledger",
        ))

    return CategoryResult(category="e2-spatial-unlock", results=tuple(results))
