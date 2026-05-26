"""Pre-compute REAL chronological trajectory paths for F1 figure.

For each (seed, variant, agent), extract the chronological sequence of
location_id visits (deduplicate consecutive same-location), convert to
atlas coords, then simplify to ~25 waypoints. The polyline through these
waypoints traces the actual road path the agent walked over 14 days.

Output: data/analysis/trajectory_cache_f1.json
"""
import json
import os
from collections import defaultdict
from pathlib import Path

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
ATLAS_PATH = REPO / "data/lanecove_atlas.json"
ANALYSIS = REPO / "data/analysis/2026-05-23_paper_exploration"
OUT_PATH = REPO / "data/analysis/trajectory_cache_f1.json"

SAMPLE_AGENTS = 99999  # all agents
SAMPLE_RESPONDERS = 99999
SAMPLE_NONRESP = 99999
# Full intervention period (day 4-9 inclusive). Set to None for all 14 days.
DAY_FILTER_MIN = 4
DAY_FILTER_MAX = 9

POS_FILES = {
    43: {
        "baseline": "data/experiments/20260521_185100_publishable_v6_day4to13_fork_seed43_BACKUP_20260522_143245/variant_baseline/seed_43_positions.json",
        "hyperlocal_push": "data/experiments/20260521_185100_publishable_v6_day4to13_fork_seed43_BACKUP_20260522_143245/variant_hyperlocal_push/seed_43_positions.json",
    },
    44: {
        "baseline": "data/experiments/20260522_165045_publishable_v7_day4to13_fork_seed44_BACKUP_20260522_213319_FULL_ALLVARIANTS/variant_baseline/seed_44_positions.json",
        "hyperlocal_push": "data/experiments/20260522_165045_publishable_v7_day4to13_fork_seed44_BACKUP_20260522_213319_FULL_ALLVARIANTS/variant_hyperlocal_push/seed_44_positions.json",
    },
    45: {
        "baseline": "data/experiments/20260522_212423_publishable_v7_day4to13_fork_seed45_BACKUP_20260523_022549_FULL_ALLVARIANTS/variant_baseline/seed_45_positions.json",
        "hyperlocal_push": "data/experiments/20260522_212423_publishable_v7_day4to13_fork_seed45_BACKUP_20260523_022549_FULL_ALLVARIANTS/variant_hyperlocal_push/seed_45_positions.json",
    },
}

print("Loading atlas → location_id → (x,y)...")
atlas = json.load(open(ATLAS_PATH))
LOC2XY = {}
for bid, b in atlas["buildings"].items():
    verts = b.get("polygon", {}).get("vertices", [])
    if verts:
        xs = [v["x"] for v in verts]
        ys = [v["y"] for v in verts]
        LOC2XY[bid] = (sum(xs)/len(xs), sum(ys)/len(ys))
outdoor = atlas["outdoor_areas"]
if isinstance(outdoor, dict):
    for oid, o in outdoor.items():
        verts = o.get("polygon", {}).get("vertices", [])
        if verts:
            xs = [v["x"] for v in verts]
            ys = [v["y"] for v in verts]
            LOC2XY[oid] = (sum(xs)/len(xs), sum(ys)/len(ys))
else:
    for o in outdoor:
        verts = o.get("polygon", {}).get("vertices", [])
        if verts and "id" in o:
            xs = [v["x"] for v in verts]
            ys = [v["y"] for v in verts]
            LOC2XY[o["id"]] = (sum(xs)/len(xs), sum(ys)/len(ys))
print(f"  {len(LOC2XY)} locations indexed")

resp = json.load(open(ANALYSIS / "C_responder_profile/agents_hyperlocal_push.json"))
RESP_BY = {(r["seed"], r["agent_id"]): r.get("is_responder", False) for r in resp}
DEV_BY = {(r["seed"], r["agent_id"]): r.get("deviation_m") for r in resp}


import random
random.seed(43)


def agent_full_path(raw_changes):
    """Sort by tick, dedupe consecutive same location, convert to (loc_id, x, y) tuples."""
    raw_changes.sort()
    seq = []
    prev_loc = None
    for tick, loc in raw_changes:
        if loc != prev_loc:
            seq.append(loc)
            prev_loc = loc
    coord_path = []
    prev_xy = None
    for loc in seq:
        xy = LOC2XY.get(loc)
        if xy is None:
            continue
        if prev_xy is not None and abs(xy[0]-prev_xy[0]) < 1 and abs(xy[1]-prev_xy[1]) < 1:
            continue
        coord_path.append([loc, round(xy[0], 1), round(xy[1], 1)])
        prev_xy = xy
    return coord_path


OUT = {"seeds": [43, 44, 45], "trajectories": {}}
for seed, variants in POS_FILES.items():
    OUT["trajectories"][str(seed)] = {}
    for variant, rel in variants.items():
        path = REPO / rel
        if not path.exists():
            print(f"MISSING: {path}")
            continue
        print(f"\nseed={seed} variant={variant} loading {path.stat().st_size / 1e6:.1f} MB...")
        d = json.load(open(path))

        per_agent = defaultdict(list)
        for c in d["changes"]:
            day = c.get("day")
            if DAY_FILTER_MIN is not None and (day is None or day < DAY_FILTER_MIN or day > DAY_FILTER_MAX):
                continue
            per_agent[c["agent_id"]].append((c["tick"], c["location_id"]))

        all_aids = list(per_agent.keys())

        # SAMPLE
        if variant == "hyperlocal_push":
            resp_aids = [a for a in all_aids if RESP_BY.get((seed, a), False)]
            nonresp_aids = [a for a in all_aids if not RESP_BY.get((seed, a), False)]
            random.shuffle(resp_aids)
            random.shuffle(nonresp_aids)
            sample_aids = resp_aids[:SAMPLE_RESPONDERS] + nonresp_aids[:SAMPLE_NONRESP]
        else:
            random.shuffle(all_aids)
            sample_aids = all_aids[:SAMPLE_AGENTS]

        agents_out = []
        for aid in sample_aids:
            wp = agent_full_path(per_agent[aid])  # now list of [loc_id, x, y]
            if len(wp) < 2:
                continue
            entry = {"aid": aid, "wp": wp}
            if variant == "hyperlocal_push":
                entry["is_responder"] = RESP_BY.get((seed, aid), False)
            agents_out.append(entry)
        avg_wp = sum(len(a['wp']) for a in agents_out) / max(len(agents_out), 1)
        print(f"  sampled {len(agents_out)} agents · avg waypoints {avg_wp:.0f} (full chrono path)")
        OUT["trajectories"][str(seed)][variant] = agents_out

print(f"\nWriting {OUT_PATH}...")
json.dump(OUT, open(OUT_PATH, "w"), separators=(",", ":"))
print(f"  done · {OUT_PATH.stat().st_size / 1e6:.1f} MB")
