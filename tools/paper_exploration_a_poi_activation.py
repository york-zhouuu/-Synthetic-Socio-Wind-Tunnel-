"""[Auto-A] POI activation heatmap analysis.

For each location_id, sum dwell_ticks across 14 days × 3 seeds for each variant.
Compute activation pct = (variant_mean - baseline_mean) / baseline_mean.
Render PNG heatmap on Lane Cove coords + top-N activated/deactivated table.
"""
from __future__ import annotations
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
OUT = REPO / "data/analysis/2026-05-23_paper_exploration/A_poi_activation"
OUT.mkdir(parents=True, exist_ok=True)

SEEDS = {
    43: REPO / "data/experiments/20260521_185100_publishable_v6_day4to13_fork_seed43",
    44: REPO / "data/experiments/20260522_165045_publishable_v7_day4to13_fork_seed44",
    45: REPO / "data/experiments/20260522_212423_publishable_v7_day4to13_fork_seed45",
}
VARIANTS = ["baseline", "hyperlocal_push", "global_distraction", "phone_friction"]


def build_loc_index():
    with open(REPO / "data/lanecove_atlas.json") as f:
        atlas = json.load(f)
    idx = {}
    for b in atlas["buildings"].values():
        c = b.get("entrance_coord")
        if c:
            idx[b["id"]] = {
                "type": b.get("building_type") or "unknown",
                "name": b.get("name") or b["id"],
                "x": c["x"], "y": c["y"],
                "kind": "building",
            }
    outdoor = atlas.get("outdoor_areas", {})
    if isinstance(outdoor, dict):
        outdoor = list(outdoor.values())
    for o in outdoor:
        verts = o.get("polygon", {}).get("vertices", [])
        if verts:
            cx = sum(v["x"] for v in verts)/len(verts)
            cy = sum(v["y"] for v in verts)/len(verts)
            idx[o["id"]] = {
                "type": "outdoor_" + (o.get("area_type") or "?"),
                "name": o.get("name") or o.get("road_name") or o["id"],
                "x": cx, "y": cy, "kind": "outdoor",
            }
    return idx


def sum_dwell_per_location(seed: int, variant: str) -> dict[str, int]:
    """Sum dwell_ticks per location_id across 14 days (one seed × variant)."""
    p = SEEDS[seed] / f"variant_{variant}" / f"seed_{seed}.json"
    with open(p) as f:
        sd = json.load(f)
    totals: dict[str, int] = defaultdict(int)
    for pd in sd["run_metrics"].get("per_day", []):
        for loc, ticks in pd.get("location_dwell_ticks", {}).items():
            totals[loc] += ticks
    return dict(totals)


def main():
    print("=== loading atlas ===")
    loc_idx = build_loc_index()
    print(f"  {len(loc_idx)} locations indexed")

    print("=== summing dwell per location per cell ===")
    cell_dwell: dict[tuple[int,str], dict[str,int]] = {}
    for s in SEEDS:
        for v in VARIANTS:
            cell_dwell[(s,v)] = sum_dwell_per_location(s, v)
            print(f"  seed {s}/{v}: {len(cell_dwell[(s,v)])} locs touched")

    # Mean dwell per location across 3 seeds, per variant
    print("=== mean dwell per location across 3 seeds ===")
    mean_dwell = {v: defaultdict(float) for v in VARIANTS}
    for v in VARIANTS:
        for loc in loc_idx:
            vals = [cell_dwell[(s,v)].get(loc, 0) for s in SEEDS]
            mean_dwell[v][loc] = statistics.mean(vals)

    # Activation pct vs baseline (only for locations with non-trivial BL dwell)
    MIN_BL = 5.0  # at least 5 ticks/seed on average to avoid noisy divide
    activation = {v: {} for v in VARIANTS if v != "baseline"}
    for v in VARIANTS:
        if v == "baseline": continue
        for loc in loc_idx:
            bl = mean_dwell["baseline"][loc]
            vv = mean_dwell[v][loc]
            if bl < MIN_BL and vv < MIN_BL: continue
            denom = max(bl, MIN_BL)
            pct = (vv - bl) / denom * 100
            activation[v][loc] = {
                "loc_id": loc,
                "name": loc_idx[loc].get("name"),
                "type": loc_idx[loc].get("type"),
                "x": loc_idx[loc].get("x"),
                "y": loc_idx[loc].get("y"),
                "bl_mean": bl,
                "variant_mean": vv,
                "activation_pct": pct,
                "abs_delta": vv - bl,
            }

    # JSON dump
    out_json = OUT / "activation_per_location.json"
    with open(out_json, "w") as f:
        json.dump({
            "mean_dwell_per_variant": {v: dict(d) for v,d in mean_dwell.items()},
            "activation_vs_baseline": activation,
            "n_seeds": len(SEEDS),
            "min_baseline_ticks_threshold": MIN_BL,
        }, f, ensure_ascii=False, indent=2)
    print(f"  → wrote {out_json}")

    # Top-N tables
    for v, acts in activation.items():
        sorted_up = sorted(acts.values(), key=lambda r: -r["activation_pct"])[:25]
        sorted_dn = sorted(acts.values(), key=lambda r: r["activation_pct"])[:25]
        with open(OUT / f"top_activated_{v}.md", "w") as f:
            f.write(f"# Top activated/deactivated locations — {v} vs baseline\n\n")
            f.write(f"Mean across {len(SEEDS)} seeds. Activation pct = "
                    f"(variant_mean − baseline_mean) / max(baseline_mean, {MIN_BL})\n\n")
            f.write(f"## 🔥 Top 25 ACTIVATED (more dwell under {v})\n\n")
            f.write("| Rank | Location | Type | BL ticks | Variant ticks | Δ | Activation% |\n")
            f.write("|---|---|---|---|---|---|---|\n")
            for i,r in enumerate(sorted_up,1):
                f.write(f"| {i} | {r['name']} | {r['type']} | {r['bl_mean']:.0f} | "
                        f"{r['variant_mean']:.0f} | +{r['abs_delta']:.0f} | "
                        f"{r['activation_pct']:+.1f}% |\n")
            f.write(f"\n## ❄️ Top 25 DEACTIVATED (less dwell under {v})\n\n")
            f.write("| Rank | Location | Type | BL ticks | Variant ticks | Δ | Activation% |\n")
            f.write("|---|---|---|---|---|---|---|\n")
            for i,r in enumerate(sorted_dn,1):
                f.write(f"| {i} | {r['name']} | {r['type']} | {r['bl_mean']:.0f} | "
                        f"{r['variant_mean']:.0f} | {r['abs_delta']:.0f} | "
                        f"{r['activation_pct']:+.1f}% |\n")
        print(f"  → wrote {OUT / f'top_activated_{v}.md'}")

    # Render heatmaps
    print("=== rendering heatmaps ===")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    # 3 variants × 1 fig (BL as reference, side-by-side maps showing activation pct)
    for v in ["hyperlocal_push", "global_distraction", "phone_friction"]:
        fig, ax = plt.subplots(1, 1, figsize=(14, 10))
        acts = list(activation[v].values())
        if not acts: continue
        xs = [a["x"] for a in acts]
        ys = [a["y"] for a in acts]
        pcts = [max(-100, min(200, a["activation_pct"])) for a in acts]
        sizes = [max(8, min(200, math.sqrt(a["bl_mean"]) * 1.5)) for a in acts]
        sc = ax.scatter(xs, ys, c=pcts, s=sizes, cmap="RdBu_r", vmin=-50, vmax=50,
                        alpha=0.7, edgecolors="black", linewidths=0.2)
        cbar = plt.colorbar(sc, ax=ax)
        cbar.set_label(f"Activation % vs baseline\n(red=more dwell, blue=less)", fontsize=11)
        ax.set_title(f"POI activation: {v} vs baseline (Lane Cove)\n"
                     f"Bubble size = baseline dwell ticks (sqrt scale). "
                     f"Mean across {len(SEEDS)} seeds.", fontsize=13)
        ax.set_xlabel("x (m, atlas-local)")
        ax.set_ylabel("y (m, atlas-local)")
        ax.set_aspect("equal")
        ax.grid(True, alpha=0.3)
        # Annotate top 5 most activated
        top5 = sorted(acts, key=lambda r: -r["activation_pct"])[:5]
        for r in top5:
            ax.annotate(r["name"][:30], (r["x"], r["y"]),
                        xytext=(5,5), textcoords="offset points",
                        fontsize=8, color="darkred", fontweight="bold")
        plt.tight_layout()
        out_png = OUT / f"heatmap_{v}.png"
        plt.savefig(out_png, dpi=140)
        plt.close()
        print(f"  → wrote {out_png}")

    # Summary markdown
    with open(OUT / "README.md", "w") as f:
        f.write("# Analysis A: POI Activation\n\n")
        f.write(f"Mean dwell ticks per location, across {len(SEEDS)} seeds, "
                f"compared variant vs baseline.\n\n")
        f.write("## Files\n\n")
        f.write("- `activation_per_location.json` — full per-loc activation data\n")
        f.write("- `top_activated_<variant>.md` — top 25 ↑↓ per variant\n")
        f.write("- `heatmap_<variant>.png` — spatial heatmap\n\n")
        f.write("## Headline numbers\n\n")
        for v, acts in activation.items():
            vals = list(acts.values())
            if not vals: continue
            pcts = [r["activation_pct"] for r in vals]
            up = [p for p in pcts if p > 10]
            dn = [p for p in pcts if p < -10]
            f.write(f"### {v}\n")
            f.write(f"- locations with non-trivial dwell: {len(vals)}\n")
            f.write(f"- activated (>10%): {len(up)}\n")
            f.write(f"- deactivated (<-10%): {len(dn)}\n")
            f.write(f"- median activation: {statistics.median(pcts):+.1f}%\n")
            f.write(f"- max activation: {max(pcts):+.1f}%\n")
            f.write(f"- min activation: {min(pcts):+.1f}%\n\n")
    print(f"  → wrote {OUT / 'README.md'}")


if __name__ == "__main__":
    main()
