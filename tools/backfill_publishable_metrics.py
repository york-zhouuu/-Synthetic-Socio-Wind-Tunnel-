"""Backfill 3 missing publishable metrics into seed_N.json (post-process only).

Fills in:
1. run_metrics.dialogue_count — from memstat dialogue_service.evicted_total (last sample)
2. run_metrics.dwell_by_type — bucket per_day.location_dwell_ticks via atlas
3. run_metrics.trajectory_deviation_m — per-agent per-day cumulative Euclidean
   distance vs same-seed baseline run (using atlas centroid coords)

Reads atlas from data/lanecove_atlas.json. No simulation re-run.
Designed to be idempotent: skip cells where artifact missing, overwrite existing.
"""
from __future__ import annotations
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
ATLAS = REPO / "data/lanecove_atlas.json"

SEEDS = {
    43: REPO / "data/experiments/20260521_185100_publishable_v6_day4to13_fork_seed43",
    44: REPO / "data/experiments/20260522_165045_publishable_v7_day4to13_fork_seed44",
    45: REPO / "data/experiments/20260522_212423_publishable_v7_day4to13_fork_seed45",
}
VARIANTS = ["baseline", "hyperlocal_push", "global_distraction", "phone_friction"]

DWELL_BUCKETS = {
    "residential":   {"residential"},
    "commercial":    {"shop","restaurant","cafe","bar","hotel","office","commercial",
                      "hospital","school","entertainment","community","worship",
                      "utility","industrial"},
    "public_outdoor": {"outdoor_park","outdoor_playground","outdoor_garden"},
    "street":        {"outdoor_street"},
}


def build_location_index() -> dict:
    """Return {location_id: {"type": str, "coord": (x,y)}}."""
    with open(ATLAS) as f:
        atlas = json.load(f)
    idx = {}
    for b in atlas["buildings"].values():
        coord = b.get("entrance_coord")
        if coord:
            idx[b["id"]] = {"type": b.get("building_type") or "unknown",
                            "coord": (coord["x"], coord["y"])}
    outdoor = atlas.get("outdoor_areas", {})
    if isinstance(outdoor, dict):
        outdoor = outdoor.values()
    for o in outdoor:
        # center = centroid of polygon vertices
        verts = o.get("polygon", {}).get("vertices", [])
        if verts:
            cx = sum(v["x"] for v in verts) / len(verts)
            cy = sum(v["y"] for v in verts) / len(verts)
            idx[o["id"]] = {"type": "outdoor_" + (o.get("area_type") or "unknown"),
                            "coord": (cx, cy)}
    return idx


def bucket_for(loc_type: str) -> str | None:
    for bucket, types in DWELL_BUCKETS.items():
        if loc_type in types:
            return bucket
    return None


def backfill_dialogue_count(cell_dir: Path, seed: int, run_metrics: dict) -> dict:
    """Update run_metrics.dialogue_count from memstat last sample."""
    memstat = cell_dir / f"seed_{seed}.memstat.jsonl"
    if not memstat.exists():
        return {"status": "no_memstat"}
    last_evicted = 0
    peak_evicted = 0
    last_live = 0
    samples = 0
    with open(memstat) as f:
        for ln in f:
            try:
                e = json.loads(ln)
                ds = e.get("dialogue_service", {})
                ev = ds.get("evicted_total", 0)
                live = ds.get("live", 0)
                if ev > peak_evicted: peak_evicted = ev
                last_evicted = ev
                last_live = live
                samples += 1
            except Exception:
                pass
    # Final completed dialogues ≈ last sample's evicted_total
    # (plus any still-live at exit, but those didn't complete)
    run_metrics["dialogue_count"] = last_evicted
    run_metrics["dialogue_live_at_exit"] = last_live
    return {"status": "ok", "dialogue_count": last_evicted,
            "live_at_exit": last_live, "samples": samples}


def backfill_dwell(cell_dir: Path, seed: int, run_metrics: dict, loc_idx: dict) -> dict:
    """Bucket per_day.location_dwell_ticks via atlas → run_metrics.dwell_by_type."""
    per_day = run_metrics.get("per_day", [])
    if not per_day:
        return {"status": "no_per_day"}
    totals = {b: 0 for b in DWELL_BUCKETS}
    totals["unknown"] = 0
    grand_total = 0
    unknown_locs = set()
    for pd in per_day:
        dwell = pd.get("location_dwell_ticks", {})
        for loc_id, ticks in dwell.items():
            loc = loc_idx.get(loc_id)
            if loc is None:
                totals["unknown"] += ticks
                unknown_locs.add(loc_id)
                grand_total += ticks
                continue
            bucket = bucket_for(loc["type"])
            if bucket is None:
                totals["unknown"] += ticks
                grand_total += ticks
            else:
                totals[bucket] += ticks
                grand_total += ticks
    pct = {f"dwell.{b}_pct": (t / grand_total if grand_total else 0.0)
           for b, t in totals.items()}
    run_metrics["dwell_by_type"] = {**totals, "total_ticks": grand_total, **pct}
    return {"status": "ok", "total_ticks": grand_total,
            "buckets": {b: totals[b] for b in DWELL_BUCKETS},
            "unknown_locs_count": len(unknown_locs)}


def _build_agent_tick_position_table(positions_path: Path,
                                     agent_ids: list[str] | None = None
                                     ) -> dict[str, list[tuple[int, str]]]:
    """Read positions.json changes → {agent_id: [(tick, location_id), ...] sorted}."""
    with open(positions_path) as f:
        pdata = json.load(f)
    table: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for c in pdata["changes"]:
        aid = c["agent_id"]
        if agent_ids is not None and aid not in agent_ids:
            continue
        table[aid].append((c["tick"], c["location_id"]))
    for aid in table:
        table[aid].sort()
    return dict(table)


def _agent_position_at_tick(timeline: list[tuple[int, str]], tick: int) -> str | None:
    """Carry-forward: agent's location at tick = last known location <= tick."""
    if not timeline or timeline[0][0] > tick:
        return None
    lo, hi = 0, len(timeline) - 1
    ans = timeline[0][1]
    while lo <= hi:
        mid = (lo + hi) // 2
        if timeline[mid][0] <= tick:
            ans = timeline[mid][1]
            lo = mid + 1
        else:
            hi = mid - 1
    return ans


def backfill_trajectory_deviation(seed: int, variant: str, cell_dir: Path,
                                  baseline_dir: Path, run_metrics: dict,
                                  loc_idx: dict,
                                  tick_sample_every: int = 12) -> dict:
    """Compute Euclidean trajectory deviation vs baseline (same seed).

    Per agent per day: at every {tick_sample_every}th tick, compute Euclidean
    distance between agent's position in this variant and in baseline. Aggregate
    to per-day mean per agent → median across agents → per-cell median + mean.

    Returns {per_day: [...], overall_median: float, overall_mean: float}.
    """
    if variant == "baseline":
        return {"status": "skip_baseline"}
    pos_self = cell_dir / f"seed_{seed}_positions.json"
    pos_base = baseline_dir / f"seed_{seed}_positions.json"
    if not pos_self.exists() or not pos_base.exists():
        return {"status": "no_positions"}
    self_table = _build_agent_tick_position_table(pos_self)
    base_table = _build_agent_tick_position_table(pos_base)

    # Iterate 14 days × 288 ticks/day, sample every N
    num_days = run_metrics.get("num_days", 14)
    ticks_per_day = 288
    total_ticks = num_days * ticks_per_day

    per_day_means: list[float | None] = []  # mean across agents per day
    all_deviations: list[float] = []  # for overall stats

    common_agents = sorted(set(self_table) & set(base_table))
    for d in range(num_days):
        day_start = d * ticks_per_day
        day_end = (d + 1) * ticks_per_day
        per_agent_means = []
        for aid in common_agents:
            distances = []
            for t in range(day_start, day_end, tick_sample_every):
                loc_self = _agent_position_at_tick(self_table[aid], t)
                loc_base = _agent_position_at_tick(base_table[aid], t)
                if loc_self is None or loc_base is None:
                    continue
                ci = loc_idx.get(loc_self)
                cb = loc_idx.get(loc_base)
                if ci is None or cb is None:
                    continue
                dx = ci["coord"][0] - cb["coord"][0]
                dy = ci["coord"][1] - cb["coord"][1]
                distances.append(math.sqrt(dx*dx + dy*dy))
            if distances:
                per_agent_means.append(statistics.mean(distances))
        if per_agent_means:
            per_day_means.append(statistics.mean(per_agent_means))
            all_deviations.extend(per_agent_means)
        else:
            per_day_means.append(None)

    valid = [d for d in all_deviations]
    overall_median = statistics.median(valid) if valid else None
    overall_mean = statistics.mean(valid) if valid else None
    run_metrics["trajectory_deviation_m"] = {
        "overall_median": overall_median,
        "overall_mean": overall_mean,
        "per_day_mean": per_day_means,
        "n_agents_compared": len(common_agents),
        "tick_sample_every": tick_sample_every,
        "baseline_ref": str(baseline_dir.name),
    }
    return {"status": "ok", "median": overall_median, "mean": overall_mean,
            "n_agents": len(common_agents)}


def process_cell(seed: int, variant: str, suite: Path, loc_idx: dict,
                 do_dialogue: bool, do_dwell: bool, do_traj: bool) -> dict:
    cell = suite / f"variant_{variant}"
    seed_json = cell / f"seed_{seed}.json"
    if not seed_json.exists():
        return {"status": "no_seed_json"}
    with open(seed_json) as f:
        sd = json.load(f)
    rm = sd["run_metrics"]
    result = {"seed": seed, "variant": variant}

    if do_dialogue:
        result["dialogue"] = backfill_dialogue_count(cell, seed, rm)
    if do_dwell:
        result["dwell"] = backfill_dwell(cell, seed, rm, loc_idx)
    if do_traj:
        baseline_cell = suite / "variant_baseline"
        result["traj"] = backfill_trajectory_deviation(
            seed, variant, cell, baseline_cell, rm, loc_idx)

    with open(seed_json, "w") as f:
        json.dump(sd, f, ensure_ascii=False, separators=(",",":"))
    return result


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", nargs="*", type=int, default=[43,44,45])
    p.add_argument("--variants", nargs="*", default=VARIANTS)
    p.add_argument("--skip-dialogue", action="store_true")
    p.add_argument("--skip-dwell",    action="store_true")
    p.add_argument("--skip-traj",     action="store_true")
    p.add_argument("--tick-sample-every", type=int, default=12)
    args = p.parse_args()

    print("Loading atlas...")
    loc_idx = build_location_index()
    print(f"  atlas index: {len(loc_idx)} locations")

    for s in args.seeds:
        suite = SEEDS.get(s)
        if not suite:
            print(f"[seed {s}] no suite mapping, skip")
            continue
        print(f"\n=== seed {s} suite={suite.name} ===")
        for v in args.variants:
            r = process_cell(
                s, v, suite, loc_idx,
                do_dialogue=not args.skip_dialogue,
                do_dwell=not args.skip_dwell,
                do_traj=not args.skip_traj,
            )
            print(f"  [{v}] {r}")


if __name__ == "__main__":
    main()
