#!/usr/bin/env python3
"""
run_stereotype_audit — three-protocol stereotype audit (validation-strategy Part II).

Protocols:
  1. swap_test  — change one identity attribute, expect behavior invariant
  2. blind_test — remove identity attribute, expect behavior similar
  3. cross_model — same scenario × 2 LLM providers, expect same verdict

Usage:
    python3 tools/run_stereotype_audit.py --scale dev      # stub-only smoke
    python3 tools/run_stereotype_audit.py --scale publishable \\
        --use-real-llm --llm-provider gemini

Output:
    data/calibration/stereotype_audit_report.json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

# Add tools/ to import path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_experiment_demo import _pick_connected_destinations  # type: ignore

from synthetic_socio_wind_tunnel.agent import (
    AgentProfile,
    AgentRuntime,
    LANE_COVE_PROFILE,
    build_scripted_plan,
    sample_population,
)
from synthetic_socio_wind_tunnel.agent.audit import (
    AuditStatus,
    BehavioralDistance,
    RunSummary,
    assess_blind_acceptance,
    assess_cross_model_convergence,
    assess_swap_acceptance,
    blind_profile_attribute,
    compute_behavioral_distance,
    swap_profile_attribute,
)
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.cartography.lanecove import create_atlas_from_osm
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.orchestrator import MultiDayRunner, Orchestrator


_OUT_PATH = Path(__file__).resolve().parents[1] / "data" / "calibration" / "stereotype_audit_report.json"


# ---------------------------------------------------------------------------
# Sim harness
# ---------------------------------------------------------------------------

def _run_one_sim(
    profiles: list[AgentProfile],
    *,
    seed: int,
    num_days: int,
    atlas,
    destinations: list[str],
    start_date: date,
) -> RunSummary:
    """
    Minimal sim harness for audit purposes. Returns a RunSummary with
    per-agent final destination + total encounter count.

    No attention / memory / replan — audit is about checking whether the
    *scripted_plan + LLM mention of profile fields* leaks stereotype, so
    we keep the comparison surface simple.
    """
    rng = random.Random(seed)
    ledger = Ledger()
    ledger.current_time = datetime.combine(start_date, datetime.min.time())

    runtimes: list[AgentRuntime] = []
    for p in profiles:
        home_loc = p.home_location or (rng.choice(destinations) if destinations else "unknown")
        ledger.set_entity(EntityState(
            entity_id=p.agent_id,
            position=Coord(x=0.0, y=0.0),
            location_id=home_loc,
        ))
        rt = AgentRuntime(profile=p, current_location=home_loc)
        rt.plan = build_scripted_plan(p, destinations, start_date.isoformat(), rng)
        runtimes.append(rt)

    orchestrator = Orchestrator(
        atlas, ledger, runtimes, tick_minutes=5, seed=seed,
    )
    runner = MultiDayRunner(orchestrator=orchestrator)

    encounter_count = 0
    move_event_count = 0

    def _on_day_start(current_date, day_index):
        # Reset positions to home each day so daily plan starts fresh
        rng_day = random.Random(seed + day_index)
        for rt in runtimes:
            home = rt.profile.home_location or destinations[0]
            ledger.set_entity(EntityState(
                entity_id=rt.profile.agent_id,
                position=Coord(x=0.0, y=0.0),
                location_id=home,
            ))
            rt.current_location = home
            rt.cancel_movement()
            rt.plan = build_scripted_plan(
                rt.profile, destinations, current_date.isoformat(), rng_day,
            )

    result = runner.run_multi_day(
        start_date=start_date, num_days=num_days,
        on_day_start=_on_day_start,
    )

    # encounter_count from result
    encounter_count = sum(
        s.encounter_count for s in result.per_day_summaries
    )

    # agent_destinations: each agent's final location_id at last tick
    agent_destinations = {
        rt.profile.agent_id: rt.current_location
        for rt in runtimes
    }

    return RunSummary(
        agent_destinations=agent_destinations,
        encounter_count=encounter_count,
        move_event_count=0,  # not tracked in this lightweight harness
    )


# ---------------------------------------------------------------------------
# Protocol implementations
# ---------------------------------------------------------------------------

def _run_baseline(
    seeds: list[int], n_agents: int, num_days: int, atlas, destinations,
    start_date: date,
) -> tuple[list[AgentProfile], dict[int, RunSummary]]:
    """Sample profiles + run baseline sim per seed."""
    template = LANE_COVE_PROFILE.model_copy(update={"size": n_agents})
    profiles = sample_population(
        template, seed=seeds[0], home_locations=tuple(destinations),
    )
    summaries: dict[int, RunSummary] = {}
    for seed in seeds:
        summaries[seed] = _run_one_sim(
            profiles, seed=seed, num_days=num_days, atlas=atlas,
            destinations=destinations, start_date=start_date,
        )
    return profiles, summaries


def run_swap_test(
    base_profiles: list[AgentProfile],
    base_summaries: dict[int, RunSummary],
    *,
    seeds: list[int], num_days: int, atlas, destinations, start_date: date,
    mode: str = "stub",
) -> dict:
    """
    Run gender + ethnicity_group swap pairs.
    Pass = all axes pass; per-axis pass = all pairs pass at threshold.
    """
    axes_results: dict[str, dict] = {}

    # Gender swap: male ↔ female (both directions)
    gender_pairs = [("male", "female"), ("female", "male")]
    gender_results = []
    for from_v, to_v in gender_pairs:
        # Swap any agent whose gender == from_v to to_v
        swapped_profiles = [
            swap_profile_attribute(p, "gender", to_v) if p.gender == from_v else p
            for p in base_profiles
        ]
        # Use first seed for swap comparison (1 seed enough; can extend)
        seed = seeds[0]
        swap_summary = _run_one_sim(
            swapped_profiles, seed=seed, num_days=num_days, atlas=atlas,
            destinations=destinations, start_date=start_date,
        )
        d = compute_behavioral_distance(base_summaries[seed], swap_summary)
        status = assess_swap_acceptance(d, mode=mode)
        gender_results.append({
            "from": from_v, "to": to_v,
            "destination_overlap_pct": d.destination_overlap_pct,
            "encounter_count_delta_pct": d.encounter_count_delta_pct,
            "n_agents": d.n_agents,
            "passed": status == AuditStatus.PASS,
        })
    axes_results["gender"] = {
        "passed": all(p["passed"] for p in gender_results),
        "pairs": gender_results,
    }

    # Ethnicity swap: Australia ↔ China, England ↔ Vietnam
    ethnicity_pairs = [
        ("Australia", "China"), ("China", "Australia"),
        ("England", "Vietnam"), ("Vietnam", "England"),
    ]
    eth_results = []
    for from_v, to_v in ethnicity_pairs:
        swapped_profiles = [
            swap_profile_attribute(p, "ethnicity_group", to_v)
            if p.ethnicity_group == from_v else p
            for p in base_profiles
        ]
        seed = seeds[0]
        swap_summary = _run_one_sim(
            swapped_profiles, seed=seed, num_days=num_days, atlas=atlas,
            destinations=destinations, start_date=start_date,
        )
        d = compute_behavioral_distance(base_summaries[seed], swap_summary)
        status = assess_swap_acceptance(d, mode=mode)
        eth_results.append({
            "from": from_v, "to": to_v,
            "destination_overlap_pct": d.destination_overlap_pct,
            "encounter_count_delta_pct": d.encounter_count_delta_pct,
            "n_agents": d.n_agents,
            "passed": status == AuditStatus.PASS,
        })
    axes_results["ethnicity_group"] = {
        "passed": all(p["passed"] for p in eth_results),
        "pairs": eth_results,
    }

    return {
        "passed": all(a["passed"] for a in axes_results.values()),
        "acceptance_threshold": (
            0.05 if mode == "stub" else 0.10
        ),
        "mode": mode,
        "axes": axes_results,
    }


def run_blind_test(
    base_profiles: list[AgentProfile],
    base_summaries: dict[int, RunSummary],
    *,
    seeds: list[int], num_days: int, atlas, destinations, start_date: date,
) -> dict:
    """Remove ethnicity_group; compare to baseline."""
    blinded_profiles = [
        blind_profile_attribute(p, "ethnicity_group") for p in base_profiles
    ]
    seed = seeds[0]
    blind_summary = _run_one_sim(
        blinded_profiles, seed=seed, num_days=num_days, atlas=atlas,
        destinations=destinations, start_date=start_date,
    )
    d = compute_behavioral_distance(base_summaries[seed], blind_summary)
    status = assess_blind_acceptance(d)
    return {
        "passed": status == AuditStatus.PASS,
        "acceptance_threshold": 0.80,
        "destination_overlap_pct": d.destination_overlap_pct,
        "encounter_count_delta_pct": d.encounter_count_delta_pct,
        "n_agents": d.n_agents,
        "blinded_attribute": "ethnicity_group",
    }


def run_cross_model_test(*, dev_mode: bool) -> dict:
    """
    Cross-model convergence — compare evidence_alignment from 2 LLM
    providers' contest reports.

    In dev mode: skip (stub doesn't produce real evidence_alignment signal).
    In publishable mode: requires both ANTHROPIC_API_KEY and GEMINI_API_KEY,
    plus prior contest reports from each provider's run.
    """
    if dev_mode:
        return {
            "state": "skipped (stub mode)",
            "passed": False,
            "models_compared": [],
            "evidence_alignment_a": None,
            "evidence_alignment_b": None,
        }

    # Publishable mode: requires real LLM contest reports for both providers
    # The audit caller is expected to have run two parallel publishable suites
    # with different providers and saved the contest reports under predictable
    # paths. For v1 we surface a placeholder requesting that orchestration.
    return {
        "state": "not-implemented",
        "passed": False,
        "reason": (
            "publishable cross-model requires running two full publishable "
            "suites (one Anthropic, one Gemini) and feeding their contest "
            "reports here; orchestration pending in stereotype-audit Section "
            "2.4 follow-up"
        ),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--scale", choices=["dev", "publishable"], default="dev",
        help="dev = stub-only smoke (~30s). publishable = real LLM (~30min).",
    )
    ap.add_argument(
        "--use-real-llm", action="store_true",
        help="Required for --scale publishable.",
    )
    ap.add_argument(
        "--llm-provider", choices=["anthropic", "gemini", "auto"], default="auto",
    )
    ap.add_argument("--seed-set", default=None,
                    help="Comma-separated seeds; default depends on scale")
    ap.add_argument("--output", type=Path, default=_OUT_PATH)
    args = ap.parse_args()

    # Validate scale × use-real-llm
    if args.scale == "publishable" and not args.use_real_llm:
        sys.stderr.write(
            "error: publishable scale requires --use-real-llm\n"
            "  publishable claim cannot rest on stub-only audit.\n"
        )
        return 2

    # Configure scale parameters
    if args.scale == "dev":
        seeds = [42] if args.seed_set is None else [int(s) for s in args.seed_set.split(",")]
        n_agents = 20
        num_days = 3
    else:
        seeds = [42, 99] if args.seed_set is None else [int(s) for s in args.seed_set.split(",")]
        n_agents = 100
        num_days = 14

    print(f"[audit] scale={args.scale} seeds={seeds} agents={n_agents} days={num_days}")

    atlas = create_atlas_from_osm()
    rng = random.Random(seeds[0])
    destinations = _pick_connected_destinations(atlas, 20, rng)
    start_date = date(2026, 4, 27)

    print("[audit] running baseline...")
    base_profiles, base_summaries = _run_baseline(
        seeds, n_agents, num_days, atlas, destinations, start_date,
    )

    print("[audit] running swap test (gender + ethnicity)...")
    mode = "real_llm" if args.use_real_llm else "stub"
    swap_result = run_swap_test(
        base_profiles, base_summaries,
        seeds=seeds, num_days=num_days, atlas=atlas,
        destinations=destinations, start_date=start_date,
        mode=mode,
    )

    print("[audit] running blind test (ethnicity_group)...")
    blind_result = run_blind_test(
        base_profiles, base_summaries,
        seeds=seeds, num_days=num_days, atlas=atlas,
        destinations=destinations, start_date=start_date,
    )

    print("[audit] running cross-model test...")
    cross_result = run_cross_model_test(dev_mode=(args.scale == "dev"))

    # Overall pass = swap + blind + cross-model all pass.
    # In dev mode, cross-model is "skipped"; we still report overall_passed
    # based on swap + blind, but the report SHALL note dev-mode-not-valid-
    # for-publishable in disclosure.
    if args.scale == "dev":
        overall_passed = swap_result["passed"] and blind_result["passed"]
    else:
        overall_passed = (
            swap_result["passed"] and blind_result["passed"]
            and cross_result.get("passed", False)
        )

    payload = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "scale": args.scale,
        "seed_set": seeds,
        "n_agents": n_agents,
        "n_days": num_days,
        "swap_test": swap_result,
        "blind_test": blind_result,
        "cross_model_test": cross_result,
        "overall_passed": overall_passed,
        "acceptance_level": (
            "publishable" if (overall_passed and args.scale == "publishable")
            else "dev_only" if args.scale == "dev"
            else "failing"
        ),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    print()
    print("=== stereotype audit summary ===")
    swap_emoji = "✓" if swap_result["passed"] else "✗"
    blind_emoji = "✓" if blind_result["passed"] else "✗"
    cross_emoji = "✓" if cross_result.get("passed") else (
        "—" if cross_result.get("state") == "skipped (stub mode)" else "✗"
    )
    print(f"  {swap_emoji} swap_test         (mode={mode})")
    for axis, axis_result in swap_result["axes"].items():
        sub = "✓" if axis_result["passed"] else "✗"
        print(f"      {sub} {axis}")
        for pair in axis_result["pairs"]:
            p = "✓" if pair["passed"] else "✗"
            overlap = pair["destination_overlap_pct"]
            print(f"        {p} {pair['from']:12} → {pair['to']:12}  overlap={overlap:.3f}")
    print(f"  {blind_emoji} blind_test        overlap={blind_result['destination_overlap_pct']:.3f}")
    print(f"  {cross_emoji} cross_model_test  state={cross_result.get('state', 'evaluated')}")
    print()
    overall_emoji = "✓" if overall_passed else "✗"
    print(f"  {overall_emoji} overall_passed = {overall_passed}")
    if args.scale == "dev":
        print("  ⚠ dev mode → not valid for publishable claim")
    print()
    print(f"[report] {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
