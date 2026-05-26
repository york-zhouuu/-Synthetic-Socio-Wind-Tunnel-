"""Synthesis hero map · all 3 findings on one Lane Cove map.

Layers (back to front):
  - Lane Cove polygons (warm beige base)
  - 690 routine-locked residents (small grey dots)
  - 310 movable residents (small pink dots)
  - Hyperlocal-push 5 anchors (large orange ring + label)
  - Phone-friction 5 anchors (large deep-pink ring + label)
  - Anchors shared between HP and PF labelled in both

One map. Three findings.
"""
import json
import math
from pathlib import Path
from collections import Counter
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MPolygon, Circle
from matplotlib.collections import PatchCollection

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
OUT = REPO / "data/analysis/2026-05-24_hypothesis_validation/synthesis_hero.png"
ATLAS = REPO / "data/lanecove_atlas.json"
SEED_DIR_43 = REPO / "data/experiments/20260521_185100_publishable_v6_day4to13_fork_seed43_BACKUP_20260522_143245"
SEED_DIR_44 = REPO / "data/experiments/20260522_165045_publishable_v7_day4to13_fork_seed44_BACKUP_20260522_213319_FULL_ALLVARIANTS"


# Palette
BG = "#FCFAF6"
INK = "#1B1F2A"
HP_COLOR = "#D14B12"   # orange — push
HP_DEEP  = "#7A2F0E"
PF_COLOR = "#C8245E"   # deep pink — friction
PF_DEEP  = "#7A0E3F"
MOVABLE  = "#C8245E"   # pink for movable
LOCKED   = "#5F584F"   # warm dark grey
MUTED    = "#6a6358"

BASE_COLOR = {
    "residential": "#EDE3D0", "house": "#EDE3D0", "apartment": "#EDE3D0",
    "commercial": "#E5DCC8", "shop": "#E5DCC8", "office": "#DDD3BD",
    "school": "#D5C8AE",
    "park": "#D4E3C4", "playground": "#D4E3C4", "garden": "#D4E3C4",
    "street": "#F0EBE0",
    "worship": "#E5DCC8",
}

print("Loading atlas...", flush=True)
atlas = json.load(ATLAS.open())
loc_poly, loc_type, loc_centroids, loc_name = {}, {}, {}, {}
for bid, b in atlas["buildings"].items():
    verts = b.get("polygon", {}).get("vertices", [])
    if verts:
        loc_poly[bid] = [(v["x"], v["y"]) for v in verts]
        loc_type[bid] = b.get("building_type", "")
        loc_name[bid] = b.get("name", "") or ""
        xs = [v["x"] for v in verts]; ys = [v["y"] for v in verts]
        loc_centroids[bid] = (sum(xs)/len(xs), sum(ys)/len(ys))
out_areas = atlas.get("outdoor_areas", {})
out_iter = out_areas.items() if isinstance(out_areas, dict) else [(o["id"], o) for o in out_areas]
for oid, o in out_iter:
    verts = o.get("polygon", {}).get("vertices", [])
    if verts:
        loc_poly[oid] = [(v["x"], v["y"]) for v in verts]
        loc_type[oid] = o.get("area_type", "")
        loc_name[oid] = o.get("name", "") or ""
        xs = [v["x"] for v in verts]; ys = [v["y"] for v in verts]
        loc_centroids[oid] = (sum(xs)/len(xs), sum(ys)/len(ys))


# === Load anchor data (seed 44, dwell delta vs baseline) ===
def load_dwell(variant, seed_dir, seed):
    p = seed_dir / f"variant_{variant}" / f"seed_{seed}.json"
    d = json.load(open(p))
    per_day = d.get("run_metrics", {}).get("per_day", [])
    total = Counter()
    for day in per_day:
        for loc, ticks in (day.get("location_dwell_ticks") or {}).items():
            total[loc] += ticks
    return total

print("Loading dwell (seed 44)...", flush=True)
bl_d = load_dwell("baseline", SEED_DIR_44, 44)
hp_d = load_dwell("hyperlocal_push", SEED_DIR_44, 44)
pf_d = load_dwell("phone_friction", SEED_DIR_44, 44)

hp_top = sorted(((loc, hp_d.get(loc,0) - bl_d.get(loc,0)) for loc in (set(bl_d)|set(hp_d))), key=lambda x:-x[1])[:5]
pf_top = sorted(((loc, pf_d.get(loc,0) - bl_d.get(loc,0)) for loc in (set(bl_d)|set(pf_d))), key=lambda x:-x[1])[:5]
print("HP anchors:", [(loc, loc_name.get(loc,'')[:25]) for loc,_ in hp_top])
print("PF anchors:", [(loc, loc_name.get(loc,'')[:25]) for loc,_ in pf_top])


# === Load residents — movability (seed 43) ===
def load_end_positions(variant):
    p = SEED_DIR_43 / f"variant_{variant}" / "seed_43_positions.json"
    d = json.load(p.open())
    last = {}
    for ch in d.get("changes") or []:
        aid = ch.get("agent_id"); loc = ch.get("location_id")
        if aid and loc and loc in loc_centroids:
            last[aid] = loc_centroids[loc]
    return last

print("Loading residents (seed 43)...", flush=True)
bl_pos = load_end_positions("baseline")
hp_pos = load_end_positions("hyperlocal_push")

movable = {}
for aid, (bx, by) in bl_pos.items():
    if aid in hp_pos:
        cx, cy = hp_pos[aid]
        movable[aid] = math.hypot(cx-bx, cy-by) >= 100
    else:
        movable[aid] = False
n_mov = sum(1 for v in movable.values() if v)
n_lock = len(movable) - n_mov
print(f"movable: {n_mov} · locked: {n_lock}")


# === Scene window — center on hot anchor cluster ===
hot_xs = [loc_centroids[loc][0] for loc,_ in (hp_top+pf_top) if loc in loc_centroids]
hot_ys = [loc_centroids[loc][1] for loc,_ in (hp_top+pf_top) if loc in loc_centroids]
hot_cx, hot_cy = sum(hot_xs)/len(hot_xs), sum(hot_ys)/len(hot_ys)
W = 1600
xmin, xmax = hot_cx - W, hot_cx + W
ymin, ymax = hot_cy - W, hot_cy + W


# === Plot ===
fig, ax = plt.subplots(1, 1, figsize=(17, 14))
fig.patch.set_facecolor(BG); ax.set_facecolor(BG)

# Layer 1: base polygons
patches_bg = []; colors_bg = []
for loc, poly in loc_poly.items():
    if loc not in loc_centroids: continue
    cx, cy = loc_centroids[loc]
    if not (xmin <= cx <= xmax and ymin <= cy <= ymax): continue
    patches_bg.append(MPolygon(poly, closed=True))
    colors_bg.append(BASE_COLOR.get(loc_type.get(loc,""), "#E8E0D2"))
pc = PatchCollection(patches_bg, match_original=False)
pc.set_facecolor(colors_bg); pc.set_edgecolor("none"); pc.set_alpha(0.5)
ax.add_collection(pc)

# Layer 2: locked residents (small grey)
for aid, (x, y) in bl_pos.items():
    if not movable.get(aid):
        if xmin <= x <= xmax and ymin <= y <= ymax:
            ax.scatter(x, y, s=10, color=LOCKED, alpha=0.28, edgecolor="none", zorder=3)
# Layer 3: movable residents (pink, slightly bigger)
for aid, (x, y) in bl_pos.items():
    if movable.get(aid):
        if xmin <= x <= xmax and ymin <= y <= ymax:
            ax.scatter(x, y, s=18, color=MOVABLE, alpha=0.62, edgecolor=BG, linewidth=0.4, zorder=4)

# Layer 4: anchors — HP (orange) and PF (deep pink)
# Overlap detection: if anchor in BOTH, show as dual
hp_set = {loc for loc,_ in hp_top}
pf_set = {loc for loc,_ in pf_top}
shared = hp_set & pf_set


def draw_anchor(loc, color_ring, color_text, label_dx, label_dy, eyebrow):
    if loc not in loc_centroids: return
    cx, cy = loc_centroids[loc]
    if not (xmin <= cx <= xmax and ymin <= cy <= ymax): return
    name = loc_name.get(loc, "")[:32] or loc[:32]
    # Big ring
    ax.add_patch(Circle((cx, cy), 130, facecolor='none',
                         edgecolor=color_ring, linewidth=3.0, zorder=5))
    # Small dot center
    ax.add_patch(Circle((cx, cy), 30, facecolor=color_ring, edgecolor=BG,
                         linewidth=1.5, zorder=6))
    # Label
    label = f"{eyebrow}\n{name}"
    ax.annotate(
        label, xy=(cx, cy), xytext=(cx + label_dx, cy + label_dy),
        fontsize=10, color=INK, weight="bold", ha="center", zorder=7,
        arrowprops=dict(arrowstyle="-", color=color_ring, linewidth=1.4),
        bbox=dict(boxstyle="round,pad=0.4", facecolor="white",
                  edgecolor=color_ring, linewidth=1.4),
    )


# Hand-tune label positions to avoid overlap
HP_LABEL_OFFSETS = {
    'plc_sydney_preschool,_lane_cove_campus': (-380, -340),
    'mowbray_road_seg_4': (380, -260),
    'anytime_fitness_australia': (350, 300),
    'area_105': (-380, 280),
    'anglican_church_of_australia_lane_cove': (250, 380),  # may shift if shared
}
PF_LABEL_OFFSETS = {
    'anglican_church_of_australia_lane_cove': (450, 380),  # different offset
    'anytime_fitness_australia': (480, 180),
    'longueville_park': (-350, -360),
    'area_105': (-350, 380),
    'anz': (340, -180),
}

# Draw HP anchors
for loc, delta in hp_top:
    off = HP_LABEL_OFFSETS.get(loc, (300, 300))
    eyebrow = "HP ANCHOR"
    draw_anchor(loc, HP_COLOR, HP_COLOR, off[0], off[1], eyebrow)

# Draw PF anchors (skip if already drawn — for shared, draw a SECOND ring offset)
for loc, delta in pf_top:
    if loc in shared:
        # Draw a second outer ring in PF color
        cx, cy = loc_centroids[loc]
        ax.add_patch(Circle((cx, cy), 170, facecolor='none',
                             edgecolor=PF_COLOR, linewidth=2.5, linestyle=(0,(4,3)), zorder=5))
    else:
        off = PF_LABEL_OFFSETS.get(loc, (-300, -300))
        draw_anchor(loc, PF_COLOR, PF_COLOR, off[0], off[1], "FRICTION ANCHOR")

# Bounds + chrome
ax.set_xlim(xmin, xmax); ax.set_ylim(ymin, ymax); ax.set_aspect("equal")
ax.set_xticks([]); ax.set_yticks([])
for s in ax.spines.values(): s.set_visible(False)

# 500m scale
ax.plot([xmin + 100, xmin + 600], [ymin + 120, ymin + 120], color=INK, linewidth=3)
ax.text(xmin + 350, ymin + 60, "500 m", ha="center", fontsize=11, color=INK)

# Inline legend at bottom right
leg_y0 = ymin + 220
ax.scatter(xmax - 1100, leg_y0, s=18, color=MOVABLE, alpha=0.7,
           edgecolor=BG, linewidth=0.5)
ax.text(xmax - 1050, leg_y0 - 10,
        f"Movable resident · {n_mov} of 1,000 (Finding 3)",
        fontsize=10.5, color=INK, fontweight="bold", va="center")
ax.scatter(xmax - 1100, leg_y0 - 120, s=10, color=LOCKED, alpha=0.5)
ax.text(xmax - 1050, leg_y0 - 130,
        f"Routine-locked · {n_lock} of 1,000",
        fontsize=10.5, color=LOCKED, va="center")
# Anchor key
ax.add_patch(Circle((xmax - 1090, leg_y0 - 260), 36, facecolor='none',
                     edgecolor=HP_COLOR, linewidth=2.5))
ax.text(xmax - 1050, leg_y0 - 270,
        "Hyperlocal-push anchor · top-5 absorbing 80% of redirected dwell (Finding 1)",
        fontsize=10.5, color=HP_COLOR, fontweight="bold", va="center")
ax.add_patch(Circle((xmax - 1090, leg_y0 - 380), 36, facecolor='none',
                     edgecolor=PF_COLOR, linewidth=2.5))
ax.text(xmax - 1050, leg_y0 - 390,
        "Phone-friction anchor · top-5 absorbing 82% — different five (Finding 2)",
        fontsize=10.5, color=PF_COLOR, fontweight="bold", va="center")
# Shared ring example
ax.add_patch(Circle((xmax - 1090, leg_y0 - 500), 36, facecolor='none',
                     edgecolor=HP_COLOR, linewidth=2.0))
ax.add_patch(Circle((xmax - 1090, leg_y0 - 500), 46, facecolor='none',
                     edgecolor=PF_COLOR, linewidth=1.8, linestyle=(0,(4,3))))
ax.text(xmax - 1050, leg_y0 - 510,
        "Shared anchor · this place wins under both interventions",
        fontsize=10.5, color=INK, va="center", style="italic")

# In-map plain-language interpretations of each layer, anchored to the
# top-left of the scene so they live next to the actual data they describe.
INTERP_X = xmin + 100
INTERP_Y0 = ymax - 320
ax.text(INTERP_X, INTERP_Y0,
        "ORANGE RINGS  ·  hyperlocal push",
        fontsize=11, color=HP_COLOR, fontweight="bold")
ax.text(INTERP_X, INTERP_Y0 - 95,
        "→ the algorithm picks distant anchors for you",
        fontsize=10.5, color=INK, style="italic")

ax.text(INTERP_X, INTERP_Y0 - 220,
        "DEEP-PINK RINGS  ·  phone friction",
        fontsize=11, color=PF_COLOR, fontweight="bold")
ax.text(INTERP_X, INTERP_Y0 - 315,
        "→ you find what's nearby on your own",
        fontsize=10.5, color=INK, style="italic")

ax.text(INTERP_X, INTERP_Y0 - 440,
        "GREY DOTS  ·  routine-locked residents",
        fontsize=11, color=LOCKED, fontweight="bold")
ax.text(INTERP_X, INTERP_Y0 - 535,
        "→ neither algorithm nor neighbourhood reaches them;",
        fontsize=10.5, color=INK, style="italic")
ax.text(INTERP_X, INTERP_Y0 - 615,
        "    their routine has already done the choosing",
        fontsize=10.5, color=INK, style="italic")

# Suptitle + footer
fig.text(0.5, 0.965,
         "Synthesis · three findings, one Lane Cove",
         fontsize=24, fontweight="bold", ha="center", va="top", color=INK)
fig.text(0.5, 0.935,
         "The same neighbourhood under three different interventions — what each one writes to, and who responds.",
         fontsize=14, color=MUTED, ha="center", va="top", style="italic")

fig.text(0.5, 0.07,
         "Each intervention writes to a different layer of attention structure:",
         fontsize=14, fontweight="bold", color=INK, ha="center")
fig.text(0.5, 0.045,
         "where attention concentrates (Finding 1 anchors)  ·  through which mechanism (Finding 2 friction picks different anchors)  ·  whom it reaches (Finding 3 movable dots).",
         fontsize=12, color=MUTED, ha="center", style="italic")

plt.subplots_adjust(top=0.91, bottom=0.10, left=0.02, right=0.98)
plt.savefig(OUT, dpi=180, bbox_inches="tight", facecolor=BG)
plt.close()
print(f"\n✓ {OUT} ({OUT.stat().st_size//1024} KB)")
