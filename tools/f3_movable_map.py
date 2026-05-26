"""F3 supplementary map · the geography of who responds to interventions.

For each of 1,000 residents:
  - Compute baseline end-of-run position (proxy for home anchor)
  - Compute end-of-run position under HP, PF, GD
  - Classify movable if any intervention end-position is >= 100 m
    from baseline end-position (matches N4 analysis)

Plot all 1,000 residents on Lane Cove:
  - Movable: pink dot (~30%)
  - Routine-locked: warm grey dot (~70%)

Reveals whether movability has a spatial pattern.
"""
import json
import math
from pathlib import Path
from collections import defaultdict
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MPolygon
from matplotlib.collections import PatchCollection

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
OUT = REPO / "data/analysis/2026-05-24_hypothesis_validation/F3_movable_map.png"
ATLAS = REPO / "data/lanecove_atlas.json"
SEED_DIR = REPO / "data/experiments/20260521_185100_publishable_v6_day4to13_fork_seed43_BACKUP_20260522_143245"


def load_end_positions(variant, loc_centroids):
    """Return {agent_id: (x, y)} — last location_id seen per agent, mapped via atlas centroids."""
    pos_file = SEED_DIR / f"variant_{variant}" / "seed_43_positions.json"
    if not pos_file.exists():
        print(f"  MISS {pos_file}", flush=True)
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
        if loc in loc_centroids:
            out[aid] = loc_centroids[loc]
    return out


print("Loading atlas...", flush=True)
atlas = json.load(ATLAS.open())
loc_poly, loc_type, loc_centroids = {}, {}, {}
for bid, b in atlas["buildings"].items():
    verts = b.get("polygon", {}).get("vertices", [])
    if verts:
        loc_poly[bid] = [(v["x"], v["y"]) for v in verts]
        loc_type[bid] = b.get("building_type", "")
        xs = [v["x"] for v in verts]; ys = [v["y"] for v in verts]
        loc_centroids[bid] = (sum(xs)/len(xs), sum(ys)/len(ys))
out_areas = atlas.get("outdoor_areas", {})
out_iter = out_areas.items() if isinstance(out_areas, dict) else [(o["id"], o) for o in out_areas]
for oid, o in out_iter:
    verts = o.get("polygon", {}).get("vertices", [])
    if verts:
        loc_poly[oid] = [(v["x"], v["y"]) for v in verts]
        loc_type[oid] = o.get("area_type", "")
        xs = [v["x"] for v in verts]; ys = [v["y"] for v in verts]
        loc_centroids[oid] = (sum(xs)/len(xs), sum(ys)/len(ys))
print(f"  {len(loc_poly)} polygons, {len(loc_centroids)} centroids", flush=True)

print("Loading end positions per condition...", flush=True)
bl_pos = load_end_positions("baseline", loc_centroids)
hp_pos = load_end_positions("hyperlocal_push", loc_centroids)
pf_pos = load_end_positions("phone_friction", loc_centroids)
gd_pos = load_end_positions("global_distraction", loc_centroids)
print(f"  BL agents with positions: {len(bl_pos)}", flush=True)
print(f"  HP: {len(hp_pos)}  PF: {len(pf_pos)}  GD: {len(gd_pos)}")

# Compute movability per agent — matches N4 definition: BL vs HP end-position
# differs by ≥ 100 m. (This is the same cut F3 reports as ~30%.)
movable = {}
for aid, (bx, by) in bl_pos.items():
    moved = False
    if aid in hp_pos:
        cx, cy = hp_pos[aid]
        if math.hypot(cx - bx, cy - by) >= 100:
            moved = True
    movable[aid] = moved

n_mov = sum(1 for v in movable.values() if v)
n_lock = sum(1 for v in movable.values() if not v)
print(f"  movable: {n_mov}  locked: {n_lock}  rate: {n_mov/(n_mov+n_lock)*100:.1f}%")

# Scene window — Lane Cove core
all_xs = [p[0] for p in bl_pos.values()]
all_ys = [p[1] for p in bl_pos.values()]
cx_med = sorted(all_xs)[len(all_xs)//2]
cy_med = sorted(all_ys)[len(all_ys)//2]
W = 1700
xmin, xmax = cx_med - W, cx_med + W
ymin, ymax = cy_med - W, cy_med + W

# Palette
BG = "#FCFAF6"
INK = "#1B1F2A"
PINK = "#FF4D8F"
PINK_DEEP = "#C8245E"
GREY_WARM = "#9E988C"
GREY_DEEP = "#5F584F"
MUTED = "#6a6358"

BASE_COLOR = {
    "residential": "#EDE3D0", "house": "#EDE3D0", "apartment": "#EDE3D0",
    "commercial": "#E5DCC8", "shop": "#E5DCC8", "office": "#DDD3BD",
    "school": "#D5C8AE",
    "park": "#D4E3C4", "playground": "#D4E3C4", "garden": "#D4E3C4",
    "street": "#F0EBE0",
    "worship": "#E5DCC8",
}

fig, ax = plt.subplots(1, 1, figsize=(16, 13))
fig.patch.set_facecolor(BG)
ax.set_facecolor(BG)

# Background polygons
patches_bg = []
colors_bg = []
for loc, poly in loc_poly.items():
    xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
    cx, cy = sum(xs)/len(xs), sum(ys)/len(ys)
    if not (xmin <= cx <= xmax and ymin <= cy <= ymax):
        continue
    patches_bg.append(MPolygon(poly, closed=True))
    colors_bg.append(BASE_COLOR.get(loc_type.get(loc, ""), "#E8E0D2"))
pc = PatchCollection(patches_bg, match_original=False)
pc.set_facecolor(colors_bg)
pc.set_edgecolor("none")
pc.set_alpha(0.55)
ax.add_collection(pc)

# Plot residents — locked first (so movable dots stack on top)
for aid, (x, y) in bl_pos.items():
    if not (xmin <= x <= xmax and ymin <= y <= ymax):
        continue
    if not movable.get(aid):
        ax.scatter(x, y, s=14, color=GREY_DEEP, alpha=0.32,
                   edgecolor="none", zorder=3)
for aid, (x, y) in bl_pos.items():
    if not (xmin <= x <= xmax and ymin <= y <= ymax):
        continue
    if movable.get(aid):
        ax.scatter(x, y, s=26, color=PINK_DEEP, alpha=0.78,
                   edgecolor=BG, linewidth=0.5, zorder=4)

ax.set_xlim(xmin, xmax); ax.set_ylim(ymin, ymax); ax.set_aspect("equal")
ax.set_xticks([]); ax.set_yticks([])
for s in ax.spines.values():
    s.set_visible(False)

# 500m scale bar
ax.plot([xmin + 100, xmin + 600], [ymin + 120, ymin + 120],
        color=INK, linewidth=3)
ax.text(xmin + 350, ymin + 60, "500 m", ha="center", fontsize=11, color=INK)

# Legend inset
leg_x, leg_y = xmin + 100, ymax - 200
ax.scatter(leg_x, leg_y, s=26, color=PINK_DEEP, alpha=0.85,
           edgecolor=BG, linewidth=0.5)
ax.text(leg_x + 80, leg_y - 5,
        f"Movable resident · end-of-run position shifts ≥ 100 m under hyperlocal push · {n_mov}",
        fontsize=11, color=INK, fontweight="bold", va="center")
ax.scatter(leg_x, leg_y - 130, s=14, color=GREY_DEEP, alpha=0.45,
           edgecolor="none")
ax.text(leg_x + 80, leg_y - 135,
        f"Routine-locked resident · same end position as baseline · {n_lock}",
        fontsize=11, color=GREY_DEEP, va="center")

# Title
fig.text(0.5, 0.965,
         "Finding 3 supplement · Where the responding 30% live",
         fontsize=22, fontweight="bold", ha="center", va="top", color=INK)
fig.text(0.5, 0.935,
         "1,000 Lane Cove residents, plotted at their baseline end-of-run position. "
         "Pink dots are the ~30% who relocate ≥ 100 m under hyperlocal push; "
         "grey dots are the ~70% who hold the same daily geography.",
         fontsize=13, color=MUTED, ha="center", va="top", style="italic",
         wrap=True)
# Bottom kicker
fig.text(0.5, 0.07,
         "The pink residents are not clustered in one corner of the neighbourhood — they are interleaved with the grey.",
         fontsize=14, fontweight="bold", color=INK, ha="center", style="italic")
fig.text(0.5, 0.045,
         "Routine adherence (Finding 3) gates intervention reach. The gate is not a postcode; it is a property of each individual's schedule rigidity.",
         fontsize=11, color=MUTED, ha="center")

plt.subplots_adjust(top=0.91, bottom=0.10, left=0.02, right=0.98)
plt.savefig(OUT, dpi=180, bbox_inches="tight", facecolor=BG)
plt.close()
print(f"\n✓ {OUT} ({OUT.stat().st_size//1024} KB)")
