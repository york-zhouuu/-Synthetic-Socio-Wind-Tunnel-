"""F2 figure · the 24-hour clock of nearby blindness.

Hero line chart (single panel, paper-style):
  - X axis: 24 hours (0–23h)
  - Y axis: notice rate (%)
  - Main line: overall hourly notice rate
  - Reference: population mean dashed
  - Stratified lines: street vs residential (the two F1 extremes)
  - Annotations on peak hour (09h) + trough hour (21h)
  - Sparse-data hours (n < 200) rendered translucently
  - Bottom strip: encounter volume per hour so reader sees the sampling weight
"""
import json
import math
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
DATA = REPO / "data/analysis/2026-05-24_hypothesis_validation/F2_chronology/f2_chronology_baseline.json"
OUT = REPO / "data/analysis/2026-05-24_hypothesis_validation/F2_chronology/f2_chronology_figure.png"

data = json.loads(DATA.read_text())
hourly = data["hourly"]
matrix = data["hourly_by_building_type"]

# Palette (v7)
BG = "#FCFAF6"
INK = "#1B1F2A"
INK_SOFT = "#3a3a3a"
PINK = "#FF4D8F"
PINK_DEEP = "#C8245E"
GREY_WARM = "#9E988C"
GREY_DEEP = "#5F584F"
MUTED = "#6a6358"
STREET_COL = "#5F584F"
RES_COL = PINK

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.size": 9.5,
    "axes.titlesize": 11,
    "axes.labelsize": 9.5,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.edgecolor": INK_SOFT,
    "axes.linewidth": 0.7,
    "xtick.color": INK_SOFT,
    "ytick.color": INK_SOFT,
    "axes.facecolor": BG,
    "figure.facecolor": BG,
})

# Build series. Drop sparse hours from rate plot (n < 200), but keep volume row.
hours = list(range(24))
rates_pct = []
encs = []
for h in hours:
    row = hourly[h]
    encs.append(row["enc"])
    if row["enc"] >= 200:
        rates_pct.append(row["rate"] * 100)
    else:
        rates_pct.append(None)

# Stratified by building type
def stratum(type_name):
    out = []
    for h in range(24):
        cell = matrix[type_name][h]
        if cell["enc"] >= 100:
            out.append(cell["rate"] * 100)
        else:
            out.append(None)
    return out

street_pct = stratum("street")
res_pct = stratum("residential")

# Population mean (across 14-day BL)
POP_MEAN = 9.5

# Figure with 2 stacked panels: main rate chart + thin volume strip
fig, (ax, ax_vol) = plt.subplots(
    2, 1, figsize=(13.0, 6.2),
    gridspec_kw={"height_ratios": [4.4, 1.0], "hspace": 0.08},
    sharex=True,
)

# --- main rate chart ---
xs = np.array(hours)

# Background period shading
ax.axvspan(0, 4, color="#3a3a3a", alpha=0.04)    # night
ax.axvspan(7, 9.5, color=PINK, alpha=0.05)       # morning rush window
ax.axvspan(16, 21, color="#3a3a3a", alpha=0.07)  # evening trough zone
# Period labels pinned to TOP of plot (y=20.7) so they don't collide
# with the data line or callout boxes
ax.text(2, 20.7, "NIGHT", color=MUTED, fontsize=8,
        ha="center", fontweight="bold")
ax.text(8.25, 20.7, "MORNING RUSH", color=PINK_DEEP, fontsize=8,
        ha="center", fontweight="bold")
ax.text(18.5, 20.7, "EVENING TROUGH", color=GREY_DEEP, fontsize=8,
        ha="center", fontweight="bold")

# Population mean reference
ax.axhline(POP_MEAN, color=MUTED, linestyle="--", linewidth=1.0, alpha=0.7)
ax.text(23.5, POP_MEAN + 0.25, f"14-day mean  {POP_MEAN}%",
        color=MUTED, fontsize=8.5, ha="right", style="italic")

# Plot stratified building-type lines (back layer, thin)
def plot_series(series, color, label, marker_color, alpha=0.7, lw=1.3, marker_size=12, dash=None):
    masked = [(h, v) for h, v in zip(hours, series) if v is not None]
    if not masked:
        return
    hx, hy = zip(*masked)
    ax.plot(hx, hy, color=color, alpha=alpha, linewidth=lw,
            linestyle=dash if dash else "-", label=label)
    ax.scatter(hx, hy, color=color, s=marker_size, zorder=3, alpha=alpha)

plot_series(street_pct, STREET_COL,
            "Street segments (always near floor)", marker_color=STREET_COL,
            alpha=0.55, lw=1.1, marker_size=8, dash=(0, (4, 2)))
plot_series(res_pct, RES_COL,
            "Residential (awareness islands)", marker_color=RES_COL,
            alpha=0.55, lw=1.1, marker_size=8, dash=(0, (4, 2)))

# Plot overall line (front layer, thick + saturated)
masked = [(h, v) for h, v in zip(hours, rates_pct) if v is not None]
hx, hy = zip(*masked)
ax.plot(hx, hy, color=INK, linewidth=2.4, label="Overall notice rate", zorder=5)
ax.scatter(hx, hy, color=INK, s=24, zorder=6,
           edgecolor=BG, linewidth=0.5)

# Annotations on trough + peak
peak_h = max(hx, key=lambda h: rates_pct[h])
trough_h = min(hx, key=lambda h: rates_pct[h])
peak_v = rates_pct[peak_h]
trough_v = rates_pct[trough_h]

# PEAK annotation: anchored to peak hour (09:00, ~13.3%); label sits to the
# right of the line in the white midday space, well below the period band.
ax.annotate(
    f"PEAK {peak_v:.1f}%\n09:00 · settling into workplaces, schools",
    xy=(peak_h, peak_v), xytext=(11.2, 17.0),
    fontsize=9, color=PINK_DEEP, fontweight="bold",
    arrowprops=dict(arrowstyle="-", color=PINK_DEEP, lw=0.7, alpha=0.7),
    bbox=dict(boxstyle="round,pad=0.5", fc="white", ec=PINK_DEEP,
              alpha=0.97, lw=0.7),
)
# TROUGH annotation: anchored to 21:00 (~6.5%); label sits BELOW the curve
# at lower-middle of plot (away from upper-left legend, away from 22:00 dot).
ax.annotate(
    f"TROUGH {trough_v:.1f}%\n21:00 · walking home, heads down",
    xy=(trough_h, trough_v), xytext=(14.8, 3.5),
    fontsize=9, color=INK, fontweight="bold",
    arrowprops=dict(arrowstyle="-", color=INK, lw=0.7, alpha=0.7),
    bbox=dict(boxstyle="round,pad=0.5", fc="white", ec=INK,
              alpha=0.97, lw=0.7),
)

ax.set_ylim(2, 22.5)
ax.set_xlim(-0.5, 23.5)
ax.set_xticks(range(0, 24, 2))
ax.set_xticklabels([f"{h:02d}:00" for h in range(0, 24, 2)])
ax.set_ylabel("Notice rate (%)", labelpad=8)
ax.set_title(
    "Finding 2 · The clock of nearby blindness — 2× daily oscillation, deepest at 21:00",
    loc="left", fontweight="bold", pad=14, color=INK, fontsize=12,
)

# Legend pinned to UPPER-LEFT (the empty 01–06h sleeping zone) so it stays
# clear of the TROUGH callout in the lower-middle.
leg = ax.legend(loc="upper left", bbox_to_anchor=(0.005, 0.99),
                frameon=True, framealpha=0.95,
                edgecolor=INK_SOFT, fontsize=8.5)
leg.get_frame().set_linewidth(0.5)

# Tag sparse hours
sparse_h = [h for h, v in zip(hours, rates_pct) if v is None]
if sparse_h:
    sparse_ranges = []
    cur_start = sparse_h[0]
    prev = sparse_h[0]
    for h in sparse_h[1:]:
        if h == prev + 1:
            prev = h
        else:
            sparse_ranges.append((cur_start, prev))
            cur_start = h
            prev = h
    sparse_ranges.append((cur_start, prev))
    for s, e in sparse_ranges:
        ax.axvspan(s - 0.5, e + 0.5, color=GREY_WARM, alpha=0.07)
        mid = (s + e) / 2
        # Place "n<200 sleeping" near the mid-y to stay out of the way of
        # both the legend (top-left) and the TROUGH callout (low-middle).
        ax.text(mid, 11.0, "n<200\nsleeping",
                ha="center", fontsize=7.5, color=MUTED, style="italic")

# --- bottom panel: encounter volume per hour ---
ax_vol.bar(hours, encs, color=GREY_WARM, alpha=0.55, edgecolor=BG, linewidth=0.4)
ax_vol.set_ylim(0, max(encs) * 1.18)
ax_vol.set_xlabel("Hour of day  (2 simulated weekdays · Mon + Tue 2026-05-04 / 05)")
ax_vol.set_ylabel("Encounters", fontsize=9, labelpad=8)
ax_vol.set_xticks(range(0, 24, 2))
ax_vol.spines["bottom"].set_color(INK_SOFT)
ax_vol.tick_params(axis="y", labelsize=8)
# Compact y-tick labels (5K, 10K) — leaves room for the ylabel
ax_vol.set_yticks([0, 10000, 20000])
ax_vol.set_yticklabels(["0", "10K", "20K"])

# Top-right label (moved from upper-left so it doesn't visually clash with
# the much larger upper-panel legend stack directly above).
ax_vol.text(0.5, max(encs) * 1.05, f"Total: {sum(encs):,} encounters",
            fontsize=8, color=MUTED, style="italic")

plt.suptitle(
    "How nearby blindness rises and falls across a single Lane Cove day · baseline (no app)",
    fontsize=11.5, fontweight="normal", y=0.99, color=INK,
)
plt.tight_layout()
plt.savefig(OUT, dpi=200, bbox_inches="tight", facecolor=BG)
plt.close()
print(f"✓ {OUT} ({OUT.stat().st_size // 1024} KB)")
