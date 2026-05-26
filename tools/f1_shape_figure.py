"""F1 figure · 2-panel: per-agent distribution + per-building-type notice rate.

Palette matches v7 report (matches f1_25d_donut.svg + poster_map_baseline.svg):
  BG cream, ink #1B1F2A, pink #FF4D8F / deep #C8245E, warm grey #9E988C.
"""
import json
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
OUT_DIR = REPO / "data/analysis/2026-05-24_hypothesis_validation/F1_shape"
data = json.load(open(OUT_DIR / "f1_shape_baseline.json"))

# Palette (mirrors v7 report)
BG = "#FCFAF6"
INK = "#1B1F2A"
INK_SOFT = "#3a3a3a"
PINK = "#FF4D8F"
PINK_DEEP = "#C8245E"
GREY_WARM = "#9E988C"
GREY_DEEP = "#5F584F"
MUTED = "#6a6358"

# Paper-style typography
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

fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), gridspec_kw={"width_ratios": [1, 1]})

# --- LEFT: per-agent histogram ---
ax = axes[0]
agent_rates = [a["rate"] * 100 for a in data["all_agent_rates"]]
import numpy as np
bins = np.arange(0, 62, 2)
counts, edges, patches = ax.hist(agent_rates, bins=bins, color=GREY_WARM,
                                  edgecolor=BG, linewidth=0.6, alpha=0.95)

# Annotate median (pink to anchor it in the data theme)
median_v = data["agent_summary"]["median"] * 100
mean_v = data["agent_summary"]["mean"] * 100
ax.axvline(median_v, color=PINK_DEEP, linestyle="--", linewidth=1.6, alpha=0.95)
ax.text(median_v + 0.6, ax.get_ylim()[1] * 0.92,
        f"median {median_v:.1f}%",
        color=PINK_DEEP, fontsize=9, fontweight="bold")

# Shade tail buckets: deep blindness (ink-soft), high awareness (pink-soft)
ax.axvspan(0, 2, color=INK, alpha=0.10)
ax.text(1, ax.get_ylim()[1] * 0.55, "deep blindness\n<2%\n(2.5% of pop)",
        color=INK_SOFT, fontsize=8, ha="center", style="italic")
ax.axvspan(30, 62, color=PINK, alpha=0.10)
ax.text(45, ax.get_ylim()[1] * 0.55, "high awareness\n>30%\n(1.0% of pop)",
        color=PINK_DEEP, fontsize=8, ha="center", style="italic")

ax.set_xlim(0, 62)
ax.set_xlabel("Individual notice rate (% of physical co-presences actually noticed)",
              color=INK_SOFT)
ax.set_ylabel("Number of agents (n=1,772)", color=INK_SOFT)
ax.set_title("A · Individual axis — most people are 5–15% blind, 70% of the time",
             loc="left", fontweight="bold", pad=10, color=INK)
ax.text(30, ax.get_ylim()[1] * 0.92,
        "Mean 9.9%  ·  Stdev 5.1pp  ·  Range 0–60%",
        fontsize=8, color=MUTED, style="italic")

# --- RIGHT: by-building-type bar chart ---
ax = axes[1]
btypes = data["location_by_building_type"]
btypes_sorted = sorted(btypes, key=lambda x: x["rate"])
labels = [b["type"] for b in btypes_sorted]
rates = [b["rate"] * 100 for b in btypes_sorted]
n_locs = [b["n_locs"] for b in btypes_sorted]

# Color: residential (highest, awareness island) + street (lowest, canyon)
# both highlighted in pink to tie to the data theme; everything else warm grey.
def _bar_color(label):
    if label == "residential":
        return PINK
    if label == "street":
        return PINK_DEEP
    return GREY_WARM

def _label_weight(label):
    return "bold" if label in ("residential", "street") else "normal"

def _label_color(label):
    if label == "residential":
        return PINK_DEEP
    if label == "street":
        return PINK_DEEP
    return INK_SOFT

colors = [_bar_color(l) for l in labels]
bars = ax.barh(range(len(labels)), rates, color=colors,
               edgecolor=BG, linewidth=0.6, alpha=0.95)

# Reference vertical for population mean (9.5%) — ink, dotted
ax.axvline(9.5, color=INK_SOFT, linestyle=":", linewidth=1.1, alpha=0.75)
ax.text(9.7, len(labels) - 0.5, "population mean 9.5%",
        color=INK_SOFT, fontsize=8, style="italic")

# Annotate each bar with rate + n_locs
for i, (r, n, b) in enumerate(zip(rates, n_locs, btypes_sorted)):
    ax.text(r + 0.3, i, f"{r:.1f}%", va="center", fontsize=8.5,
            color=_label_color(labels[i]),
            fontweight=_label_weight(labels[i]))
    ax.text(-0.7, i, f"n={n}", va="center", ha="right", fontsize=7.5, color=MUTED)

ax.set_yticks(range(len(labels)))
ax.set_yticklabels(labels, fontsize=9, color=INK)
ax.set_xlim(-3, 25)
ax.set_xlabel("Notice rate at this location type (%)", color=INK_SOFT)
ax.set_title("B · Spatial axis — streets are blindness canyons (7.1%), homes are awareness islands (19.4%)",
             loc="left", fontweight="bold", pad=10, color=INK)

plt.suptitle("Figure 1 · The shape of default blindness · Lane Cove baseline (no app, 1000 agents × 14 days × 2 seeds)",
             fontsize=11, fontweight="bold", y=1.02, color=INK)

plt.tight_layout()
out = OUT_DIR / "f1_shape_figure.png"
plt.savefig(out, dpi=200, bbox_inches="tight", facecolor=BG)
plt.close()
print(f"✓ {out} ({out.stat().st_size//1024} KB)")
