"""F2 figure · Friction vs push for new-tie formation.

2-panel paper-style figure:
  Left  : total noticed pairs by intervention condition
  Right : novelty share — % of those pairs that did not exist in BL
"""
import json
from pathlib import Path
import matplotlib.pyplot as plt

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
DATA = REPO / "data/analysis/2026-05-24_hypothesis_validation/H17_familiarity_noticed/h17_noticed_pairs.json"
OUT = REPO / "data/analysis/2026-05-24_hypothesis_validation/F2_friction_figure.png"

data = json.loads(DATA.read_text())
combined = data["combined"]

# Palette (v7)
BG, INK, INK_SOFT = "#FCFAF6", "#1B1F2A", "#3a3a3a"
PINK, PINK_DEEP = "#FF4D8F", "#C8245E"
GREY_WARM, GREY_DEEP, MUTED = "#9E988C", "#5F584F", "#6a6358"

# Reader-facing condition labels
LABELS = {
    "baseline":          ("no app",                 "(baseline)",      GREY_WARM),
    "hyperlocal_push":   ('"hyperlocal" push',     "(recommendation)", PINK),
    "global_distraction":("global distraction",     "(content swap)",  GREY_DEEP),
    "phone_friction":    ("phone friction",         "(removed attention)", PINK_DEEP),
}
ORDER = ["baseline", "hyperlocal_push", "global_distraction", "phone_friction"]

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

fig, (ax_l, ax_r) = plt.subplots(1, 2, figsize=(13, 5.4),
                                  gridspec_kw={"wspace": 0.30})

xs = list(range(len(ORDER)))
labels_top = [LABELS[c][0] for c in ORDER]
labels_bot = [LABELS[c][1] for c in ORDER]
colors = [LABELS[c][2] for c in ORDER]

# ====== LEFT: total noticed pairs ======
totals = [combined[c]["total_pairs"] for c in ORDER]
ratios = [combined[c]["ratio_vs_bl"] for c in ORDER]

bars = ax_l.bar(xs, totals, color=colors, edgecolor=BG, linewidth=0.7,
                 alpha=0.95, width=0.65)

# Annotate ratio above each bar
for i, (t, r) in enumerate(zip(totals, ratios)):
    if i == 0:
        label = f"{t:,d}\n(baseline)"
    else:
        label = f"{t:,d}\n{r:.2f}× BL"
    color_ann = PINK_DEEP if i in (1, 3) else INK_SOFT
    weight = "bold" if i in (1, 3) else "normal"
    ax_l.text(i, t + 700, label, ha="center", fontsize=10,
               color=color_ann, fontweight=weight)

ax_l.set_xticks(xs)
ax_l.set_xticklabels([f"{a}\n{b}" for a, b in zip(labels_top, labels_bot)],
                      fontsize=9.5, color=INK)
ax_l.set_ylim(0, max(totals) * 1.20)
ax_l.set_ylabel("Noticed pairs · 14 days · 2 seeds pooled")
ax_l.set_title(
    "A · Both push and friction roughly triple noticed pairs over baseline",
    loc="left", fontweight="bold", pad=12, color=INK,
)

# ====== RIGHT: novelty share ======
new_shares = [combined[c]["pct_new"] for c in ORDER]
new_counts = [combined[c]["new_pairs"] for c in ORDER]

bars2 = ax_r.bar(xs, new_shares, color=colors, edgecolor=BG, linewidth=0.7,
                  alpha=0.95, width=0.65)

for i, (s, n) in enumerate(zip(new_shares, new_counts)):
    if i == 0:
        label = "0%\n(baseline = itself)"
        color_ann = INK_SOFT
        weight = "normal"
    else:
        label = f"{s:.1f}%\n({n:,d} new pairs)"
        color_ann = PINK_DEEP if i in (1, 3) else INK_SOFT
        weight = "bold" if i in (1, 3) else "normal"
    ax_r.text(i, s + 3.0, label, ha="center", fontsize=10,
              color=color_ann, fontweight=weight)

ax_r.set_xticks(xs)
ax_r.set_xticklabels([f"{a}\n{b}" for a, b in zip(labels_top, labels_bot)],
                      fontsize=9.5, color=INK)
ax_r.set_ylim(0, 115)
ax_r.set_ylabel("Share of noticed pairs absent in baseline  (%)")
ax_r.set_title(
    "B · Across all three interventions, > 85% of noticed pairs are new — different people, not more frequency",
    loc="left", fontweight="bold", pad=12, color=INK, fontsize=10.5,
)

plt.suptitle(
    "Finding 2 · Friction and recommendation reach similar magnitudes of new-tie formation — and the route that prescribed nothing reached the most",
    fontsize=11.5, fontweight="bold", y=1.02, color=INK,
)

plt.tight_layout()
plt.savefig(OUT, dpi=200, bbox_inches="tight", facecolor=BG)
plt.close()
print(f"✓ {OUT} ({OUT.stat().st_size // 1024} KB)")
