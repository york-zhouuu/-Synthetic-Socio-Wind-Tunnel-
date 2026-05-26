"""Aggregate location visit counts across 3 seeds × {BL, HP} for F1 heatmap.

For each location_id, count how many UNIQUE agents visited it over 14 days,
summed across 3 seeds. Output:
{
  "baseline": {location_id: count, ...},
  "hyperlocal_push": {location_id: count, ...},
}

Used to render heat map: building/outdoor polygons colored by visit density.
"""
import json
from collections import defaultdict
from pathlib import Path

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
OUT_PATH = REPO / "data/analysis/heatmap_cache_f1.json"

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

agg = {"baseline": defaultdict(int), "hyperlocal_push": defaultdict(int)}

for seed, variants in POS_FILES.items():
    for variant, rel in variants.items():
        path = REPO / rel
        if not path.exists():
            print(f"MISSING: {path}")
            continue
        print(f"seed={seed} variant={variant} loading {path.stat().st_size / 1e6:.1f} MB...")
        d = json.load(open(path))

        # Per-location set of unique agents
        loc_agents = defaultdict(set)
        for c in d["changes"]:
            loc_agents[c["location_id"]].add(c["agent_id"])

        # Add to aggregate
        for loc_id, agents in loc_agents.items():
            agg[variant][loc_id] += len(agents)

OUT = {
    "baseline": dict(agg["baseline"]),
    "hyperlocal_push": dict(agg["hyperlocal_push"]),
}
print(f"\nbaseline:    {len(OUT['baseline'])} distinct locations")
print(f"hyperlocal_push: {len(OUT['hyperlocal_push'])} distinct locations")

# Stats
import statistics
for variant in ["baseline", "hyperlocal_push"]:
    counts = list(OUT[variant].values())
    counts.sort(reverse=True)
    print(f"\n{variant} top 5:")
    # Print top 5 to spot-check
    top = sorted(OUT[variant].items(), key=lambda x: -x[1])[:5]
    for loc, c in top:
        print(f"  {loc}: {c} unique agent-visits")
    print(f"  median: {statistics.median(counts)}, p90: {counts[int(len(counts)*0.1)]}, max: {counts[0]}")

json.dump(OUT, open(OUT_PATH, "w"), separators=(",", ":"))
print(f"\nWritten {OUT_PATH} · {OUT_PATH.stat().st_size / 1e3:.0f} KB")
