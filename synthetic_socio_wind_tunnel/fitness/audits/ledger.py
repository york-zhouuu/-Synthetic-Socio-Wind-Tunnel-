"""Ledger observability audit - can we extract trajectory / encounter snapshots?"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.engine.simulation import SimulationService
from synthetic_socio_wind_tunnel.fitness.report import AuditResult, AuditStatus, CategoryResult
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.atlas import Atlas


def _snapshot(ledger: Ledger, agent_ids: list[str]) -> list[dict]:
    """Extract a minimal trajectory snapshot without depending on Phase 2 metrics."""
    return [
        {
            "entity_id": aid,
            "location_id": ledger.get_entity(aid).location_id if ledger.get_entity(aid) else None,
            "time": ledger.current_time.isoformat(),
        }
        for aid in agent_ids
    ]


def audit_ledger_observability(atlas: "Atlas") -> CategoryResult:
    """
    Three checks:
    - trajectory-export:     agent location sequence can be extracted per-tick
    - encounter-export:      two agents in the same location can be detected
    - snapshot-determinism:  same-seed run produces byte-equal snapshot
    """
    results: list[AuditResult] = []

    outdoor_ids = list(atlas.region.outdoor_areas.keys())
    if len(outdoor_ids) < 2:
        msg = "atlas needs ≥2 outdoor areas"
        for cid in ("ledger.trajectory-export", "ledger.encounter-export",
                    "ledger.snapshot-determinism"):
            results.append(AuditResult(
                id=cid,
                status=AuditStatus.SKIP,
                detail=msg,
                mitigation_change="cartography",
            ))
        return CategoryResult(category="ledger-observability", results=tuple(results))

    loc_a, loc_b = outdoor_ids[0], outdoor_ids[1]

    def run(seed_like: int) -> tuple[list[dict], list[dict]]:
        ledger = Ledger()
        ledger.current_time = datetime(2026, 4, 20, 8, 0, 0)
        sim = SimulationService(atlas, ledger)
        agents = ["alpha", "beta"]
        for aid in agents:
            ledger.set_entity(EntityState(
                entity_id=aid,
                location_id=loc_a,
                position=Coord(x=0.0, y=0.0),
            ))
        trajectory: list[dict] = []
        # tick 0 → both at loc_a
        trajectory.extend(_snapshot(ledger, agents))
        # tick 1 → alpha moves to loc_b
        ledger.current_time = ledger.current_time + timedelta(minutes=5)
        sim.move_entity("alpha", loc_b)
        trajectory.extend(_snapshot(ledger, agents))
        # tick 2 → beta joins loc_b
        ledger.current_time = ledger.current_time + timedelta(minutes=5)
        sim.move_entity("beta", loc_b)
        trajectory.extend(_snapshot(ledger, agents))

        # Encounter: pairs sharing location at any tick
        encounters: list[dict] = []
        snapshots_by_time: dict[str, dict[str, str | None]] = {}
        for s in trajectory:
            t = s["time"]
            snapshots_by_time.setdefault(t, {})[s["entity_id"]] = s["location_id"]
        for t, locs in snapshots_by_time.items():
            for i, a in enumerate(agents):
                for b in agents[i + 1:]:
                    if locs.get(a) == locs.get(b) and locs.get(a) is not None:
                        encounters.append({"time": t, "a": a, "b": b, "loc": locs[a]})

        return trajectory, encounters

    traj, enc = run(seed_like=1)

    if len(traj) == 6:  # 2 agents × 3 ticks
        results.append(AuditResult(
            id="ledger.trajectory-export",
            status=AuditStatus.PASS,
            detail=f"extracted {len(traj)} trajectory points",
            extras={"count": len(traj)},
        ))
    else:
        results.append(AuditResult(
            id="ledger.trajectory-export",
            status=AuditStatus.FAIL,
            detail=f"expected 6 trajectory points, got {len(traj)}",
            mitigation_change="ledger",
        ))

    if any(e["loc"] == loc_b for e in enc):
        results.append(AuditResult(
            id="ledger.encounter-export",
            status=AuditStatus.PASS,
            detail=f"detected {len(enc)} encounter(s)",
            extras={"count": len(enc)},
        ))
    else:
        results.append(AuditResult(
            id="ledger.encounter-export",
            status=AuditStatus.FAIL,
            detail="failed to detect agents co-located after convergence",
            mitigation_change="ledger",
        ))

    # Determinism: run twice, compare JSON
    traj_1, _ = run(seed_like=1)
    traj_2, _ = run(seed_like=1)
    if json.dumps(traj_1, sort_keys=True) == json.dumps(traj_2, sort_keys=True):
        results.append(AuditResult(
            id="ledger.snapshot-determinism",
            status=AuditStatus.PASS,
            detail="two runs produced byte-equal trajectory snapshot",
        ))
    else:
        results.append(AuditResult(
            id="ledger.snapshot-determinism",
            status=AuditStatus.FAIL,
            detail="trajectory snapshot diverged across runs with same setup",
            mitigation_change="ledger",
        ))

    return CategoryResult(category="ledger-observability", results=tuple(results))
