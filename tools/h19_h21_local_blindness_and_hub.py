"""H19 + H21 联合分析

H19: GD 让人"忘记本街"? — encounter 按到 home 半径分类,GD vs BL 本街内 encounter 占比
H21: HP 创造孤独的 hub? — 比较 BL vs HP 的 per-POI dwell_ticks,挑出 hot/cold 极端

主参考: seed 44 + 45, 4 variants. 用 ledger_state.entities[home_location] + atlas 米 + memory_store agent_events kind=encounter。

H19 数据需要 per-encounter 的 location_id (memory_store.agent_events[encounter].location_id)
+ agent 的 home_location 从 population_cache 拉。

H21 直接用 run_metrics.per_day.location_dwell_ticks (在 seed_N.json 里)。
"""
import ijson
import json
import math
from pathlib import Path
from collections import defaultdict, Counter
from statistics import median, mean
import os

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
OUT_DIR = REPO / "data/analysis/2026-05-24_hypothesis_validation"
H19 = OUT_DIR / "H19_local_blindness"; H19.mkdir(parents=True, exist_ok=True)
H21 = OUT_DIR / "H21_hub_concentration"; H21.mkdir(parents=True, exist_ok=True)

ATLAS = REPO / "data/lanecove_atlas.json"
POP_CACHE = REPO / "data/population_cache/v1"

SEED_DIRS = {
    44: REPO / "data/experiments/20260522_165045_publishable_v7_day4to13_fork_seed44_BACKUP_20260522_213319_FULL_ALLVARIANTS",
    45: REPO / "data/experiments/20260522_212423_publishable_v7_day4to13_fork_seed45_BACKUP_20260523_022549_FULL_ALLVARIANTS",
}
VARIANTS = ["baseline", "hyperlocal_push", "global_distraction", "phone_friction"]


print("Loading atlas centroids...", flush=True)
atlas = json.load(open(ATLAS))
loc_xy = {}
loc_meta = {}  # location_id -> {name, type}
for bid, b in atlas["buildings"].items():
    verts = b.get("polygon", {}).get("vertices", [])
    if verts:
        xs = [v["x"] for v in verts]; ys = [v["y"] for v in verts]
        loc_xy[bid] = (sum(xs)/len(xs), sum(ys)/len(ys))
        loc_meta[bid] = {"name": b.get("name", "") or "", "type": b.get("building_type", "")}
outdoor = atlas.get("outdoor_areas", {})
out_iter = outdoor.items() if isinstance(outdoor, dict) else [(o["id"], o) for o in outdoor]
for oid, o in out_iter:
    verts = o.get("polygon", {}).get("vertices", [])
    if verts:
        xs = [v["x"] for v in verts]; ys = [v["y"] for v in verts]
        loc_xy[oid] = (sum(xs)/len(xs), sum(ys)/len(ys))
        loc_meta[oid] = {"name": o.get("name", "") or "", "type": o.get("area_type", "")}
print(f"  {len(loc_xy)} location centroids", flush=True)


def load_homes(seed):
    """agent_id -> home_location_id, from population_cache."""
    homes = {}
    for f in os.listdir(POP_CACHE):
        d = json.load(open(POP_CACHE / f))
        if d.get("key_inputs", {}).get("seed") != seed:
            continue
        for p in d.get("profiles", []):
            aid = p.get("agent_id")
            if aid:
                homes[aid] = p.get("home_location")
    return homes


def get_snap_path(seed, variant):
    d = SEED_DIRS[seed] / f"variant_{variant}"
    snaps = list(d.glob(f"seed_{seed}_pid*_tick*.snapshot.json"))
    return snaps[0] if snaps else None


def get_seed_summary_path(seed, variant):
    d = SEED_DIRS[seed] / f"variant_{variant}"
    return d / f"seed_{seed}.json"


def dist_m(a, b):
    if a not in loc_xy or b not in loc_xy:
        return None
    return math.hypot(loc_xy[a][0]-loc_xy[b][0], loc_xy[a][1]-loc_xy[b][1])


# ====================================================================
# H19: Local-radius encounter distribution
# ====================================================================
def h19_analyse_seed(seed):
    print(f"\n=== H19 SEED {seed} ===", flush=True)
    homes = load_homes(seed)
    print(f"  loaded {len(homes)} home locations", flush=True)

    variant_results = {}
    for v in VARIANTS:
        sp = get_snap_path(seed, v)
        if sp is None:
            continue
        print(f"  reading {v} snap...", flush=True)

        # Walk per-agent agent_events, count encounters per home-radius bucket
        buckets = Counter()  # bucket_label -> count
        n_enc_total = 0
        n_enc_with_loc = 0
        with open(sp) as f:
            for aid, events in ijson.kvitems(f, "memory_store_state.agent_events"):
                home = homes.get(aid)
                if home is None:
                    continue
                for ev in events:
                    if ev.get("kind") != "encounter":
                        continue
                    n_enc_total += 1
                    eloc = ev.get("location_id")
                    if eloc is None:
                        continue
                    d = dist_m(home, eloc)
                    if d is None:
                        continue
                    n_enc_with_loc += 1
                    if d < 100: b = "0-100m"
                    elif d < 300: b = "100-300m"
                    elif d < 500: b = "300-500m"
                    elif d < 1000: b = "500-1000m"
                    elif d < 2000: b = "1-2km"
                    elif d < 5000: b = "2-5km"
                    else: b = "5km+"
                    buckets[b] += 1
        variant_results[v] = {
            "n_encounters_total": n_enc_total,
            "n_with_loc": n_enc_with_loc,
            "buckets": dict(buckets),
        }
        print(f"    {v}: {n_enc_total} encounters ({n_enc_with_loc} have loc → bucketed)", flush=True)

    return variant_results


# ====================================================================
# H21: Hub concentration — per-POI dwell deltas
# ====================================================================
def h21_analyse_seed(seed):
    print(f"\n=== H21 SEED {seed} ===", flush=True)

    # Sum per-day location_dwell_ticks across all 14 days, per variant
    variant_dwell = {}
    for v in VARIANTS:
        sp = get_seed_summary_path(seed, v)
        if not sp.exists():
            print(f"  [SKIP] {v}: no seed_N.json")
            continue
        d = json.load(open(sp))
        per_day = d.get("run_metrics", {}).get("per_day", [])
        total = Counter()
        for day in per_day:
            for loc, ticks in (day.get("location_dwell_ticks") or {}).items():
                total[loc] += ticks
        variant_dwell[v] = total
        print(f"  {v:22s}: {len(total)} locations with dwell, total ticks = {sum(total.values())}", flush=True)

    bl = variant_dwell.get("baseline", Counter())

    # For each variant != baseline, compute per-POI delta
    deltas = {}
    for v in VARIANTS:
        if v == "baseline" or v not in variant_dwell:
            continue
        vd = variant_dwell[v]
        all_locs = set(vd) | set(bl)
        delta_list = []
        for loc in all_locs:
            d_bl = bl.get(loc, 0)
            d_v = vd.get(loc, 0)
            delta = d_v - d_bl
            ratio = (d_v + 1) / (d_bl + 1)  # +1 to avoid div by 0
            delta_list.append({
                "loc": loc,
                "name": loc_meta.get(loc, {}).get("name", ""),
                "type": loc_meta.get(loc, {}).get("type", ""),
                "dwell_bl": d_bl,
                "dwell_v": d_v,
                "delta": delta,
                "ratio": round(ratio, 3),
            })
        # Top 15 hot (most gained)
        delta_list.sort(key=lambda x: -x["delta"])
        top_hot = delta_list[:20]
        # Top 15 cold (most lost)
        delta_list.sort(key=lambda x: x["delta"])
        top_cold = delta_list[:20]
        # Gini-ish: how concentrated is the increase?
        positive_deltas = sorted([x["delta"] for x in delta_list if x["delta"] > 0], reverse=True)
        sum_pos = sum(positive_deltas)
        top1_share = positive_deltas[0] / sum_pos if positive_deltas and sum_pos else 0
        top5_share = sum(positive_deltas[:5]) / sum_pos if positive_deltas and sum_pos else 0
        top20_share = sum(positive_deltas[:20]) / sum_pos if positive_deltas and sum_pos else 0
        deltas[v] = {
            "top_hot": top_hot,
            "top_cold": top_cold,
            "n_locations_with_gain": sum(1 for x in delta_list if x["delta"] > 0),
            "n_locations_with_loss": sum(1 for x in delta_list if x["delta"] < 0),
            "sum_pos_dwell_delta": sum_pos,
            "top1_share_of_pos": round(top1_share, 4),
            "top5_share_of_pos": round(top5_share, 4),
            "top20_share_of_pos": round(top20_share, 4),
        }
        print(f"  {v:22s}: top1={top1_share*100:.1f}% top5={top5_share*100:.1f}% top20={top20_share*100:.1f}% of all positive dwell delta", flush=True)
    return deltas


# Run all
print("\n" + "=" * 60 + "\nH19 LOCAL BLINDNESS\n" + "=" * 60)
h19_all = {}
for s in [44, 45]:
    h19_all[s] = h19_analyse_seed(s)

print("\n" + "=" * 60 + "\nH21 HUB CONCENTRATION\n" + "=" * 60)
h21_all = {}
for s in [44, 45]:
    h21_all[s] = h21_analyse_seed(s)

# Combine H19
print("\n" + "=" * 60 + "\nH19 COMBINED HEADLINE")
combined_h19 = {}
for v in VARIANTS:
    pooled = Counter()
    n_total = 0
    for s in [44, 45]:
        if v in h19_all.get(s, {}):
            for b, c in h19_all[s][v]["buckets"].items():
                pooled[b] += c
            n_total += h19_all[s][v]["n_encounters_total"]
    if not pooled:
        continue
    total_bucketed = sum(pooled.values())
    combined_h19[v] = {
        "n_encounters_total": n_total,
        "n_bucketed": total_bucketed,
        "buckets_count": dict(pooled),
        "buckets_pct": {b: round(c / total_bucketed * 100, 2) for b, c in pooled.items()},
    }

# Print
bucket_order = ["0-100m", "100-300m", "300-500m", "500-1000m", "1-2km", "2-5km", "5km+"]
print(f"{'BUCKET':>12s}", end="")
for v in VARIANTS:
    print(f"  {v[:3]:>6s}", end="")
print()
for b in bucket_order:
    print(f"{b:>12s}", end="")
    for v in VARIANTS:
        if v in combined_h19 and b in combined_h19[v]["buckets_pct"]:
            print(f"  {combined_h19[v]['buckets_pct'][b]:5.1f}%", end="")
        else:
            print(f"  {'.':>6s}", end="")
    print()

# Local share (0-500m as "本街")
print(f"\n本街 (0-500m) encounter share %:")
for v in VARIANTS:
    if v not in combined_h19:
        continue
    bp = combined_h19[v]["buckets_pct"]
    local_share = bp.get("0-100m", 0) + bp.get("100-300m", 0) + bp.get("300-500m", 0)
    print(f"  {v:22s}: {local_share:5.1f}%")


# Combine H21 (just per-seed for now, average top-shares)
print("\n" + "=" * 60 + "\nH21 COMBINED HEADLINE")
print("Top-N share of all positive dwell-delta (concentration of HP/GD/PF 'pulled-in' dwell):")
print(f"{'VARIANT':<22s} {'top1':>8s} {'top5':>8s} {'top20':>8s} {'#gained':>8s} {'#lost':>8s}")
for v in ["hyperlocal_push", "global_distraction", "phone_friction"]:
    t1 = mean([h21_all[s][v]["top1_share_of_pos"] for s in [44, 45] if v in h21_all[s]])
    t5 = mean([h21_all[s][v]["top5_share_of_pos"] for s in [44, 45] if v in h21_all[s]])
    t20 = mean([h21_all[s][v]["top20_share_of_pos"] for s in [44, 45] if v in h21_all[s]])
    n_g = mean([h21_all[s][v]["n_locations_with_gain"] for s in [44, 45] if v in h21_all[s]])
    n_l = mean([h21_all[s][v]["n_locations_with_loss"] for s in [44, 45] if v in h21_all[s]])
    print(f"  {v:22s} {t1*100:7.1f}% {t5*100:7.1f}% {t20*100:7.1f}%  {n_g:7.0f}  {n_l:7.0f}")

# Top 5 hot POIs in HP (avg dwell delta across seeds — show seed 44 directly for first pass)
print("\nTop 10 HP-hot POIs (seed 44):")
for x in h21_all[44]["hyperlocal_push"]["top_hot"][:10]:
    name = x["name"][:40] if x["name"] else x["loc"][:40]
    print(f"  +{x['delta']:7d} ticks ({x['ratio']:6.1f}×) [{x['type']:15s}] {name}")

print("\nTop 10 HP-cold POIs (seed 44):")
for x in h21_all[44]["hyperlocal_push"]["top_cold"][:10]:
    name = x["name"][:40] if x["name"] else x["loc"][:40]
    print(f"  {x['delta']:7d} ticks ({x['ratio']:6.2f}×) [{x['type']:15s}] {name}")

# Write outputs
json.dump({"seeds": [44, 45], "per_seed": h19_all, "combined": combined_h19},
          open(H19 / "h19_local_radius.json", "w"), ensure_ascii=False, indent=2)
json.dump({"seeds": [44, 45], "per_seed": h21_all},
          open(H21 / "h21_hub_concentration.json", "w"), ensure_ascii=False, indent=2)

print(f"\n✓ H19 → {H19}\n✓ H21 → {H21}")
