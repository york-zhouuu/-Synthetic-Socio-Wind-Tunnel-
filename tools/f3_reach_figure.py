"""F3 figure · Routine adherence gates intervention reach.

2-panel paper-style figure:
  Left  : movability rate by routine adherence (low / mid / high)
  Right : movability rate by extraversion (low / mid / high) — null result
"""
import json
from pathlib import Path
import matplotlib.pyplot as plt

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
DATA = REPO / "data/analysis/2026-05-24_hypothesis_validation/N4_movable_profile/n4_movable_profile.json"
OUT = REPO / "data/analysis/2026-05-24_hypothesis_validation/F3_reach_figure.png"

data = json.loads(DATA.read_text())

# Palette (v7)
BG, INK, INK_SOFT = "#FCFAF6", "#1B1F2A", "#3a3a3a"
PINK, PINK_DEEP = "#FF4D8F", "#C8245E"
GREY_WARM, GREY_DEEP, MUTED = "#9E988C", "#5F584F", "#6a6358"

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

fig, (ax_l, ax_r) = plt.subplots(1, 2, figsize=(12.5, 5.0),
                                  gridspec_kw={"wspace": 0.30})

# ====== LEFT: routine adherence (strongest predictor) ======
routine_rows = data["by_routine_adherence"]
# Display order: low, mid, high
order_r = ["low", "mid", "high"]
def label_match(rows, key):
    for r in rows:
        if key in r["cat"]:
            return r
    return None
ordered_r = [label_match(routine_rows, k) for k in order_r]

labels_r = ["Low\nroutine adherence", "Mid", "High\nroutine adherence"]
rates_r = [r["rate"] * 100 for r in ordered_r]
totals_r = [r["total"] for r in ordered_r]
colors_r = [PINK_DEEP, GREY_WARM, GREY_DEEP]
xs = list(range(3))

bars = ax_l.bar(xs, rates_r, color=colors_r, edgecolor=BG, linewidth=0.7,
                 alpha=0.95, width=0.6)

for i, (rate, n) in enumerate(zip(rates_r, totals_r)):
    ax_l.text(i, rate + 1.5, f"{rate:.1f}%", ha="center",
               fontsize=12, fontweight="bold", color=colors_r[i])
    ax_l.text(i, rate + 5.0, f"n={n:,d}", ha="center",
               fontsize=9, color=MUTED, style="italic")

# Population-wide reference (29.35%)
pop_rate = data["movable_rate"] * 100
ax_l.axhline(pop_rate, color=INK_SOFT, linestyle="--", linewidth=1.0, alpha=0.7)
ax_l.text(2.4, pop_rate + 0.5, f"population mean {pop_rate:.1f}%",
           color=INK_SOFT, fontsize=8.5, ha="right", style="italic")

# Red dashed cliff-trend line connecting bar tops to show the steep cascade
import numpy as np
xs_arr = np.array(xs)
rates_arr = np.array(rates_r)
ax_l.plot(xs_arr, rates_arr, color=PINK_DEEP, linestyle="--", linewidth=2.0,
           alpha=0.75, zorder=5, marker="v", markersize=10,
           markerfacecolor=PINK_DEEP, markeredgecolor=BG)
# "STEEP CLIFF — 3.1× spread" annotation
ax_l.text(1.0, 52, "↓  steep cliff  ·  3.1× spread",
           fontsize=11, color=PINK_DEEP, fontweight="bold", ha="center",
           bbox=dict(boxstyle="round,pad=0.4", fc=BG, ec=PINK_DEEP, lw=1.2))

ax_l.set_xticks(xs)
ax_l.set_xticklabels(labels_r, fontsize=10, color=INK)
ax_l.set_ylim(0, 56)
ax_l.set_ylabel("Share of residents who relocate ≥100 m  under intervention  (%)")
ax_l.set_title(
    "A · Routine adherence gates reach (3.1× spread)",
    loc="left", fontweight="bold", pad=12, color=INK,
)

# ====== RIGHT: extraversion (null result) ======
extra_rows = data["by_extraversion"]
ordered_e = [label_match(extra_rows, k) for k in order_r]
labels_e = ["Low\nextraversion", "Mid", "High\nextraversion"]
rates_e = [r["rate"] * 100 for r in ordered_e]
totals_e = [r["total"] for r in ordered_e]

# All grey — null result
colors_e = [GREY_WARM] * 3
bars2 = ax_r.bar(xs, rates_e, color=colors_e, edgecolor=BG, linewidth=0.7,
                  alpha=0.85, width=0.6)

for i, (rate, n) in enumerate(zip(rates_e, totals_e)):
    ax_r.text(i, rate + 1.5, f"{rate:.1f}%", ha="center",
               fontsize=12, fontweight="bold", color=GREY_DEEP)
    ax_r.text(i, rate + 5.0, f"n={n:,d}", ha="center",
               fontsize=9, color=MUTED, style="italic")

ax_r.axhline(pop_rate, color=INK_SOFT, linestyle="--", linewidth=1.0, alpha=0.7)
ax_r.text(2.4, pop_rate + 0.5, f"population mean {pop_rate:.1f}%",
           color=INK_SOFT, fontsize=8.5, ha="right", style="italic")

# Grey horizontal trend line — emphasises FLATNESS
rates_e_arr = np.array(rates_e)
ax_r.plot(xs_arr, rates_e_arr, color=GREY_DEEP, linestyle="--", linewidth=2.0,
           alpha=0.7, zorder=5, marker="s", markersize=9,
           markerfacecolor=GREY_DEEP, markeredgecolor=BG)
# "FLAT — no slope" annotation
ax_r.text(1.0, 52, "→  flat  ·  1.13× spread",
           ha="center", fontsize=11, color=GREY_DEEP, fontweight="bold",
           bbox=dict(boxstyle="round,pad=0.4", fc=BG, ec=GREY_DEEP, lw=1.2))

ax_r.set_xticks(xs)
ax_r.set_xticklabels(labels_e, fontsize=10, color=INK)
ax_r.set_ylim(0, 56)
ax_r.set_ylabel("Share of residents who relocate ≥100 m  under intervention  (%)")
ax_r.set_title(
    "B · Extraversion does not — same effect for income, gender, household",
    loc="left", fontweight="bold", pad=12, color=INK,
)

plt.suptitle(
    "Finding 3 · Routine adherence — not personality — gates whether a resident responds to an intervention at all",
    fontsize=11.5, fontweight="bold", y=1.02, color=INK,
)

plt.tight_layout()
plt.savefig(OUT, dpi=200, bbox_inches="tight", facecolor=BG)
plt.close()
print(f"✓ {OUT} ({OUT.stat().st_size // 1024} KB)")
