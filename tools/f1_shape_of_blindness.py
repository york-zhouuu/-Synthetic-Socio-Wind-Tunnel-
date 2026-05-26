"""F1 · The Shape of Default Blindness (Depth + Geography combined)

Goal: For BASELINE variant, compute:
  (a) per-agent notice rate distribution (depth/individual axis)
  (b) per-location notice rate distribution (geography/place axis)

Notice rate = noticed encounters / total encounters at that level.

Output:
  - JSON with per-agent + per-location stats
  - PNG with 2-panel figure: (left) individual distribution histogram, (right) per-location distribution
"""
import ijson
import json
import os
from pathlib import Path
from collections import defaultdict, Counter
from statistics import median, mean, stdev

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
OUT = REPO / "data/analysis/2026-05-24_hypothesis_validation/F1_shape"
OUT.mkdir(parents=True, exist_ok=True)
ATLAS = REPO / "data/lanecove_atlas.json"

SEED_DIRS = {
    44: REPO / "data/experiments/20260522_165045_publishable_v7_day4to13_fork_seed44_BACKUP_20260522_213319_FULL_ALLVARIANTS",
    45: REPO / "data/experiments/20260522_212423_publishable_v7_day4to13_fork_seed45_BACKUP_20260523_022549_FULL_ALLVARIANTS",
}


def get_snap_path(seed, variant):
    d = SEED_DIRS[seed] / f"variant_{variant}"
    return next(d.glob(f"seed_{seed}_pid*_tick*.snapshot.json"))


print("Loading atlas building_type info...", flush=True)
atlas = json.load(open(ATLAS))
loc_meta = {}
for bid, b in atlas["buildings"].items():
    loc_meta[bid] = {"name": b.get("name", "") or "", "type": b.get("building_type", "")}
out = atlas.get("outdoor_areas", {})
out_iter = out.items() if isinstance(out, dict) else [(o["id"], o) for o in out]
for oid, o in out_iter:
    loc_meta[oid] = {"name": o.get("name", "") or "", "type": o.get("area_type", "")}
print(f"  {len(loc_meta)} location meta", flush=True)


def analyse_baseline(seed):
    """Walk BL snapshot, accumulate per-agent + per-location encounter/noticed counters."""
    snap = get_snap_path(seed, "baseline")
    print(f"\n=== SEED {seed} BL · {snap.name} ({snap.stat().st_size/1e6:.0f}MB) ===", flush=True)

    # Per-agent
    per_agent = defaultdict(lambda: {"enc": 0, "noticed": 0})
    # Per-location
    per_loc = defaultdict(lambda: {"enc": 0, "noticed": 0})

    n_agents = 0
    with open(snap) as f:
        for aid, events in ijson.kvitems(f, "memory_store_state.agent_events"):
            n_agents += 1
            if n_agents % 100 == 0:
                print(f"  {n_agents}/1000", flush=True)
            for ev in events:
                if ev.get("kind") != "encounter":
                    continue
                tags = ev.get("tags") or []
                loc = ev.get("location_id")
                per_agent[aid]["enc"] += 1
                if loc:
                    per_loc[loc]["enc"] += 1
                if "noticed" in tags:
                    per_agent[aid]["noticed"] += 1
                    if loc:
                        per_loc[loc]["noticed"] += 1

    # Compute notice rates
    agent_rates = []
    for aid, c in per_agent.items():
        if c["enc"] >= 10:  # require at least 10 encounters to be meaningful
            agent_rates.append({
                "agent_id": aid,
                "enc": c["enc"],
                "noticed": c["noticed"],
                "rate": round(c["noticed"] / c["enc"], 4),
            })

    loc_rates = []
    for lid, c in per_loc.items():
        if c["enc"] >= 20:  # filter sparse locations
            loc_rates.append({
                "loc": lid,
                "name": loc_meta.get(lid, {}).get("name", ""),
                "type": loc_meta.get(lid, {}).get("type", ""),
                "enc": c["enc"],
                "noticed": c["noticed"],
                "rate": round(c["noticed"] / c["enc"], 4),
            })

    return agent_rates, loc_rates


def summary(label, items, key="rate"):
    if not items:
        return {}
    vals = sorted(x[key] for x in items)
    n = len(vals)
    return {
        "label": label,
        "n": n,
        "mean": round(mean(vals), 4),
        "median": round(median(vals), 4),
        "stdev": round(stdev(vals), 4) if n > 1 else 0,
        "min": round(min(vals), 4),
        "max": round(max(vals), 4),
        "p10": round(vals[int(n*0.10)], 4),
        "p25": round(vals[int(n*0.25)], 4),
        "p75": round(vals[int(n*0.75)], 4),
        "p90": round(vals[int(n*0.90)], 4),
        "p99": round(vals[int(n*0.99)], 4),
    }


# Run both seeds & pool
all_agent_rates = []
all_loc_rates_per_seed = {}
for s in [44, 45]:
    ar, lr = analyse_baseline(s)
    all_agent_rates.extend(ar)
    all_loc_rates_per_seed[s] = lr
    print(f"  agents with >=10 enc: {len(ar)}", flush=True)
    print(f"  locations with >=20 enc: {len(lr)}", flush=True)

# Pool location across seeds: sum enc+noticed by loc id
loc_pool = defaultdict(lambda: {"enc": 0, "noticed": 0})
for s in [44, 45]:
    for x in all_loc_rates_per_seed[s]:
        loc_pool[x["loc"]]["enc"] += x["enc"]
        loc_pool[x["loc"]]["noticed"] += x["noticed"]
loc_pooled = []
for lid, c in loc_pool.items():
    if c["enc"] >= 40:  # pooled threshold higher
        loc_pooled.append({
            "loc": lid,
            "name": loc_meta.get(lid, {}).get("name", ""),
            "type": loc_meta.get(lid, {}).get("type", ""),
            "enc": c["enc"],
            "noticed": c["noticed"],
            "rate": round(c["noticed"] / c["enc"], 4),
        })

# Stats
agent_summary = summary("per-agent (BL, seed 44+45 pooled)", all_agent_rates)
loc_summary = summary("per-location (BL, seed 44+45 pooled)", loc_pooled)

print("\n" + "=" * 70)
print(f"AGENT notice rate (n={agent_summary['n']}):")
for k in ["min", "p10", "p25", "median", "mean", "p75", "p90", "p99", "max"]:
    print(f"  {k:>8s}: {agent_summary[k]*100:>6.2f}%")
print(f"  stdev:  {agent_summary['stdev']*100:.2f}pp")

print(f"\nLOCATION notice rate (n={loc_summary['n']}):")
for k in ["min", "p10", "p25", "median", "mean", "p75", "p90", "p99", "max"]:
    print(f"  {k:>8s}: {loc_summary[k]*100:>6.2f}%")
print(f"  stdev:  {loc_summary['stdev']*100:.2f}pp")

# Bin agents
agent_bins = Counter()
for a in all_agent_rates:
    r = a["rate"] * 100
    if r < 2: b = "<2%"
    elif r < 5: b = "2-5%"
    elif r < 10: b = "5-10%"
    elif r < 15: b = "10-15%"
    elif r < 20: b = "15-20%"
    elif r < 30: b = "20-30%"
    elif r < 50: b = "30-50%"
    else: b = ">50%"
    agent_bins[b] += 1
print(f"\nAgent distribution buckets (n={agent_summary['n']}):")
for b in ["<2%", "2-5%", "5-10%", "10-15%", "15-20%", "20-30%", "30-50%", ">50%"]:
    c = agent_bins.get(b, 0)
    pct = c / agent_summary["n"] * 100 if agent_summary["n"] else 0
    bar = "█" * int(pct / 2)
    print(f"  {b:>8s} {c:>4d}  {pct:>5.1f}%  {bar}")

# Location: by type breakdown
type_stats = defaultdict(lambda: {"enc": 0, "noticed": 0, "n_locs": 0})
for x in loc_pooled:
    t = x["type"] or "(unknown)"
    type_stats[t]["enc"] += x["enc"]
    type_stats[t]["noticed"] += x["noticed"]
    type_stats[t]["n_locs"] += 1
type_rows = []
for t, c in type_stats.items():
    if c["enc"] >= 100:
        type_rows.append({
            "type": t,
            "n_locs": c["n_locs"],
            "total_enc": c["enc"],
            "total_noticed": c["noticed"],
            "rate": round(c["noticed"] / c["enc"], 4),
        })
type_rows.sort(key=lambda x: -x["rate"])
print(f"\nLocation notice rate by building_type (filter ≥100 enc/type, sort by rate):")
for r in type_rows:
    print(f"  {r['type']:18s}  n_locs={r['n_locs']:4d}  enc={r['total_enc']:7d}  rate={r['rate']*100:5.2f}%")

# Top/Bottom locations
loc_pooled_sorted = sorted(loc_pooled, key=lambda x: -x["rate"])
print(f"\nTop 15 highest notice-rate locations (BL, ≥40 enc):")
for x in loc_pooled_sorted[:15]:
    name = x["name"][:40] if x["name"] else x["loc"][:40]
    print(f"  {x['rate']*100:5.1f}% (n={x['enc']:4d}) [{x['type']:14s}] {name}")
print(f"\nBottom 15 lowest notice-rate locations:")
for x in sorted(loc_pooled, key=lambda x: x["rate"])[:15]:
    name = x["name"][:40] if x["name"] else x["loc"][:40]
    print(f"  {x['rate']*100:5.1f}% (n={x['enc']:4d}) [{x['type']:14s}] {name}")

# Output
json.dump({
    "method": "BL variant, seed 44+45 pooled · noticed = encounter event with 'noticed' in tags",
    "agent_summary": agent_summary,
    "agent_distribution_buckets": dict(agent_bins),
    "location_summary": loc_summary,
    "location_by_building_type": type_rows,
    "top_15_locations": loc_pooled_sorted[:15],
    "bottom_15_locations": sorted(loc_pooled, key=lambda x: x["rate"])[:15],
    "all_agent_rates": all_agent_rates,
    "all_location_rates": loc_pooled,
}, open(OUT / "f1_shape_baseline.json", "w"), ensure_ascii=False, indent=2)

print(f"\n✓ {OUT / 'f1_shape_baseline.json'}")
