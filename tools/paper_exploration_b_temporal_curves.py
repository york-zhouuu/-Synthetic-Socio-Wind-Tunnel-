"""[Auto-B] 14-day temporal curves: onset / habituation / post-revert.

Plot per-day metrics across 14 days × 4 variants × 3 seeds.
Phases: 4 baseline (day 0-3) + 6 intervention (day 4-9) + 4 post (day 10-13).
Identify onset (day 4 spike), plateau, post-period revert.
"""
from __future__ import annotations
import json
import statistics
from pathlib import Path

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
OUT = REPO / "data/analysis/2026-05-23_paper_exploration/B_temporal_curves"
OUT.mkdir(parents=True, exist_ok=True)

SEEDS = {
    43: REPO / "data/experiments/20260521_185100_publishable_v6_day4to13_fork_seed43",
    44: REPO / "data/experiments/20260522_165045_publishable_v7_day4to13_fork_seed44",
    45: REPO / "data/experiments/20260522_212423_publishable_v7_day4to13_fork_seed45",
}
VARIANTS = ["baseline", "hyperlocal_push", "global_distraction", "phone_friction"]
VARIANT_COLORS = {
    "baseline": "#777777",
    "hyperlocal_push": "#d62728",
    "global_distraction": "#1f77b4",
    "phone_friction": "#2ca02c",
}
VARIANT_LABELS = {
    "baseline": "对照组 (baseline)",
    "hyperlocal_push": "超在地推送 (HP)",
    "global_distraction": "镜像组·全球新闻 (GD)",
    "phone_friction": "反技术组 (PF)",
}


def per_day_series(seed: int, variant: str, metric_path: list[str]) -> list:
    """Extract per-day series for a nested metric path from seed_N.json."""
    p = SEEDS[seed] / f"variant_{variant}" / f"seed_{seed}.json"
    with open(p) as f:
        sd = json.load(f)
    series = []
    for pd in sd["run_metrics"].get("per_day", []):
        cur = pd
        for k in metric_path:
            if isinstance(cur, dict):
                cur = cur.get(k)
            else:
                cur = None
                break
        series.append(cur)
    return series


def main():
    print("=== loading per-day data ===")
    # Collect 14-day series per (seed, variant, metric)
    metrics = [
        ("encounter_count_total", ["encounter_count_total"], "encounter count"),
        ("distinct_encounter_pairs", ["distinct_encounter_pairs"], "distinct pairs"),
        ("notifications_delivered", ["notifications_delivered"], "notifications"),
        ("info_origins_today", ["info_origins_today"], "info origins/day"),
        ("info_reaching_2plus_today", ["info_reaching_2plus_today"], "info reach ≥2hop"),
        ("avg_hops_today", ["avg_hops_today"], "avg propagation hops"),
        ("new_ties_today", ["new_ties_today"], "new ties/day"),
        ("avg_ties_per_agent", ["avg_ties_per_agent"], "avg ties/agent"),
        ("tie_count_weak", ["tie_count_weak"], "weak ties total"),
        ("move_success_count", ["move_success_count"], "move success/day"),
    ]

    data = {}  # (variant, metric_key) -> {day: [seed values]}
    for v in VARIANTS:
        for key, path, _ in metrics:
            day_vals = [[] for _ in range(14)]
            for s in SEEDS:
                ser = per_day_series(s, v, path)
                for d, val in enumerate(ser):
                    if val is not None:
                        day_vals[d].append(val)
            data[(v, key)] = day_vals

    # JSON dump
    out_json = OUT / "per_day_series.json"
    with open(out_json, "w") as f:
        json.dump({
            "phases": {"baseline": [0,1,2,3], "intervention": [4,5,6,7,8,9],
                       "post": [10,11,12,13]},
            "metrics": [
                {"key": k, "label": lbl, "path": p}
                for k, p, lbl in metrics
            ],
            "data": {
                f"{v}|{k}": [
                    {"day": d, "values": vals,
                     "mean": statistics.mean(vals) if vals else None,
                     "stdev": statistics.stdev(vals) if len(vals)>1 else None}
                    for d, vals in enumerate(day_vals)
                ]
                for (v, k), day_vals in data.items()
            }
        }, f, ensure_ascii=False, indent=2)
    print(f"  → wrote {out_json}")

    # Multi-panel matplotlib
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    n_metrics = len(metrics)
    cols = 2
    rows = (n_metrics + 1) // 2
    fig, axes = plt.subplots(rows, cols, figsize=(14, 4*rows))
    axes = axes.flatten()
    days = list(range(14))

    for i, (key, _, label) in enumerate(metrics):
        ax = axes[i]
        for v in VARIANTS:
            means = []
            stdevs = []
            for d in days:
                vals = data[(v, key)][d]
                means.append(statistics.mean(vals) if vals else float("nan"))
                stdevs.append(statistics.stdev(vals) if len(vals)>1 else 0)
            means = np.array(means); stdevs = np.array(stdevs)
            ax.plot(days, means, marker="o", color=VARIANT_COLORS[v],
                    label=VARIANT_LABELS[v], linewidth=2)
            ax.fill_between(days, means-stdevs, means+stdevs,
                            color=VARIANT_COLORS[v], alpha=0.15)
        # Phase shading
        ax.axvspan(-0.5, 3.5, alpha=0.05, color="grey", label=None)
        ax.axvspan(3.5, 9.5, alpha=0.08, color="red", label=None)
        ax.axvspan(9.5, 13.5, alpha=0.05, color="grey", label=None)
        ax.axvline(3.5, color="black", linestyle="--", linewidth=0.5)
        ax.axvline(9.5, color="black", linestyle="--", linewidth=0.5)
        ax.set_title(label, fontsize=11)
        ax.set_xlabel("day")
        ax.set_xticks(days)
        ax.grid(True, alpha=0.3)
        if i == 0:
            ax.legend(loc="upper left", fontsize=9)
    # Hide empty subplots
    for j in range(n_metrics, len(axes)):
        axes[j].set_visible(False)
    fig.suptitle("14-day temporal curves — onset (day 4-9 red) vs baseline/post (grey)\n"
                 "Lines = mean across 3 seeds, shaded band = ±1 stdev",
                 fontsize=14, y=1.005)
    plt.tight_layout()
    out_png = OUT / "temporal_curves.png"
    plt.savefig(out_png, dpi=140, bbox_inches="tight")
    plt.close()
    print(f"  → wrote {out_png}")

    # Compute "phase summary" — mean per (baseline / intervention / post) per (variant, metric)
    insights = {}
    for v in VARIANTS:
        insights[v] = {}
        for key, _, label in metrics:
            phase_means = {}
            for phase_name, phase_days in [
                ("baseline", [0,1,2,3]),
                ("intervention", [4,5,6,7,8,9]),
                ("post", [10,11,12,13]),
            ]:
                phase_vals = []
                for d in phase_days:
                    phase_vals.extend(data[(v, key)][d])
                if phase_vals:
                    phase_means[phase_name] = statistics.mean(phase_vals)
            insights[v][key] = phase_means

    # Write insights markdown
    with open(OUT / "phase_summary.md", "w") as f:
        f.write("# Phase-summary: baseline (day 0-3) vs intervention (4-9) vs post (10-13)\n\n")
        f.write("Mean per phase, averaged across 3 seeds.\n\n")
        for key, _, label in metrics:
            f.write(f"## {label} (`{key}`)\n\n")
            f.write(f"| variant | baseline | intervention | post | "
                    f"intervention/baseline | post/baseline (revert?) |\n")
            f.write("|---|---|---|---|---|---|\n")
            for v in VARIANTS:
                ph = insights[v].get(key, {})
                bl = ph.get("baseline"); iv = ph.get("intervention"); po = ph.get("post")
                if bl and bl > 0:
                    iv_r = f"{iv/bl:.2f}×" if iv else "?"
                    po_r = f"{po/bl:.2f}×" if po else "?"
                else:
                    iv_r = po_r = "?"
                fmt = lambda x: f"{x:,.0f}" if x is not None and x > 100 else (
                    f"{x:.2f}" if x is not None else "?")
                f.write(f"| {VARIANT_LABELS[v]} | {fmt(bl)} | {fmt(iv)} | {fmt(po)} | "
                        f"{iv_r} | {po_r} |\n")
            f.write("\n")
    print(f"  → wrote {OUT / 'phase_summary.md'}")

    # Per-variant "onset" detection: day 4 vs day 3 jump for HP/GD/PF
    with open(OUT / "README.md", "w") as f:
        f.write("# Analysis B: 14-day temporal curves\n\n")
        f.write("## Phases\n")
        f.write("- **Baseline** (day 0-3): no intervention applied\n")
        f.write("- **Intervention** (day 4-9): 6 days of variant-specific push\n")
        f.write("- **Post** (day 10-13): intervention stopped, observe revert\n\n")
        f.write("## Files\n")
        f.write("- `temporal_curves.png` — 10-metric multi-panel chart\n")
        f.write("- `per_day_series.json` — raw per-day data per cell\n")
        f.write("- `phase_summary.md` — phase-aggregated stats table\n\n")
        f.write("## Key questions to answer from this analysis\n")
        f.write("1. **Onset shape**: Does HP effect jump suddenly on day 4 (push starts)\n"
                "   or accumulate gradually? → tells us about habit-formation dynamics\n")
        f.write("2. **Habituation**: Does effect attenuate across days 5-9? → diminishing returns?\n")
        f.write("3. **Post-period revert**: Do days 10-13 return to baseline\n"
                "   levels (no stickiness) or stay elevated (residual habits)?\n")
        f.write("4. **Variant separation**: When does HP/PF curve diverge from GD?\n\n")
    print(f"  → wrote {OUT / 'README.md'}")


if __name__ == "__main__":
    main()
