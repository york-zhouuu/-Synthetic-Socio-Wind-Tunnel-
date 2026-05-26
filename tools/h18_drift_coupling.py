"""H18: 同 agent 在 4 个 universe 里末态物理距离的耦合度

理论上 4 个宇宙的同 agent 应该:
- BL 终点 = 默认行为
- HP 终点 = 被本街推送拉动 → 应该靠近 push targets
- GD 终点 = attention drift → 可能漂去 CBD (随机)
- PF 终点 = 抬头偶遇 → 应该接近 BL 但更敏感于附近 anchor

H18 问的是: 推送的"位移效应"集中在少数 responder 身上,还是均匀分布?

输出: per-agent 4-universe 终态距离矩阵 (BL-HP, BL-GD, BL-PF, HP-GD, HP-PF, GD-PF)
+ 距离分布百分位 + responder vs non-responder 区分

主参考: seed 44 + 45, 4 variants. 用 ledger_state.entities 末态位置 + atlas 转米。
"""
import ijson
import json
import math
from pathlib import Path
from statistics import median, mean

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
OUT = REPO / "data/analysis/2026-05-24_hypothesis_validation/H18_drift"
OUT.mkdir(parents=True, exist_ok=True)

ATLAS = REPO / "data/lanecove_atlas.json"

SEED_DIRS = {
    44: REPO / "data/experiments/20260522_165045_publishable_v7_day4to13_fork_seed44_BACKUP_20260522_213319_FULL_ALLVARIANTS",
    45: REPO / "data/experiments/20260522_212423_publishable_v7_day4to13_fork_seed45_BACKUP_20260523_022549_FULL_ALLVARIANTS",
}
VARIANTS = ["baseline", "hyperlocal_push", "global_distraction", "phone_friction"]


def get_snap_path(seed, variant):
    d = SEED_DIRS[seed] / f"variant_{variant}"
    snaps = list(d.glob(f"seed_{seed}_pid*_tick*.snapshot.json"))
    return snaps[0] if snaps else None


print("Loading atlas for location centroids...", flush=True)
atlas = json.load(open(ATLAS))
loc_xy = {}  # location_id -> (x, y) in atlas-local meters
for bid, b in atlas["buildings"].items():
    verts = b.get("polygon", {}).get("vertices", [])
    if verts:
        xs = [v["x"] for v in verts]; ys = [v["y"] for v in verts]
        loc_xy[bid] = (sum(xs)/len(xs), sum(ys)/len(ys))
outdoor = atlas.get("outdoor_areas", {})
out_iter = outdoor.items() if isinstance(outdoor, dict) else [(o["id"], o) for o in outdoor]
for oid, o in out_iter:
    verts = o.get("polygon", {}).get("vertices", [])
    if verts:
        xs = [v["x"] for v in verts]; ys = [v["y"] for v in verts]
        loc_xy[oid] = (sum(xs)/len(xs), sum(ys)/len(ys))
print(f"  {len(loc_xy)} locations with centroids", flush=True)


def extract_end_positions(snap_path):
    """ledger_state.entities.{agent_id}.{position} for all agents."""
    print(f"  reading entities from {snap_path.name}...", flush=True)
    end = {}  # agent_id -> location_id
    with open(snap_path) as f:
        for aid, e in ijson.kvitems(f, "ledger_state.entities"):
            loc = e.get("location_id")
            if loc:
                end[aid] = loc
    return end


def dist_m(a, b):
    """Distance in meters between two location_ids using atlas centroids."""
    if a not in loc_xy or b not in loc_xy:
        return None
    ax, ay = loc_xy[a]
    bx, by = loc_xy[b]
    return math.sqrt((ax-bx)**2 + (ay-by)**2)


def analyse_seed(seed):
    print(f"\n=== SEED {seed} ===", flush=True)
    end_per_variant = {}
    for v in VARIANTS:
        sp = get_snap_path(seed, v)
        if sp is None:
            print(f"  [SKIP] {v}")
            continue
        end_per_variant[v] = extract_end_positions(sp)
        print(f"  {v:22s}: {len(end_per_variant[v])} agents with end_loc", flush=True)

    # Pairwise distance per agent
    pairs = [
        ("baseline", "hyperlocal_push"),
        ("baseline", "global_distraction"),
        ("baseline", "phone_friction"),
        ("hyperlocal_push", "global_distraction"),
        ("hyperlocal_push", "phone_friction"),
        ("global_distraction", "phone_friction"),
    ]

    agent_drift = {}  # agent_id -> {pair_name: distance_m}
    for v1, v2 in pairs:
        if v1 not in end_per_variant or v2 not in end_per_variant:
            continue
        e1, e2 = end_per_variant[v1], end_per_variant[v2]
        common = set(e1) & set(e2)
        for aid in common:
            d = dist_m(e1[aid], e2[aid])
            if d is None:
                continue
            agent_drift.setdefault(aid, {})[f"{v1}__{v2}"] = round(d, 1)

    # Aggregate distributions
    summary = {}
    for v1, v2 in pairs:
        key = f"{v1}__{v2}"
        dists = [d[key] for d in agent_drift.values() if key in d]
        if not dists:
            continue
        dists_sorted = sorted(dists)
        n = len(dists)
        summary[key] = {
            "n": n,
            "mean_m": round(mean(dists), 1),
            "median_m": round(median(dists), 1),
            "p25_m": round(dists_sorted[n//4], 1),
            "p75_m": round(dists_sorted[3*n//4], 1),
            "p90_m": round(dists_sorted[int(n*0.90)], 1),
            "p95_m": round(dists_sorted[int(n*0.95)], 1),
            "p99_m": round(dists_sorted[int(n*0.99)], 1),
            "max_m": round(max(dists), 1),
            "frac_moved_gt_100m": round(sum(1 for d in dists if d > 100) / n, 4),
            "frac_moved_gt_500m": round(sum(1 for d in dists if d > 500) / n, 4),
            "frac_moved_gt_1000m": round(sum(1 for d in dists if d > 1000) / n, 4),
            "frac_zero": round(sum(1 for d in dists if d < 1) / n, 4),
        }
    return summary, agent_drift


all_summaries = {}
all_drifts = {}
for s in [44, 45]:
    summ, drift = analyse_seed(s)
    all_summaries[s] = summ
    all_drifts[s] = drift

# Combined (pool both seeds)
print("\n=== COMBINED ===")
pairs = [
    ("baseline", "hyperlocal_push"),
    ("baseline", "global_distraction"),
    ("baseline", "phone_friction"),
    ("hyperlocal_push", "global_distraction"),
    ("hyperlocal_push", "phone_friction"),
    ("global_distraction", "phone_friction"),
]
combined_summary = {}
for v1, v2 in pairs:
    key = f"{v1}__{v2}"
    pooled = []
    for s in [44, 45]:
        for aid, ds in all_drifts.get(s, {}).items():
            if key in ds:
                pooled.append(ds[key])
    if not pooled:
        continue
    ps = sorted(pooled)
    n = len(ps)
    combined_summary[key] = {
        "n": n,
        "mean_m": round(mean(pooled), 1),
        "median_m": round(median(pooled), 1),
        "p25_m": round(ps[n//4], 1),
        "p75_m": round(ps[3*n//4], 1),
        "p90_m": round(ps[int(n*0.90)], 1),
        "p95_m": round(ps[int(n*0.95)], 1),
        "p99_m": round(ps[int(n*0.99)], 1),
        "max_m": round(max(pooled), 1),
        "frac_moved_gt_100m": round(sum(1 for d in pooled if d > 100) / n, 4),
        "frac_moved_gt_500m": round(sum(1 for d in pooled if d > 500) / n, 4),
        "frac_moved_gt_1000m": round(sum(1 for d in pooled if d > 1000) / n, 4),
        "frac_zero": round(sum(1 for d in pooled if d < 1) / n, 4),
    }

json.dump({
    "method": "ledger_state.entities[agent].position → atlas centroid → euclidean",
    "seeds": [44, 45],
    "per_seed_summary": all_summaries,
    "combined_summary": combined_summary,
}, open(OUT / "h18_drift_matrix.json", "w"), ensure_ascii=False, indent=2)

# Headline
print("\n" + "=" * 60)
print("H18 · 4-Universe drift matrix (combined seed 44+45)")
print(f"{'PAIR':45s} {'n':>5s} {'mean':>7s} {'med':>6s} {'p90':>6s} {'p95':>6s} {'p99':>6s} {'max':>6s}  {'>100m':>6s} {'>500m':>6s} {'>1km':>6s} {'zero':>6s}")
for v1, v2 in pairs:
    k = f"{v1}__{v2}"
    if k not in combined_summary:
        continue
    s = combined_summary[k]
    label = f"{v1[:3]:>3s} ↔ {v2[:3]:<3s}"
    print(f"  {label:45s} {s['n']:5d} {s['mean_m']:7.1f} {s['median_m']:6.1f} {s['p90_m']:6.0f} {s['p95_m']:6.0f} {s['p99_m']:6.0f} {s['max_m']:6.0f}  {s['frac_moved_gt_100m']*100:5.1f}% {s['frac_moved_gt_500m']*100:5.1f}% {s['frac_moved_gt_1000m']*100:5.1f}% {s['frac_zero']*100:5.1f}%")

print(f"\n✓ output: {OUT / 'h18_drift_matrix.json'}")
