"""Scale baseline - wall-time measurements for quick (100×72) / full (1000×288)."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal

from synthetic_socio_wind_tunnel.agent import LANE_COVE_PROFILE, sample_population
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.engine.navigation import NavigationService, PathStrategy
from synthetic_socio_wind_tunnel.engine.simulation import SimulationService
from synthetic_socio_wind_tunnel.fitness._common import percentile
from synthetic_socio_wind_tunnel.fitness.report import (
    AuditResult,
    AuditStatus,
    CategoryResult,
    ScaleBaseline,
)
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.perception import PerceptionPipeline
from synthetic_socio_wind_tunnel.perception.models import ObserverContext

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.atlas import Atlas


def _neighbors_of(atlas: "Atlas", loc_id: str) -> list[str]:
    """Return adjacent location ids via Connection graph."""
    neighbors: list[str] = []
    for conn in atlas.region.connections:
        if conn.from_id == loc_id:
            neighbors.append(conn.to_id)
        elif conn.bidirectional and conn.to_id == loc_id:
            neighbors.append(conn.from_id)
    return neighbors


def audit_scale_baseline(
    atlas: "Atlas",
    *,
    scale: Literal["quick", "full"] = "quick",
) -> tuple[CategoryResult, ScaleBaseline]:
    """
    Run N agents × M ticks of:
      advance time → every agent moves to a random neighbour via simulation →
      every agent renders perception.

    This covers the three hot paths a real tick exercises: write (move_entity,
    updates Ledger + events), read (pipeline.render with filter chain), and
    graph lookup (adjacency). Excluded: LLM calls, planner replan, memory —
    those belong to Phase 2 capabilities with their own baselines.

    quick: N=100, M=72
    full:  N=1000, M=288
    """
    N, M = (100, 72) if scale == "quick" else (1000, 288)

    locs = list(atlas.region.outdoor_areas.keys()) or list(atlas.region.buildings.keys())
    if not locs:
        cat = CategoryResult(
            category="scale-baseline",
            results=(AuditResult(
                id="scale.wall-time",
                status=AuditStatus.SKIP,
                detail="atlas has no locations",
                mitigation_change="cartography",
            ),),
        )
        return cat, ScaleBaseline(
            agents=N, ticks=M,
            wall_seconds_total=0.0, wall_seconds_p50=0.0, wall_seconds_p99=0.0,
            notes="skipped — atlas empty",
        )

    # Pre-compute adjacency per location — makes the tick loop cheap.
    adjacency: dict[str, list[str]] = {loc: _neighbors_of(atlas, loc) for loc in locs}
    # Locations without neighbors are fine; agent stays put (matches real behaviour
    # when an agent is inside a building with no external connections).

    ledger = Ledger()
    ledger.current_time = datetime(2026, 4, 20, 7, 0, 0)
    agents_sample = sample_population(LANE_COVE_PROFILE, seed=42, num_protagonists=0)[:N]
    agent_ids: list[str] = []
    for i, prof in enumerate(agents_sample):
        aid = f"scale_agent_{i:04d}"
        agent_ids.append(aid)
        ledger.set_entity(EntityState(
            entity_id=aid,
            location_id=locs[i % len(locs)],
            position=Coord(x=float(i % 10), y=float(i // 10 % 10)),
        ))

    sim = SimulationService(atlas, ledger)
    pipeline = PerceptionPipeline(atlas, ledger)

    # Deterministic per-agent movement pattern: cycle through neighbors based on
    # a per-agent seed-like offset. No RNG so the baseline is reproducible.
    def _next_location(aid: str, current: str, tick: int) -> str:
        neighbors = adjacency.get(current, [])
        if not neighbors:
            return current
        offset = (hash(aid) + tick) % len(neighbors)
        return neighbors[offset]

    per_tick_seconds: list[float] = []
    successful_moves = 0
    skipped_moves = 0  # agents in dead-end rooms stay put
    total_start = time.perf_counter()
    for t in range(M):
        ledger.current_time = ledger.current_time + timedelta(minutes=5)
        tick_start = time.perf_counter()

        # Write phase: every agent tries to move to a neighbor.
        for aid in agent_ids:
            entity = ledger.get_entity(aid)
            if entity is None:
                continue
            next_loc = _next_location(aid, entity.location_id, t)
            if next_loc == entity.location_id:
                skipped_moves += 1
                continue
            r = sim.move_entity(aid, next_loc)
            if r.success:
                successful_moves += 1

        # Read phase: every agent renders perception at its (possibly new) location.
        for aid in agent_ids:
            entity = ledger.get_entity(aid)
            if entity is None:
                continue
            ctx = ObserverContext(
                entity_id=aid,
                position=entity.position,
                location_id=entity.location_id,
            )
            pipeline.render(ctx)

        per_tick_seconds.append(time.perf_counter() - tick_start)
    total_elapsed = time.perf_counter() - total_start

    p50 = percentile(per_tick_seconds, 0.50)
    p99 = percentile(per_tick_seconds, 0.99)

    baseline = ScaleBaseline(
        agents=N,
        ticks=M,
        wall_seconds_total=total_elapsed,
        wall_seconds_p50=p50,
        wall_seconds_p99=p99,
        notes=(
            f"scale={scale}; each tick: N move_entity writes + N pipeline.render reads; "
            f"successful moves={successful_moves}, skipped(dead-end)={skipped_moves}. "
            "Excludes LLM/planner/memory — those add to real tick cost."
        ),
    )

    # Gate: quick should finish in < 120s on any reasonable machine
    if scale == "quick" and total_elapsed > 120:
        status = AuditStatus.FAIL
        detail = f"quick scale took {total_elapsed:.1f}s (> 120s budget)"
        mitigation = "orchestrator"
    else:
        status = AuditStatus.PASS
        detail = (
            f"{N} agents × {M} ticks: total={total_elapsed:.2f}s, "
            f"p50={p50 * 1000:.1f}ms, p99={p99 * 1000:.1f}ms "
            f"(moves={successful_moves}, skipped={skipped_moves})"
        )
        mitigation = None

    cat = CategoryResult(
        category="scale-baseline",
        results=(AuditResult(
            id="scale.wall-time",
            status=status,
            detail=detail,
            mitigation_change=mitigation,
            extras={
                "total_seconds": total_elapsed,
                "p50_seconds": p50,
                "p99_seconds": p99,
                "agents": N,
                "ticks": M,
                "moves_succeeded": successful_moves,
                "moves_skipped": skipped_moves,
            },
        ),),
    )
    return cat, baseline
