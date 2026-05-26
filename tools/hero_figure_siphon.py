"""Hero figure: Lane Cove 虹吸地图 — HP 让 5 个 anchor 暴涨 / 1500+ residential 冷却

Layout: 2 panels side-by-side
- Panel A: BL Lane Cove (subdued, baseline activity)
- Panel B: HP Lane Cove (PLC + 4 anchor 大红圆圈,1500+ residential 灰暗)
- Top callouts: top1 PLC +56× / top5 dwell share 80%

Reads per-POI dwell from seed_N.json run_metrics.per_day.location_dwell_ticks
+ atlas centroids for plotting
"""
import json
import math
from pathlib import Path
from collections import Counter
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MPolygon, Circle
from matplotlib.collections import PatchCollection

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
OUT = REPO / "data/analysis/2026-05-24_hypothesis_validation/HERO_FIGURE"
OUT.mkdir(parents=True, exist_ok=True)
ATLAS = REPO / "data/lanecove_atlas.json"

# Use seed 44 (main reference, full data)
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
loc_xy = {}
loc_poly = {}
loc_type = {}
loc_name = {}
for bid, b in atlas["buildings"].items():
    verts = b.get("polygon", {}).get("vertices", [])
    if verts:
        xs = [v["x"] for v in verts]; ys = [v["y"] for v in verts]
        loc_xy[bid] = (sum(xs)/len(xs), sum(ys)/len(ys))
        loc_poly[bid] = [(v["x"], v["y"]) for v in verts]
        loc_type[bid] = b.get("building_type", "")
        loc_name[bid] = b.get("name", "") or ""
out = atlas.get("outdoor_areas", {})
out_iter = out.items() if isinstance(out, dict) else [(o["id"], o) for o in out]
for oid, o in out_iter:
    verts = o.get("polygon", {}).get("vertices", [])
    if verts:
        xs = [v["x"] for v in verts]; ys = [v["y"] for v in verts]
        loc_xy[oid] = (sum(xs)/len(xs), sum(ys)/len(ys))
        loc_poly[oid] = [(v["x"], v["y"]) for v in verts]
        loc_type[oid] = o.get("area_type", "")
        loc_name[oid] = o.get("name", "") or ""

print(f"  {len(loc_poly)} location polygons", flush=True)

print("Loading dwell ticks...", flush=True)
bl_dwell = load_dwell("baseline")
hp_dwell = load_dwell("hyperlocal_push")
print(f"  BL: {len(bl_dwell)} POIs, total {sum(bl_dwell.values())} ticks", flush=True)
print(f"  HP: {len(hp_dwell)} POIs, total {sum(hp_dwell.values())} ticks", flush=True)

# Compute deltas
all_locs = set(bl_dwell) | set(hp_dwell)
deltas = {loc: hp_dwell.get(loc, 0) - bl_dwell.get(loc, 0) for loc in all_locs}

# Top hot
top_hot = sorted(deltas.items(), key=lambda x: -x[1])[:8]
print("\n  Top hot POIs (HP - BL):")
for loc, delta in top_hot:
    print(f"    {loc[:40]:40s} +{delta:7d}  ({loc_name.get(loc,'')[:30]})")

# Compute scene bounds (Lane Cove core area, ~2km × 2km around the hot anchor cluster)
# Use ALL POIs that have non-zero dwell to find the relevant area
active_xs = [loc_xy[loc][0] for loc in all_locs if loc in loc_xy]
active_ys = [loc_xy[loc][1] for loc in all_locs if loc in loc_xy]
center_x = sum(active_xs) / len(active_xs)
center_y = sum(active_ys) / len(active_ys)
print(f"  active centroid: ({center_x:.0f}, {center_y:.0f})", flush=True)

# Zoom to a tight window around the hot anchors
hot_xs = [loc_xy[loc][0] for loc, _ in top_hot if loc in loc_xy]
hot_ys = [loc_xy[loc][1] for loc, _ in top_hot if loc in loc_xy]
hot_cx = sum(hot_xs) / len(hot_xs); hot_cy = sum(hot_ys) / len(hot_ys)
W = 1500  # 1.5km on each side
xmin, xmax = hot_cx - W, hot_cx + W
ymin, ymax = hot_cy - W, hot_cy + W
print(f"  scene window: x [{xmin:.0f}, {xmax:.0f}], y [{ymin:.0f}, {ymax:.0f}]", flush=True)


# Type-based base colors
BASE_COLOR = {
    "residential": "#D4C5A8",  # warm beige
    "house": "#D4C5A8",
    "apartment": "#D4C5A8",
    "commercial": "#C7BAA8",
    "shop": "#C7BAA8",
    "office": "#B8AC95",
    "school": "#A89880",
    "park": "#B8C9A9",
    "playground": "#B8C9A9",
    "garden": "#B8C9A9",
    "street": "#E8E3DC",
    "worship": "#C7BAA8",
    "entertainment": "#C7BAA8",
    "restaurant": "#C7BAA8",
}


def color_for(loc, dwell_value, max_dwell, mode="bl"):
    """mode='bl' use neutral. mode='hp' overlay heat where dwell > BL."""
    base = BASE_COLOR.get(loc_type.get(loc, ""), "#D4C5A8")
    return base


def paint_panel(ax, dwell, title, top_hot_locs=None, show_callouts=True):
    """Draw lane cove polygons coloured by dwell intensity."""
    # First — all polygons in the window, low-saturation base
    patches_bg = []
    for loc, poly in loc_poly.items():
        if loc not in loc_xy:
            continue
        cx, cy = loc_xy[loc]
        if not (xmin <= cx <= xmax and ymin <= cy <= ymax):
            continue
        patches_bg.append((loc, MPolygon(poly, closed=True)))
    # Pure type-base
    pc_bg = PatchCollection([p for _, p in patches_bg], match_original=False)
    colors_bg = []
    for loc, _ in patches_bg:
        d = dwell.get(loc, 0)
        if d == 0:
            colors_bg.append("#F4EFE5")  # pale background for inactive
        else:
            # Heat based on this variant's dwell quantile
            colors_bg.append(BASE_COLOR.get(loc_type.get(loc, ""), "#D4C5A8"))
    pc_bg.set_facecolor(colors_bg)
    pc_bg.set_edgecolor("none")
    ax.add_collection(pc_bg)

    # Now: overlay HOT spots (top hot POIs in this variant)
    top_in_panel = sorted(dwell.items(), key=lambda x: -x[1])[:30]
    for loc, val in top_in_panel:
        if loc not in loc_xy:
            continue
        cx, cy = loc_xy[loc]
        if not (xmin <= cx <= xmax and ymin <= cy <= ymax):
            continue
        # Heat circle size scales with dwell intensity (log)
        max_d = max(dwell.values()) if dwell else 1
        intensity = val / max_d
        radius = 25 + intensity * 250  # 25-275m visual radius
        alpha = 0.18 + intensity * 0.55
        circle = Circle((cx, cy), radius, facecolor='#D14B12', edgecolor='none', alpha=alpha)
        ax.add_patch(circle)

    # If panel B (HP), specifically label top hot anchors with arrows
    if top_hot_locs and show_callouts:
        for loc, delta in top_hot_locs[:5]:
            if loc not in loc_xy:
                continue
            cx, cy = loc_xy[loc]
            if not (xmin <= cx <= xmax and ymin <= cy <= ymax):
                continue
            name = loc_name.get(loc, loc)[:30] or loc[:30]
            ratio = (hp_dwell.get(loc, 0) + 1) / (bl_dwell.get(loc, 0) + 1)
            label = f"{name}\n+{delta//1000}K · {ratio:.0f}×"
            # Draw red ring at the anchor
            ring = Circle((cx, cy), 80, facecolor='none', edgecolor='#7A2F0E', linewidth=2.5)
            ax.add_patch(ring)
            # Smart label placement based on quadrant from center
            dx = cx - hot_cx
            dy = cy - hot_cy
            # Bigger offset reduces overlap of label box with the giant
            # PLC Preschool circle and other dense anchors.
            label_off_x = 340 if dx >= 0 else -340
            label_off_y = 280 if dy >= 0 else -280
            ha = "left" if dx >= 0 else "right"
            ax.annotate(
                label,
                xy=(cx, cy), xytext=(cx + label_off_x, cy + label_off_y),
                fontsize=9, color="#2A1F18", weight="bold", ha=ha,
                arrowprops=dict(arrowstyle="-", color="#7A2F0E", linewidth=1.2),
                bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="#7A2F0E", linewidth=1)
            )

    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ax.set_aspect('equal')
    # title intentionally omitted — descriptive header is in fig.text above
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)

    # Scale bar (500m)
    sb_x = xmin + 80
    sb_y = ymin + 100
    ax.plot([sb_x, sb_x + 500], [sb_y, sb_y], color="#2A1F18", linewidth=3)
    ax.text(sb_x + 250, sb_y - 80, "500 m", ha="center", fontsize=10, color="#2A1F18")


# Plot
fig, axes = plt.subplots(1, 2, figsize=(20, 11))
plt.style.use("default")

# Panel A: baseline
paint_panel(axes[0], bl_dwell, "Baseline · no push", show_callouts=False)

# Panel B: hyperlocal_push, with anchors highlighted
paint_panel(axes[1], hp_dwell, "Hyperlocal push · 14 days later", top_hot_locs=top_hot)

# Big top callout banners — descriptive, no insider abbreviations.
# Reader-friendly: anyone walking up cold should know what each panel shows.
fig.text(0.27, 0.965, "BEFORE",
         fontsize=22, fontweight="bold", color="#5A4A3A",
         ha="center", va="top")
fig.text(0.27, 0.935, "no app · 14-day baseline",
         fontsize=14, color="#6A5A4A", ha="center", va="top", style='italic')
fig.text(0.27, 0.910, "1,000 residents in Lane Cove · dwell distributed across ~2,400 places",
         fontsize=11, color="#6A5A4A", ha="center", va="top")

fig.text(0.73, 0.965, "AFTER",
         fontsize=22, fontweight="bold", color="#D14B12",
         ha="center", va="top")
fig.text(0.73, 0.935, '14 days of "hyperlocal" push  ·  30 pushes per resident',
         fontsize=14, color="#7A2F0E", ha="center", va="top", style='italic')
fig.text(0.73, 0.910, "same 1,000 residents · 1 preschool absorbs 62% of all redistributed dwell · 1,556 places lose dwell",
         fontsize=11, color="#7A2F0E", ha="center", va="top", weight="bold")

# Bottom summary band
plt.subplots_adjust(top=0.85, bottom=0.10, left=0.02, right=0.98, wspace=0.04)

# Bottom kicker
fig.text(0.5, 0.06, '"Hyperlocal" push, in practice, is centralising.',
         fontsize=18, fontweight="bold", color="#2A1F18", ha="center", style="italic")
fig.text(0.5, 0.03, '249 POIs gain dwell · 1,556 POIs lose it · ratio 1 : 6 · top-5 anchors absorb 80% of the gain',
         fontsize=12, color="#5A4A3A", ha="center")

out_path = OUT / "siphon_hero_figure.png"
plt.savefig(out_path, dpi=200, bbox_inches="tight", facecolor="white")
plt.close()
print(f"\n✓ {out_path} ({out_path.stat().st_size//1024} KB)")

# Also write a simplified version without callouts for embed
fig2, axes2 = plt.subplots(1, 2, figsize=(16, 9))
paint_panel(axes2[0], bl_dwell, "Before · baseline", show_callouts=False)
paint_panel(axes2[1], hp_dwell, "After · hyperlocal push", top_hot_locs=top_hot)
plt.subplots_adjust(wspace=0.04)
out2 = OUT / "siphon_hero_compact.png"
plt.savefig(out2, dpi=160, bbox_inches="tight", facecolor="white")
plt.close()
print(f"✓ {out2} ({out2.stat().st_size//1024} KB)")
