"""F2 figure · 3-panel geographic comparison.

Lane Cove dwell distribution under three conditions side-by-side:
  Before (no app) · After hyperlocal push · After phone friction

Visual thesis: push concentrates onto 5 community anchors; friction
distributes more broadly across the neighbourhood.
"""
import json
from pathlib import Path
from collections import Counter
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MPolygon, Circle
from matplotlib.collections import PatchCollection

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
OUT = REPO / "data/analysis/2026-05-24_hypothesis_validation/F2_3panel_geographic.png"
ATLAS = REPO / "data/lanecove_atlas.json"
SEED_DIR = REPO / "data/experiments/20260522_165045_publishable_v7_day4to13_fork_seed44_BACKUP_20260522_213319_FULL_ALLVARIANTS"


def load_dwell(variant):
    p = SEED_DIR / f"variant_{variant}" / "seed_44.json"
    d = json.load(open(p))
    per_day = d.get("run_metrics", {}).get("per_day", [])
    total = Counter()
    for day in per_day:
        for loc, ticks in (day.get("location_dwell_ticks") or {}).items():
            total[loc] += ticks
    return total


print("Loading atlas...", flush=True)
atlas = json.load(open(ATLAS))
loc_xy, loc_poly, loc_type, loc_name = {}, {}, {}, {}
for bid, b in atlas["buildings"].items():
    verts = b.get("polygon", {}).get("vertices", [])
    if verts:
        xs = [v["x"] for v in verts]; ys = [v["y"] for v in verts]
        loc_xy[bid] = (sum(xs)/len(xs), sum(ys)/len(ys))
        loc_poly[bid] = [(v["x"], v["y"]) for v in verts]
        loc_type[bid] = b.get("building_type", "")
        loc_name[bid] = b.get("name", "") or ""
out_areas = atlas.get("outdoor_areas", {})
out_iter = out_areas.items() if isinstance(out_areas, dict) else [(o["id"], o) for o in out_areas]
for oid, o in out_iter:
    verts = o.get("polygon", {}).get("vertices", [])
    if verts:
        xs = [v["x"] for v in verts]; ys = [v["y"] for v in verts]
        loc_xy[oid] = (sum(xs)/len(xs), sum(ys)/len(ys))
        loc_poly[oid] = [(v["x"], v["y"]) for v in verts]
        loc_type[oid] = o.get("area_type", "")
        loc_name[oid] = o.get("name", "") or ""
print(f"  {len(loc_poly)} polygons", flush=True)

print("Loading dwell...", flush=True)
bl_dwell = load_dwell("baseline")
hp_dwell = load_dwell("hyperlocal_push")
pf_dwell = load_dwell("phone_friction")
print(f"  BL: {sum(bl_dwell.values()):,}, HP: {sum(hp_dwell.values()):,}, PF: {sum(pf_dwell.values()):,}", flush=True)

# Compute deltas
all_locs = set(bl_dwell) | set(hp_dwell) | set(pf_dwell)
hp_deltas = {loc: hp_dwell.get(loc, 0) - bl_dwell.get(loc, 0) for loc in all_locs}
pf_deltas = {loc: pf_dwell.get(loc, 0) - bl_dwell.get(loc, 0) for loc in all_locs}

hp_top = sorted(hp_deltas.items(), key=lambda x: -x[1])[:8]
pf_top = sorted(pf_deltas.items(), key=lambda x: -x[1])[:8]
print("\nHP top hot:")
for loc, d in hp_top[:5]:
    print(f"  +{d:>7d}  {loc_name.get(loc,'')[:30]}")
print("\nPF top hot:")
for loc, d in pf_top[:5]:
    print(f"  +{d:>7d}  {loc_name.get(loc,'')[:30]}")

# Concentration metrics for the caption
def top_n_share_of_gain(deltas, n):
    pos = sorted([d for d in deltas.values() if d > 0], reverse=True)
    return sum(pos[:n]) / sum(pos) if pos else 0

hp_top5_share = top_n_share_of_gain(hp_deltas, 5) * 100
pf_top5_share = top_n_share_of_gain(pf_deltas, 5) * 100
hp_gainers = sum(1 for d in hp_deltas.values() if d > 0)
pf_gainers = sum(1 for d in pf_deltas.values() if d > 0)
print(f"\nHP top-5 absorb {hp_top5_share:.0f}% of all gains  · {hp_gainers} POI gain dwell")
print(f"PF top-5 absorb {pf_top5_share:.0f}% of all gains  · {pf_gainers} POI gain dwell")

# Scene window
hot_xs = [loc_xy[loc][0] for loc, _ in hp_top if loc in loc_xy]
hot_ys = [loc_xy[loc][1] for loc, _ in hp_top if loc in loc_xy]
hot_cx, hot_cy = sum(hot_xs)/len(hot_xs), sum(hot_ys)/len(hot_ys)
W = 1500
xmin, xmax = hot_cx - W, hot_cx + W
ymin, ymax = hot_cy - W, hot_cy + W

BASE_COLOR = {
    "residential": "#D4C5A8", "house": "#D4C5A8", "apartment": "#D4C5A8",
    "commercial": "#C7BAA8", "shop": "#C7BAA8", "office": "#B8AC95",
    "school": "#A89880",
    "park": "#B8C9A9", "playground": "#B8C9A9", "garden": "#B8C9A9",
    "street": "#E8E3DC",
    "worship": "#C7BAA8", "entertainment": "#C7BAA8", "restaurant": "#C7BAA8",
}


def paint_panel(ax, dwell, top_locs=None, show_callouts=False,
                heat_color="#D14B12", ring_color="#7A2F0E"):
    # Background polygons
    patches_bg = []
    for loc, poly in loc_poly.items():
        if loc not in loc_xy: continue
        cx, cy = loc_xy[loc]
        if not (xmin <= cx <= xmax and ymin <= cy <= ymax): continue
        patches_bg.append((loc, MPolygon(poly, closed=True)))
    pc_bg = PatchCollection([p for _, p in patches_bg], match_original=False)
    colors_bg = []
    for loc, _ in patches_bg:
        d = dwell.get(loc, 0)
        colors_bg.append("#F4EFE5" if d == 0
                          else BASE_COLOR.get(loc_type.get(loc, ""), "#D4C5A8"))
    pc_bg.set_facecolor(colors_bg)
    pc_bg.set_edgecolor("none")
    ax.add_collection(pc_bg)

    # Heat overlay (top-30 hottest POIs in this condition)
    top_in_panel = sorted(dwell.items(), key=lambda x: -x[1])[:30]
    max_d = max(dwell.values()) if dwell else 1
    for loc, val in top_in_panel:
        if loc not in loc_xy: continue
        cx, cy = loc_xy[loc]
        if not (xmin <= cx <= xmax and ymin <= cy <= ymax): continue
        intensity = val / max_d
        radius = 25 + intensity * 250
        alpha = 0.18 + intensity * 0.55
        ax.add_patch(Circle((cx, cy), radius, facecolor=heat_color,
                             edgecolor='none', alpha=alpha))

    # Callouts (5 named anchor labels for HP)
    if top_locs and show_callouts:
        for loc, delta in top_locs[:5]:
            if loc not in loc_xy: continue
            cx, cy = loc_xy[loc]
            if not (xmin <= cx <= xmax and ymin <= cy <= ymax): continue
            name = loc_name.get(loc, loc)[:30] or loc[:30]
            label = f"{name}\n+{delta//1000}K"
            ax.add_patch(Circle((cx, cy), 80, facecolor='none',
                                 edgecolor=ring_color, linewidth=2.5))
            dx, dy = cx - hot_cx, cy - hot_cy
            off_x = 340 if dx >= 0 else -340
            off_y = 280 if dy >= 0 else -280
            ha = "left" if dx >= 0 else "right"
            ax.annotate(
                label, xy=(cx, cy), xytext=(cx + off_x, cy + off_y),
                fontsize=8.5, color="#2A1F18", weight="bold", ha=ha,
                arrowprops=dict(arrowstyle="-", color=ring_color, linewidth=1.2),
                bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                          edgecolor=ring_color, linewidth=1),
            )

    ax.set_xlim(xmin, xmax); ax.set_ylim(ymin, ymax); ax.set_aspect('equal')
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values(): s.set_visible(False)

    # 500m scale bar
    sb_x = xmin + 80; sb_y = ymin + 100
    ax.plot([sb_x, sb_x + 500], [sb_y, sb_y], color="#2A1F18", linewidth=3)
    ax.text(sb_x + 250, sb_y - 80, "500 m", ha="center",
            fontsize=10, color="#2A1F18")


fig, axes = plt.subplots(1, 3, figsize=(28, 10))

# Panel A: Before
paint_panel(axes[0], bl_dwell, heat_color="#C8A88C", ring_color="#5A4A3A")
# Panel B: Hyperlocal push (with anchor callouts)
paint_panel(axes[1], hp_dwell, top_locs=hp_top, show_callouts=True,
            heat_color="#D14B12", ring_color="#7A2F0E")
# Panel C: Phone friction (with named callouts so we can see the DIFFERENT anchor set)
paint_panel(axes[2], pf_dwell, top_locs=pf_top, show_callouts=True,
            heat_color="#C8245E", ring_color="#7A0E3F")

# Headers
fig.text(0.18, 0.965, "BEFORE",
         fontsize=22, fontweight="bold", color="#5A4A3A",
         ha="center", va="top")
fig.text(0.18, 0.935, "no app · 14-day baseline",
         fontsize=14, color="#6A5A4A", ha="center", va="top", style='italic')
fig.text(0.18, 0.910, "1,000 residents · dwell distributed across ~2,400 places",
         fontsize=11, color="#6A5A4A", ha="center", va="top")

fig.text(0.50, 0.965, "AFTER · HYPERLOCAL PUSH",
         fontsize=22, fontweight="bold", color="#D14B12",
         ha="center", va="top")
fig.text(0.50, 0.935, "14 days · 30 pushes per resident · recommend nearby place",
         fontsize=14, color="#7A2F0E", ha="center", va="top", style='italic')
fig.text(0.50, 0.910,
         f"top-5 places absorb {hp_top5_share:.0f}% of all dwell gains · {hp_gainers} places gain · 1,556 places lose",
         fontsize=11, color="#7A2F0E", ha="center", va="top", weight="bold")

fig.text(0.82, 0.965, "AFTER · PHONE FRICTION",
         fontsize=22, fontweight="bold", color="#C8245E",
         ha="center", va="top")
fig.text(0.82, 0.935, "14 days · less compelling phone · no recommendation",
         fontsize=14, color="#7A0E3F", ha="center", va="top", style='italic')
fig.text(0.82, 0.910,
         f"top-5 places absorb {pf_top5_share:.0f}% of gains · also concentrates — onto a different five",
         fontsize=11, color="#7A0E3F", ha="center", va="top", weight="bold")

plt.subplots_adjust(top=0.85, bottom=0.10, left=0.01, right=0.99, wspace=0.04)

# Kicker — corrected based on data: BOTH concentrate, but onto different anchor sets
fig.text(0.5, 0.06,
         'Both push and friction concentrate Lane Cove\'s attention onto 5 anchors — but onto two different fives.',
         fontsize=17, fontweight="bold", color="#2A1F18", ha="center", style="italic")
fig.text(0.5, 0.03,
         'Push picks a preschool, gym, road, outdoor area, and church (algorithm criteria).  Friction picks a church, gym, park, outdoor area, and bank (organic routine drift).',
         fontsize=11, color="#5A4A3A", ha="center")

plt.savefig(OUT, dpi=180, bbox_inches="tight", facecolor="white")
plt.close()
print(f"\n✓ {OUT} ({OUT.stat().st_size//1024} KB)")
