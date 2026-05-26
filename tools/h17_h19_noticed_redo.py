"""重跑 H17 + H19 — 用 NOTICED 口径(过 attention gate 的子集),
不是 distinct_pairs / agent_events[encounter] all。

Noticed filter (per Hannah/Mary case studies):
  e.kind == 'encounter' AND 'noticed' in (e.tags or [])

H17 (familiar vs stranger): walk noticed encounters → extract (a, related_a) pairs
H19 (home radius): walk noticed encounters → bucket by distance from home

主参考: seed 44 + 45, 4 variants
"""
import ijson
import json
import math
import os
from pathlib import Path
from collections import defaultdict, Counter

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
OUT_DIR = REPO / "data/analysis/2026-05-24_hypothesis_validation"
H17 = OUT_DIR / "H17_familiarity_noticed"; H17.mkdir(parents=True, exist_ok=True)
H19 = OUT_DIR / "H19_local_blindness_noticed"; H19.mkdir(parents=True, exist_ok=True)

ATLAS = REPO / "data/lanecove_atlas.json"
POP_CACHE = REPO / "data/population_cache/v1"

SEED_DIRS = {
    44: REPO / "data/experiments/20260522_165045_publishable_v7_day4to13_fork_seed44_BACKUP_20260522_213319_FULL_ALLVARIANTS",
    45: REPO / "data/experiments/20260522_212423_publishable_v7_day4to13_fork_seed45_BACKUP_20260523_022549_FULL_ALLVARIANTS",
}
VARIANTS = ["baseline", "hyperlocal_push", "global_distraction", "phone_friction"]


def get_snap_path(seed, variant):
    d = SEED_DIRS[seed] / f"variant_{variant}"
    return next(d.glob(f"seed_{seed}_pid*_tick*.snapshot.json"))


print("Loading atlas centroids...", flush=True)
atlas = json.load(open(ATLAS))
loc_xy = {}
for bid, b in atlas["buildings"].items():
    verts = b.get("polygon", {}).get("vertices", [])
    if verts:
        xs = [v["x"] for v in verts]; ys = [v["y"] for v in verts]
        loc_xy[bid] = (sum(xs)/len(xs), sum(ys)/len(ys))
out = atlas.get("outdoor_areas", {})
out_iter = out.items() if isinstance(out, dict) else [(o["id"], o) for o in out]
for oid, o in out_iter:
    verts = o.get("polygon", {}).get("vertices", [])
    if verts:
        xs = [v["x"] for v in verts]; ys = [v["y"] for v in verts]
        loc_xy[oid] = (sum(xs)/len(xs), sum(ys)/len(ys))
print(f"  {len(loc_xy)} centroids", flush=True)


def load_homes(seed):
    homes = {}
    for f in os.listdir(POP_CACHE):
        d = json.load(open(POP_CACHE / f))
        if d.get("key_inputs", {}).get("seed") != seed: continue
        for p in d.get("profiles", []):
            aid = p.get("agent_id")
            if aid: homes[aid] = p.get("home_location")
    return homes


def dist_m(a, b):
    if a not in loc_xy or b not in loc_xy: return None
    return math.hypot(loc_xy[a][0]-loc_xy[b][0], loc_xy[a][1]-loc_xy[b][1])


# Walk each variant's snap ONCE, extract noticed encounter info for BOTH H17 + H19
def analyse_snap(snap_path, seed, variant, homes):
    """Returns:
      - noticed_pairs: set of (a, b) sorted tuples (H17)
      - home_bucket_counts: dict bucket -> count (H19)
      - n_noticed_total: total noticed encounters
      - n_encounter_total: total encounters (for ratio)
    """
    print(f"  reading {snap_path.name} ({snap_path.stat().st_size/1e6:.0f}MB)...", flush=True)
    noticed_pairs = set()
    home_buckets = Counter()
    n_noticed = 0
    n_enc = 0
    n_proc_agents = 0

    with open(snap_path) as f:
        for aid, events in ijson.kvitems(f, "memory_store_state.agent_events"):
            n_proc_agents += 1
            if n_proc_agents % 200 == 0:
                print(f"    {n_proc_agents} agents processed...", flush=True)
            home = homes.get(aid)
            for ev in events:
                if ev.get("kind") != "encounter": continue
                n_enc += 1
                tags = ev.get("tags") or []
                if "noticed" not in tags: continue
                n_noticed += 1

                # H17: pair extraction (actor_id is the OTHER agent)
                partner = ev.get("actor_id")
                if partner and partner != aid:
                    noticed_pairs.add(tuple(sorted([aid, partner])))

                # H19: bucket by home distance
                eloc = ev.get("location_id")
                if home is None or eloc is None: continue
                d = dist_m(home, eloc)
                if d is None: continue
                if d < 100: b = "0-100m"
                elif d < 300: b = "100-300m"
                elif d < 500: b = "300-500m"
                elif d < 1000: b = "500-1000m"
                elif d < 2000: b = "1-2km"
                elif d < 5000: b = "2-5km"
                else: b = "5km+"
                home_buckets[b] += 1

    notice_rate = n_noticed / n_enc if n_enc else 0
    print(f"    [{variant}] noticed: {n_noticed:,} / total encounters: {n_enc:,} ({notice_rate*100:.1f}%) · pairs: {len(noticed_pairs):,}", flush=True)
    return {
        "noticed_pairs": noticed_pairs,
        "home_buckets": dict(home_buckets),
        "n_noticed_total": n_noticed,
        "n_encounter_total": n_enc,
        "notice_rate": round(notice_rate, 4),
    }


all_data = {}
for seed in [44, 45]:
    print(f"\n=== SEED {seed} ===", flush=True)
    homes = load_homes(seed)
    print(f"  loaded {len(homes)} homes", flush=True)
    per_var = {}
    for v in VARIANTS:
        per_var[v] = analyse_snap(get_snap_path(seed, v), seed, v, homes)
    all_data[seed] = per_var


# H17 combined: union noticed pairs across seeds per variant
print("\n" + "=" * 70)
print("H17 (NOTICED口径) · familiar vs stranger pairs")
print("=" * 70)

combined_pairs = {v: set() for v in VARIANTS}
for seed in [44, 45]:
    for v in VARIANTS:
        combined_pairs[v] |= all_data[seed][v]["noticed_pairs"]

bl_set = combined_pairs["baseline"]
print(f"\n{'VARIANT':<22s} {'total_pairs':>12s} {'shared_BL':>12s} {'NEW':>10s} {'%new':>7s} {'lost_from_BL':>13s}")
h17_results = {}
for v in VARIANTS:
    vp = combined_pairs[v]
    shared = vp & bl_set
    new = vp - bl_set
    lost = bl_set - vp
    pct = round(len(new)/len(vp)*100, 1) if vp else 0
    h17_results[v] = {
        "total_pairs": len(vp),
        "shared_with_baseline": len(shared),
        "new_pairs": len(new),
        "lost_from_baseline": len(lost),
        "pct_new": pct,
        "ratio_vs_bl": round(len(vp) / len(bl_set), 3) if bl_set else 0,
    }
    print(f"  {v:22s} {len(vp):>12,} {len(shared):>12,} {len(new):>10,} {pct:>6.1f}% {len(lost):>13,}")

bl_n = len(bl_set)
if bl_n > 0:
    print(f"\nNet pair change vs BL ({bl_n}):")
    for v in ["hyperlocal_push", "global_distraction", "phone_friction"]:
        n = h17_results[v]["total_pairs"]
        print(f"  {v:22s}: {n:,} (ratio {n/bl_n:.2f}× · Δ {n-bl_n:+,})")
else:
    print(f"\n⚠ BL pair count = 0, cannot compute ratios")


# H19 combined: pool buckets across seeds per variant
print("\n" + "=" * 70)
print("H19 (NOTICED口径) · 注意到的人按 home 距离分桶")
print("=" * 70)

combined_buckets = {v: Counter() for v in VARIANTS}
combined_totals = {v: 0 for v in VARIANTS}
combined_n_noticed = {v: 0 for v in VARIANTS}
combined_n_enc = {v: 0 for v in VARIANTS}
for seed in [44, 45]:
    for v in VARIANTS:
        d = all_data[seed][v]
        for b, c in d["home_buckets"].items():
            combined_buckets[v][b] += c
        combined_n_noticed[v] += d["n_noticed_total"]
        combined_n_enc[v] += d["n_encounter_total"]

print(f"\nNotice rate per variant (noticed / total encounters):")
for v in VARIANTS:
    nr = combined_n_noticed[v] / combined_n_enc[v] if combined_n_enc[v] else 0
    print(f"  {v:22s} {combined_n_noticed[v]:>10,} / {combined_n_enc[v]:>10,} = {nr*100:.1f}%")

bucket_order = ["0-100m", "100-300m", "300-500m", "500-1000m", "1-2km", "2-5km", "5km+"]
h19_results = {}
print(f"\n{'BUCKET':>12s}", end="")
for v in VARIANTS:
    print(f"  {v[:3]:>6s}", end="")
print()
for b in bucket_order:
    print(f"{b:>12s}", end="")
    for v in VARIANTS:
        total = sum(combined_buckets[v].values())
        c = combined_buckets[v].get(b, 0)
        pct = c/total*100 if total else 0
        print(f"  {pct:5.1f}%", end="")
    print()

# 本街 (0-500m) share
print(f"\n本街 (home 0-500m) 注意到人的占比:")
local_shares = {}
for v in VARIANTS:
    total = sum(combined_buckets[v].values())
    local = sum(combined_buckets[v].get(b, 0) for b in ["0-100m", "100-300m", "300-500m"])
    local_pct = round(local/total*100, 2) if total else 0
    local_shares[v] = local_pct
    print(f"  {v:22s}: {local_pct:5.1f}%   (noticed total = {total:,})")

for v in VARIANTS:
    total = sum(combined_buckets[v].values())
    h19_results[v] = {
        "total_noticed_with_loc": total,
        "n_noticed_total": combined_n_noticed[v],
        "n_encounter_total": combined_n_enc[v],
        "notice_rate": round(combined_n_noticed[v]/combined_n_enc[v], 4) if combined_n_enc[v] else 0,
        "buckets_count": dict(combined_buckets[v]),
        "buckets_pct": {b: round(combined_buckets[v].get(b, 0) / total * 100, 2) if total else 0 for b in bucket_order},
        "local_500m_share_pct": local_shares[v],
    }


# Write outputs (NOT including raw pair sets — too big)
json.dump({
    "method": "agent_events[kind=encounter, 'noticed' in tags] · pair from related_agents",
    "seeds": [44, 45],
    "per_seed_notice_stats": {s: {v: {
        "n_noticed_total": all_data[s][v]["n_noticed_total"],
        "n_encounter_total": all_data[s][v]["n_encounter_total"],
        "notice_rate": all_data[s][v]["notice_rate"],
    } for v in VARIANTS} for s in [44, 45]},
    "combined": h17_results,
}, open(H17 / "h17_noticed_pairs.json", "w"), ensure_ascii=False, indent=2)

json.dump({
    "method": "agent_events[kind=encounter, 'noticed' in tags] · bucket by dist from home",
    "seeds": [44, 45],
    "combined": h19_results,
}, open(H19 / "h19_noticed_home_radius.json", "w"), ensure_ascii=False, indent=2)

print(f"\n✓ {H17}")
print(f"✓ {H19}")
