"""F3 figure · wide and shallow awareness.

2-panel paper-style figure:

Panel A (left):  pair notice-count distribution — striking 98%/2% gap
                 showing 1-shot recognition dominates.
Panel B (right): per-agent histogram of distinct partners noticed in 2 days
                 — shows the WIDTH of each agent's awareness graph
                 (median ~9 partners), most as singletons.
"""
import json
import math
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np
from collections import Counter

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
DATA = REPO / "data/analysis/2026-05-24_hypothesis_validation/F3_asymmetry/f3_concentration_baseline.json"
OUT = REPO / "data/analysis/2026-05-24_hypothesis_validation/F3_asymmetry/f3_concentration_figure.png"

data = json.loads(DATA.read_text())

# Palette (v7)
BG = "#FCFAF6"
INK = "#1B1F2A"
INK_SOFT = "#3a3a3a"
PINK = "#FF4D8F"
PINK_DEEP = "#C8245E"
GREY_WARM = "#9E988C"
GREY_DEEP = "#5F584F"
MUTED = "#6a6358"

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

fig, (ax_l, ax_r) = plt.subplots(1, 2, figsize=(13.0, 5.6),
                                  gridspec_kw={"width_ratios": [1, 1.15],
                                               "wspace": 0.28})

# ============================================================
# PANEL A · pair notice-count distribution (98% / 2% gap)
# ============================================================
dist = data["pair_notice_count_distribution"]
# Keys are str ('1', '2', ...). Convert and sort.
counts = sorted([int(k) for k in dist.keys()])
freqs = [dist[str(c)] for c in counts]
total_pairs = sum(freqs)
pcts = [f / total_pairs * 100 for f in freqs]

# Bars — only show counts up to 5 (everything else is 0)
display_counts = [c for c in counts if c <= 5]
display_freqs = [dist[str(c)] for c in display_counts]
display_pcts = [f / total_pairs * 100 for f in display_freqs]

bar_colors = [PINK if c == 1 else PINK_DEEP if c == 2 else GREY_DEEP
              for c in display_counts]
bars = ax_l.bar(display_counts, display_pcts, color=bar_colors,
                 edgecolor=BG, linewidth=0.6, alpha=0.95, width=0.65)

# Annotate
for c, p, f in zip(display_counts, display_pcts, display_freqs):
    if p > 1:
        ax_l.text(c, p + 1.2, f"{p:.1f}%",
                  ha="center", fontsize=10, fontweight="bold",
                  color=PINK_DEEP if c <= 2 else GREY_DEEP)
        ax_l.text(c, p + 4.0, f"n={f:,d}",
                  ha="center", fontsize=8, color=MUTED, style="italic")
    elif f > 0:
        ax_l.text(c, p + 1.0, f"{p:.1f}%\nn={f}",
                  ha="center", fontsize=8, color=MUTED, style="italic")

# Pullquote annotation between bars
ax_l.text(3, 60,
          "Of every 100 mutual\n"
          "recognitions in 2 days,\n"
          "98 are one-shot.",
          fontsize=10, color=INK, fontweight="normal", style="italic",
          ha="center", va="center",
          bbox=dict(boxstyle="round,pad=0.7", fc="white", ec=PINK,
                    alpha=0.95, lw=0.7))

ax_l.set_xticks(display_counts)
ax_l.set_xticklabels([f"{c}×" for c in display_counts])
ax_l.set_xlabel("Times this pair mutually noticed each other  (2 weekdays)")
ax_l.set_ylabel("Share of all noticed pairs  (%)")
ax_l.set_ylim(0, 108)
ax_l.set_title(
    "A · Almost every mutual notice is a one-shot",
    loc="left", fontweight="bold", pad=10, color=INK,
)
ax_l.text(0.5, 102,
          f"7,437 unique mutual-noticed pairs · max repeat in window = 2",
          fontsize=8.5, color=MUTED, style="italic")

# ============================================================
# PANEL B · per-agent histogram of n_distinct_partners
# ============================================================
rows = data["per_agent_concentration_rows"]
partner_counts = [r["n_distinct_partners"] for r in rows]
median_pc = data["agent_summary"]["n_distinct_partners_median"]

bins = np.arange(0, 36, 1)
counts_h, edges, patches = ax_r.hist(
    partner_counts, bins=bins, color=GREY_WARM, edgecolor=BG,
    linewidth=0.5, alpha=0.95,
)

# Median line
ax_r.axvline(median_pc, color=PINK_DEEP, linestyle="--",
             linewidth=1.6, alpha=0.95)
ax_r.text(median_pc + 0.6, ax_r.get_ylim()[1] * 0.88,
          f"median  {int(median_pc)} partners",
          color=PINK_DEEP, fontsize=10, fontweight="bold")

# Annotate with the interpretive caption
ax_r.text(22, ax_r.get_ylim()[1] * 0.78,
          "Each bar = N agents who noticed\n"
          "exactly that many distinct people.\n\n"
          "Most agents have a small, wide,\n"
          "non-repeating awareness graph.",
          fontsize=9, color=INK_SOFT, style="italic",
          va="top", ha="left",
          bbox=dict(boxstyle="round,pad=0.6", fc="white",
                    ec=INK_SOFT, alpha=0.92, lw=0.5))

ax_r.set_xlabel("Number of distinct people this agent noticed (2 weekdays)")
ax_r.set_ylabel(f"Number of agents  (n={len(rows):,d})")
ax_r.set_xlim(0, 36)
ax_r.set_title(
    "B · Each agent's awareness graph is wide and thin",
    loc="left", fontweight="bold", pad=10, color=INK,
)
agent_summary = data["agent_summary"]
ax_r.text(0.5, ax_r.get_ylim()[1] * 0.96,
          f"Median agent: {int(agent_summary['n_distinct_partners_median'])} "
          f"distinct partners · {int(agent_summary['n_total_noticed_median'])} "
          f"total notices · pair Gini = {data['gini']}",
          fontsize=8.5, color=MUTED, style="italic")

# ============================================================
# Suptitle
# ============================================================
plt.suptitle(
    "Finding 3 · The thinness of awareness — wide reach, no repeats (2-day window)",
    fontsize=12, fontweight="bold", y=1.01, color=INK,
)

plt.tight_layout()
plt.savefig(OUT, dpi=200, bbox_inches="tight", facecolor=BG)
plt.close()
print(f"✓ {OUT} ({OUT.stat().st_size // 1024} KB)")
