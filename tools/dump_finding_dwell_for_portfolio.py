"""Dump per-POI dwell deltas for F1 / F2 finding overlays in the portfolio cinema.

Reads the same data as `tools/hero_figure_siphon.py` (seed 44 BL/HP/PF dwell),
extracts top-N hottest POIs by delta-vs-baseline, joins with atlas centroids
+ names + types, writes a compact JSON the portfolio can load at runtime.

Output: portfolio/public/case-studies/sswt/finding-anchors.json

Schema:
{
  "f1_siphon": {
    "top_pois": [
      { "id", "name", "type", "x", "y", "delta_ticks", "ratio", "bl", "hp" },
      ... (top 30 sorted desc by delta)
    ],
    "top_anchors": [...top 5, same shape...]
  },
  "f2_friction": {
    "hp_anchors": [...top 5 in HP-BL...],
    "pf_anchors": [...top 5 in PF-BL...],
    "overlap_anchors": [...intersection...],
    "top_pois_hp": [...top 30 HP...],
    "top_pois_pf": [...top 30 PF...]
  }
}
"""
import json
from pathlib import Path
from collections import Counter

import math

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
PORTFOLIO = Path("/Users/york_z/Documents/GitHub/portfolio")
ATLAS = REPO / "data/lanecove_atlas.json"
SEED_DIR = REPO / "data/experiments/20260522_165045_publishable_v7_day4to13_fork_seed44_BACKUP_20260522_213319_FULL_ALLVARIANTS"
# F3 movable analysis uses seed 43 (per `tools/f3_movable_map.py`).
SEED43_DIR = REPO / "data/experiments/20260521_185100_publishable_v6_day4to13_fork_seed43_BACKUP_20260522_143245"
MOVABLE_THRESHOLD_M = 100.0
OUT = PORTFOLIO / "public/case-studies/sswt/finding-anchors.json"


def load_dwell(variant):
    p = SEED_DIR / f"variant_{variant}" / "seed_44.json"
    d = json.load(open(p))
    per_day = d.get("run_metrics", {}).get("per_day", [])
    total = Counter()
    for day in per_day:
        for loc, ticks in (day.get("location_dwell_ticks") or {}).items():
            total[loc] += ticks
    return total


def load_atlas_meta():
    atlas = json.load(open(ATLAS))
    meta = {}
    for bid, b in atlas["buildings"].items():
        verts = b.get("polygon", {}).get("vertices", [])
        if verts:
            xs = [v["x"] for v in verts]
            ys = [v["y"] for v in verts]
            meta[bid] = {
                "name": b.get("name", "") or "",
                "type": b.get("building_type", ""),
                "x": sum(xs) / len(xs),
                "y": sum(ys) / len(ys),
            }
    out = atlas.get("outdoor_areas", {})
    out_iter = out.items() if isinstance(out, dict) else [(o["id"], o) for o in out]
    for oid, o in out_iter:
        verts = o.get("polygon", {}).get("vertices", [])
        if verts:
            xs = [v["x"] for v in verts]
            ys = [v["y"] for v in verts]
            meta[oid] = {
                "name": o.get("name", "") or "",
                "type": o.get("area_type", ""),
                "x": sum(xs) / len(xs),
                "y": sum(ys) / len(ys),
            }
    return meta


def top_n_by_delta(target_dwell, bl_dwell, atlas_meta, n=30, min_delta=1000):
    all_locs = set(target_dwell) | set(bl_dwell)
    deltas = []
    for loc in all_locs:
        if loc not in atlas_meta:
            continue
        bl = bl_dwell.get(loc, 0)
        tg = target_dwell.get(loc, 0)
        delta = tg - bl
        if delta <= min_delta:
            continue
        ratio = (tg + 1) / (bl + 1)
        deltas.append({
            "id": loc,
            "name": atlas_meta[loc]["name"],
            "type": atlas_meta[loc]["type"],
            "x": atlas_meta[loc]["x"],
            "y": atlas_meta[loc]["y"],
            "bl": bl,
            "hp": tg,  # named "hp" generically — caller knows variant
            "delta_ticks": delta,
            "ratio": round(ratio, 1),
        })
    deltas.sort(key=lambda x: -x["delta_ticks"])
    return deltas[:n]


print("Loading atlas...", flush=True)
meta = load_atlas_meta()
print(f"  {len(meta)} POIs (buildings + outdoor areas)", flush=True)

print("Loading dwell ticks (baseline / hyperlocal_push / phone_friction)...", flush=True)
bl = load_dwell("baseline")
hp = load_dwell("hyperlocal_push")
pf = load_dwell("phone_friction")
print(f"  BL {len(bl)} POIs · HP {len(hp)} POIs · PF {len(pf)} POIs", flush=True)

# F1 siphon: HP vs BL
f1_top30 = top_n_by_delta(hp, bl, meta, n=30)
f1_top5 = f1_top30[:5]
print(f"\nF1 top 5 (HP - BL):")
for a in f1_top5:
    print(f"  +{a['delta_ticks']//1000:>5}K · {a['ratio']:>5}x · {a['name'][:35]}")

# F2 friction: HP-BL and PF-BL separately
f2_hp_top30 = top_n_by_delta(hp, bl, meta, n=30)
f2_pf_top30 = top_n_by_delta(pf, bl, meta, n=30)
f2_hp_top5_ids = {a["id"] for a in f2_hp_top30[:5]}
f2_pf_top5_ids = {a["id"] for a in f2_pf_top30[:5]}
overlap_ids = f2_hp_top5_ids & f2_pf_top5_ids
print(f"\nF2 HP top 5 anchors:")
for a in f2_hp_top30[:5]:
    print(f"  HP +{a['delta_ticks']//1000:>5}K · {a['name'][:35]}")
print(f"\nF2 PF top 5 anchors:")
for a in f2_pf_top30[:5]:
    print(f"  PF +{a['delta_ticks']//1000:>5}K · {a['name'][:35]}")
print(f"\nF2 overlap (top 5 ∩): {len(overlap_ids)} anchors")
for oid in overlap_ids:
    print(f"  ⊕ {meta.get(oid, {}).get('name', oid)}")

# Compute world bounds for normalization (portfolio uses normalized coords)
active_pois = [p for p in meta.values() if p["x"] is not None]
xs = [p["x"] for p in active_pois]
ys = [p["y"] for p in active_pois]
bounds = {
    "min_x": min(xs),
    "max_x": max(xs),
    "min_y": min(ys),
    "max_y": max(ys),
}

## F3 routine cliff — per-agent movable classification.
## Replicates `tools/f3_movable_map.py`: load BL & HP end positions
## from seed_43 positions.json, classify each agent as movable if their
## HP end-position is >= 100 m from their BL end-position.

def load_end_positions_with_loc(variant_dir: Path, agent_centroids):
    """Last location per agent → (location_id, centroid_x, centroid_y in meters)."""
    pos_file = variant_dir / "seed_43_positions.json"
    if not pos_file.exists():
        return {}
    d = json.load(pos_file.open())
    changes = d.get("changes") or []
    last_loc = {}
    for ch in changes:
        aid = ch.get("agent_id")
        loc = ch.get("location_id")
        if aid and loc:
            last_loc[aid] = loc
    out = {}
    for aid, loc in last_loc.items():
        if loc in agent_centroids:
            cx, cy = agent_centroids[loc]
            out[aid] = (loc, cx, cy)
    return out


print("\nLoading F3 end-position data (seed 43)...", flush=True)
centroids_only = {k: (v["x"], v["y"]) for k, v in meta.items()}
bl_pos = load_end_positions_with_loc(SEED43_DIR / "variant_baseline", centroids_only)
hp_pos = load_end_positions_with_loc(SEED43_DIR / "variant_hyperlocal_push", centroids_only)
print(f"  BL: {len(bl_pos)} agents · HP: {len(hp_pos)} agents", flush=True)

f3_agents = []
n_mov = 0
for aid, (bl_loc, bx, by) in bl_pos.items():
    moved = False
    if aid in hp_pos:
        _, cx, cy = hp_pos[aid]
        if math.hypot(cx - bx, cy - by) >= MOVABLE_THRESHOLD_M:
            moved = True
    f3_agents.append({
        "agent_id": aid,
        "bl_location_id": bl_loc,
        "movable": moved,
    })
    if moved:
        n_mov += 1
n_lock = len(f3_agents) - n_mov
print(f"  movable {n_mov} / locked {n_lock} ({n_mov/max(1,len(f3_agents))*100:.1f}% movable)", flush=True)

output = {
    "_meta": {
        "source": "seed_44 (F1/F2) + seed_43 (F3) · 14 days · 4 variants",
        "atlas": "data/lanecove_atlas.json",
        "n_pois_total": len(meta),
        "world_bounds_meters": bounds,
        "movable_threshold_m": MOVABLE_THRESHOLD_M,
    },
    "f1_siphon": {
        "top_pois": f1_top30,
        "top_anchors": f1_top5,
    },
    "f2_friction": {
        "hp_anchors": f2_hp_top30[:5],
        "pf_anchors": f2_pf_top30[:5],
        "overlap_ids": list(overlap_ids),
        "top_pois_hp": f2_hp_top30,
        "top_pois_pf": f2_pf_top30,
    },
    "f3_routine_cliff": {
        "agents": f3_agents,
        "n_movable": n_mov,
        "n_locked": n_lock,
        "threshold_m": MOVABLE_THRESHOLD_M,
    },
}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(output, indent=2))
print(f"\n✓ wrote {OUT}")
print(f"  size: {OUT.stat().st_size / 1024:.1f} KB")
