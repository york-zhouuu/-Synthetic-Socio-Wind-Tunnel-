#!/usr/bin/env python3
"""
measure_group_alignment — quantify how realistically agent activity aligns
with real-world group patterns.

Self-contained: runs its own small baseline sim (100 agents × 7 days × stub
mode) with custom hourly recorder, computes F1 (temporal) + F3 (routine)
metrics, dumps JSON.

Usage:
    python3 tools/measure_group_alignment.py
    python3 tools/measure_group_alignment.py --output data/realism/baseline.json
    python3 tools/measure_group_alignment.py --agents 50 --days 14

Output: data/realism/<tag>_metrics.json with stage1_passed verdict.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median

from synthetic_socio_wind_tunnel.agent import (
    AgentRuntime,
    LANE_COVE_PROFILE,
    build_scripted_plan,
    sample_population,
)
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.cartography.lanecove import create_atlas_from_osm
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.orchestrator import MultiDayRunner, Orchestrator


_DEFAULT_OUT = Path(__file__).resolve().parents[1] / "data" / "realism" / "baseline_metrics.json"


# ---------------------------------------------------------------------------
# Mini-sim with hourly + per-agent destination capture
# ---------------------------------------------------------------------------

def run_mini_sim(*, n_agents: int, n_days: int, seed: int):
    """
    Run a stub-mode baseline sim with custom recording.

    Returns:
        hourly_encs: list of length 24 — average encounter count per hour
                     across all sim days
        agent_visits: dict[agent_id → list[location_id]] of unique destinations
                      visited each day (for routine repeat analysis)
        per_day_total: list of length n_days — total encounters per day
        agent_profiles: list of AgentProfile (for routine_adherence analysis)
    """
    print(f"[mini-sim] {n_agents} agents × {n_days} days × stub mode...")
    atlas = create_atlas_from_osm()
    rng = random.Random(seed)

    # fix-population-uses-typed-locations: use typed pools instead of
    # outdoor-only single pool (agents must live in residential buildings).
    from synthetic_socio_wind_tunnel.agent import build_location_pools
    pools = build_location_pools(
        atlas, home_count=max(40, n_agents // 2),
        work_count=20, poi_count=30, rng=rng,
    )
    all_dests = list(pools.poi_pool)

    # Sample population with LifePattern
    template = LANE_COVE_PROFILE.model_copy(update={"size": n_agents})
    profiles = sample_population(
        template, seed=seed, pools=pools,
        atlas=atlas,
    )

    ledger = Ledger()
    start_date = date(2026, 5, 4)  # Monday
    ledger.current_time = datetime.combine(start_date, datetime.min.time())

    runtimes: list[AgentRuntime] = []
    for p in profiles:
        home = p.home_location or rng.choice(all_dests)
        ledger.set_entity(EntityState(
            entity_id=p.agent_id,
            position=Coord(x=0.0, y=0.0),
            location_id=home,
        ))
        rt = AgentRuntime(profile=p, current_location=home)
        rt.plan = build_scripted_plan(
            p, date=start_date.isoformat(), rng=rng, pools=pools,
        )
        runtimes.append(rt)

    orchestrator = Orchestrator(atlas, ledger, runtimes, tick_minutes=5, seed=seed)
    runner = MultiDayRunner(orchestrator=orchestrator)

    # Custom recorder: hourly bucket + per-agent destination per day
    hourly_encs: list[int] = [0] * 24
    agent_visits: dict[str, list[set[str]]] = defaultdict(list)
    per_day_total: list[int] = []

    def _custom_on_tick_end(tick_result):
        # Record encounters per simulated hour (TickResult.encounter_candidates
        # is the per-tick collision list).
        sim_t = tick_result.simulated_time
        if sim_t is not None:
            hourly_encs[sim_t.hour] += len(tick_result.encounter_candidates)

    orchestrator.register_on_tick_end(_custom_on_tick_end)

    def _on_day_start(current_date, day_index):
        rng_day = random.Random(seed + day_index)
        # Capture each agent's destinations TODAY (from yesterday's plan execution)
        if day_index > 0:
            for rt in runtimes:
                # Plan steps from previous day reflect where agent went
                plan = rt.plan
                if plan and plan.steps:
                    visited = {s.destination for s in plan.steps if s.destination}
                    agent_visits[rt.profile.agent_id].append(visited)

        # Reset for new day + new plan
        for rt in runtimes:
            home = rt.profile.home_location or all_dests[0]
            ledger.set_entity(EntityState(
                entity_id=rt.profile.agent_id,
                position=Coord(x=0.0, y=0.0),
                location_id=home,
            ))
            rt.current_location = home
            rt.cancel_movement()
            rt.plan = build_scripted_plan(
                rt.profile, date=current_date.isoformat(),
                rng=rng_day, pools=pools,
            )

    result = runner.run_multi_day(
        start_date=start_date, num_days=n_days,
        on_day_start=_on_day_start,
    )
    per_day_total = [s.encounter_count for s in result.per_day_summaries]

    # Final day capture
    for rt in runtimes:
        plan = rt.plan
        if plan and plan.steps:
            visited = {s.destination for s in plan.steps if s.destination}
            agent_visits[rt.profile.agent_id].append(visited)

    # Average hourly encounters across all days
    hourly_avg = [int(h / max(1, n_days)) for h in hourly_encs]

    return hourly_avg, dict(agent_visits), per_day_total, profiles


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------

def compute_f1_temporal(
    hourly_encs: list[int], per_day_total: list[int], start_date: date,
) -> dict:
    """
    F1: temporal realism — daytime peak vs lunch lull + weekday/weekend.

    Encounter peaks happen when agents are CO-LOCATED (at workplace, shops,
    leisure venues), not during 7-9am commute (people are dispersing).
    Real-world peaks are 9-11am (work arrival) + 17-19pm (return + leisure).
    Lunch (12-13) is an encounter dip.
    """
    daytime_peak = max(hourly_encs[9:20]) if len(hourly_encs) > 19 else 0
    lunch_dip = min(hourly_encs[12:14]) if len(hourly_encs) > 13 else 1
    morning_peak_ratio = daytime_peak / max(1, lunch_dip)

    # Weekday vs weekend
    weekday_totals = []
    weekend_totals = []
    for i, total in enumerate(per_day_total):
        day = start_date + timedelta(days=i)
        if day.weekday() < 5:
            weekday_totals.append(total)
        else:
            weekend_totals.append(total)

    if weekday_totals and weekend_totals:
        wd_avg = sum(weekday_totals) / len(weekday_totals)
        we_avg = sum(weekend_totals) / len(weekend_totals)
        diff_pct = abs(wd_avg - we_avg) / max(1, wd_avg)
    else:
        diff_pct = 0.0

    return {
        "morning_peak_ratio": round(morning_peak_ratio, 3),
        "weekday_weekend_diff_pct": round(diff_pct, 3),
        "popular_times_emd": None,  # require Popular Times JSON to compute
        "hourly_encounters": hourly_encs,
    }


def compute_f3_routine(
    agent_visits: dict[str, list[set[str]]], profiles: list,
) -> dict:
    """
    F3: per-agent routine stickiness vs routine_adherence.

    Metric: `repeat_pct` = top venue's daily-appearance rate.
    For each agent's day-by-day visit sets, find the venue that appears
    in the MOST days (not most total visits), divided by total days.
    - Sticky agent (LifePattern locked): top venue appears most days → high pct
    - Explorer (low adherence): top venue rarely repeats across days → low pct
    """
    profile_by_id = {p.agent_id: p for p in profiles}

    high_repeat_pcts = []
    low_repeat_pcts = []
    correlation_data = []

    for agent_id, day_visits in agent_visits.items():
        if not day_visits or len(day_visits) < 2:
            continue
        profile = profile_by_id.get(agent_id)
        if profile is None:
            continue
        home = profile.home_location
        # For each unique venue (EXCLUDING home), count days it was visited
        venue_day_count: dict[str, int] = defaultdict(int)
        for day_set in day_visits:
            for venue in day_set:
                if venue and venue != home:
                    venue_day_count[venue] += 1
        if not venue_day_count:
            continue
        max_days = max(venue_day_count.values())
        repeat_pct = max_days / len(day_visits)

        adherence = profile.personality.routine_adherence
        correlation_data.append((adherence, repeat_pct))

        if adherence > 0.7:
            high_repeat_pcts.append(repeat_pct)
        elif adherence < 0.4:
            low_repeat_pcts.append(repeat_pct)

    high_avg = median(high_repeat_pcts) if high_repeat_pcts else 0.0
    low_avg = median(low_repeat_pcts) if low_repeat_pcts else 0.0

    spearman_corr = _spearman(
        [a for a, _ in correlation_data],
        [r for _, r in correlation_data],
    ) if len(correlation_data) >= 10 else 0.0

    return {
        "high_adherence_repeat_pct": round(high_avg, 3),
        "low_adherence_repeat_pct": round(low_avg, 3),
        "spearman_adherence_repeat": round(spearman_corr, 3),
        "n_high_adherence": len(high_repeat_pcts),
        "n_low_adherence": len(low_repeat_pcts),
    }


def _spearman(xs: list[float], ys: list[float]) -> float:
    """Manual Spearman rank correlation (avoid scipy dep on hot path)."""
    if len(xs) < 2:
        return 0.0
    rank_x = _rank(xs)
    rank_y = _rank(ys)
    n = len(xs)
    mean_x = sum(rank_x) / n
    mean_y = sum(rank_y) / n
    num = sum((rx - mean_x) * (ry - mean_y) for rx, ry in zip(rank_x, rank_y))
    den_x = sum((rx - mean_x) ** 2 for rx in rank_x) ** 0.5
    den_y = sum((ry - mean_y) ** 2 for ry in rank_y) ** 0.5
    if den_x == 0 or den_y == 0:
        return 0.0
    return num / (den_x * den_y)


def _rank(xs: list[float]) -> list[float]:
    indexed = sorted(enumerate(xs), key=lambda kv: kv[1])
    ranks = [0.0] * len(xs)
    for r, (i, _) in enumerate(indexed, start=1):
        ranks[i] = r
    return ranks


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--agents", type=int, default=100)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--output", type=Path, default=_DEFAULT_OUT)
    args = ap.parse_args()

    start_date = date(2026, 5, 4)  # Monday — gives 5 weekday + 2 weekend if days=7
    hourly_encs, agent_visits, per_day_total, profiles = run_mini_sim(
        n_agents=args.agents, n_days=args.days, seed=args.seed,
    )

    f1 = compute_f1_temporal(hourly_encs, per_day_total, start_date)
    f3 = compute_f3_routine(agent_visits, profiles)

    # Stage 1 acceptance
    stage1_passed = (
        f1["morning_peak_ratio"] > 1.5
        and f1["weekday_weekend_diff_pct"] > 0.15
        and f3["spearman_adherence_repeat"] > 0.5
    )

    payload = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "n_agents": args.agents,
        "n_days": args.days,
        "seed": args.seed,
        "f1_temporal": f1,
        "f3_routine": f3,
        "stage1_passed": stage1_passed,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    print()
    print("=== Group Alignment Metrics ===")
    print(f"  F1 morning_peak_ratio       = {f1['morning_peak_ratio']:.2f}  (need > 1.5)")
    print(f"  F1 weekday/weekend diff     = {f1['weekday_weekend_diff_pct']:.1%} (need > 15%)")
    print(f"  F3 high adherence repeat    = {f3['high_adherence_repeat_pct']:.1%}")
    print(f"  F3 low adherence repeat     = {f3['low_adherence_repeat_pct']:.1%}")
    print(f"  F3 spearman corr            = {f3['spearman_adherence_repeat']:.2f}  (need > 0.5)")
    print()
    emoji = "✓" if stage1_passed else "✗"
    print(f"  {emoji} stage1_passed = {stage1_passed}")
    print()
    print(f"[report] {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
