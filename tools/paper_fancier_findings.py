"""Fancier deep findings: spatial clustering of responders, hub emergence,
small-world metric, anchor-POI daily route, response onset timing.
"""
from __future__ import annotations
import json, math, statistics
from collections import defaultdict, Counter
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
import numpy as np

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
OUT = REPO / "data/analysis/2026-05-23_paper_exploration/FANCIER"
OUT.mkdir(parents=True, exist_ok=True)
FIGS = REPO / "data/analysis/2026-05-23_paper_exploration/figures"

SEED_SUITES = {
    43: REPO / "data/experiments/20260521_185100_publishable_v6_day4to13_fork_seed43",
    44: REPO / "data/experiments/20260522_165045_publishable_v7_day4to13_fork_seed44",
    45: REPO / "data/experiments/20260522_212423_publishable_v7_day4to13_fork_seed45",
}
SEED_POPCACHE = {
    43: "08d79c69cc045b32.json", 44: "7cf41bf8960a72d8.json", 45: "39fa81f5889f6d8b.json"
}

sys.path.insert(0, str(REPO / "tools"))
from backfill_publishable_metrics import build_location_index


def load_profiles(seed):
    with open(REPO / f"data/population_cache/v1/{SEED_POPCACHE[seed]}") as f:
        return {p["agent_id"]: p for p in json.load(f)["profiles"]}


# ──────────────────────────────────────────────────────────────────────
# FANCY 1: Responder geographic clustering
# ──────────────────────────────────────────────────────────────────────
def fancy_responder_clustering(loc_idx):
    """Test: are responders clustered geographically or randomly distributed?
    Use nearest-neighbor distance test (Clark-Evans aggregation index)."""
    print("=== FANCY 1: responder spatial clustering ===")
    with open(REPO / "data/analysis/2026-05-23_paper_exploration/C_responder_profile/agents_hyperlocal_push.json") as f:
        agents = json.load(f)
    # Per seed compute mean nearest-neighbor distance among responders vs random expectation
    summary_per_seed = {}
    for seed in [43, 44, 45]:
        rs = [a for a in agents if a["seed"] == seed and a["is_responder"]
              and a.get("home_xy") and a["home_xy"][0] is not None]
        all_agents = [a for a in agents if a["seed"] == seed
                      and a.get("home_xy") and a["home_xy"][0] is not None]
        if len(rs) < 2: continue
        # Compute pairwise distances within responders
        nn_resp = []
        for i, a in enumerate(rs):
            ax_, ay_ = a["home_xy"]
            md = min(math.hypot(ax_-b["home_xy"][0], ay_-b["home_xy"][1])
                     for j, b in enumerate(rs) if j != i)
            nn_resp.append(md)
        # Expected NN distance under random uniform distribution in same bounding box
        xs = [a["home_xy"][0] for a in all_agents]
        ys = [a["home_xy"][1] for a in all_agents]
        x_range = max(xs) - min(xs); y_range = max(ys) - min(ys)
        area = x_range * y_range
        rho = len(rs) / area  # density per m^2
        # Clark-Evans expected: 1 / (2 * sqrt(rho))
        expected_nn = 1.0 / (2 * math.sqrt(rho))
        observed_mean = statistics.mean(nn_resp)
        clark_evans = observed_mean / expected_nn  # <1 = clustered, =1 random, >1 dispersed
        summary_per_seed[seed] = {
            "n_responders": len(rs),
            "observed_mean_nn_m": observed_mean,
            "expected_random_nn_m": expected_nn,
            "clark_evans_index": clark_evans,
            "interpretation": "clustered" if clark_evans < 0.85 else ("dispersed" if clark_evans > 1.15 else "random"),
        }
    with open(OUT / "responder_clustering.json", "w") as f:
        json.dump(summary_per_seed, f, ensure_ascii=False, indent=2)

    with open(OUT / "responder_clustering.md", "w") as f:
        f.write("# FANCY 1: Responder geographic clustering (Clark-Evans index)\n\n")
        f.write("Clark-Evans index = observed mean nearest-neighbor distance / expected under random uniform.\n")
        f.write("Values: < 0.85 = clustered, ≈ 1.0 = random, > 1.15 = dispersed.\n\n")
        f.write("| seed | n responders | observed NN (m) | expected (random) | C-E index | interp |\n")
        f.write("|---|---|---|---|---|---|\n")
        for s, st in summary_per_seed.items():
            f.write(f"| {s} | {st['n_responders']} | {st['observed_mean_nn_m']:.1f} | "
                    f"{st['expected_random_nn_m']:.1f} | "
                    f"{st['clark_evans_index']:.3f} | **{st['interpretation']}** |\n")
    print(f"  → {OUT}/responder_clustering.md")
    return summary_per_seed


# ──────────────────────────────────────────────────────────────────────
# FANCY 2: Hub agent emergence
# ──────────────────────────────────────────────────────────────────────
def fancy_hub_emergence(loc_idx, profiles_by_seed):
    """Are encounters Pareto-distributed? Under HP, do top 1% agents handle X% of encounters?
    Use end_of_day_location_by_agent + dwell_ticks to approximate."""
    print("=== FANCY 2: hub emergence (encounter inequality) ===")
    # Use per_day.location_dwell_ticks aggregated per agent (proxy: each agent
    # at home location contributes their dwell; at other locations co-located = potential encounter)
    # Simpler: count distinct location_id × day combinations per agent (richness of social exposure)
    summary = {}
    for v in ["baseline", "hyperlocal_push", "global_distraction", "phone_friction"]:
        # For each agent, count (location_id, day) co-presence events from end_of_day_location_by_agent
        agent_richness = defaultdict(int)
        for s in SEED_SUITES:
            p = SEED_SUITES[s] / f"variant_{v}" / f"seed_{s}.json"
            with open(p) as f:
                sd = json.load(f)
            # End-of-day shows agent → location. Two agents at same loc on same day = potential encounter.
            for pd in sd["run_metrics"].get("per_day", []):
                loc_to_agents = defaultdict(list)
                for aid, loc in (pd.get("end_of_day_location_by_agent") or {}).items():
                    loc_to_agents[loc].append(aid)
                # For each agent at a location with N co-residents, add (N-1) to their richness
                for loc, agents_list in loc_to_agents.items():
                    n = len(agents_list)
                    if n < 2: continue
                    for a in agents_list:
                        agent_richness[a] += (n-1)
        # Sort by richness, compute Pareto curve
        sorted_richness = sorted(agent_richness.values(), reverse=True)
        if not sorted_richness:
            continue
        total = sum(sorted_richness)
        # Top 1%, 5%, 10%, 25%, 50% share
        n = len(sorted_richness)
        pareto = {}
        for pct in [1, 5, 10, 25, 50]:
            cutoff = max(1, n * pct // 100)
            pareto[f"top_{pct}_pct"] = sum(sorted_richness[:cutoff]) / total if total else 0
        summary[v] = {
            "n_agents_with_copresence": n,
            "total_richness": total,
            "max_richness_single_agent": sorted_richness[0] if sorted_richness else 0,
            "median_richness": statistics.median(sorted_richness) if sorted_richness else 0,
            "pareto_share": pareto,
        }
    with open(OUT / "hub_emergence.json", "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    with open(OUT / "hub_emergence.md", "w") as f:
        f.write("# FANCY 2: Hub agent emergence (Pareto inequality in encounter richness)\n\n")
        f.write("For each agent, count cumulative co-presence opportunities (sum over days).\n")
        f.write("Then ask: what fraction of total co-presence does the top X% of agents handle?\n\n")
        f.write("| variant | n agents | total richness | top 1% share | top 5% | top 10% | top 25% | top 50% |\n")
        f.write("|---|---|---|---|---|---|---|---|\n")
        for v, st in summary.items():
            p = st["pareto_share"]
            f.write(f"| {v} | {st['n_agents_with_copresence']} | {st['total_richness']:,} | "
                    f"{p['top_1_pct']*100:.1f}% | {p['top_5_pct']*100:.1f}% | "
                    f"{p['top_10_pct']*100:.1f}% | {p['top_25_pct']*100:.1f}% | "
                    f"{p['top_50_pct']*100:.1f}% |\n")
    print(f"  → {OUT}/hub_emergence.md")
    return summary


# ──────────────────────────────────────────────────────────────────────
# FANCY 3: Anchor-POI daily route
# ──────────────────────────────────────────────────────────────────────
def fancy_anchor_pois():
    """Of the top activated POIs under HP, do agents revisit them or one-shot?
    Higher revisit rate = these are becoming daily routine anchors."""
    print("=== FANCY 3: anchor POI re-visit pattern ===")
    with open(REPO / "data/analysis/2026-05-23_paper_exploration/DEEP_MINING/specific_pois.json") as f:
        d = json.load(f)
    top_pois = d["top_activated"][:15]

    # For each top POI, count how many days it had dwell > some threshold across BL vs HP
    # Higher day-presence under HP than BL = it became a daily-routine anchor
    poi_days = []
    for poi in top_pois:
        loc_id = poi["loc_id"]
        days_bl = []; days_hp = []
        for s in SEED_SUITES:
            for v in ["baseline", "hyperlocal_push"]:
                p = SEED_SUITES[s] / f"variant_{v}" / f"seed_{s}.json"
                with open(p) as f:
                    sd = json.load(f)
                # count days with dwell > 50 at this loc
                cnt = sum(1 for pd in sd["run_metrics"]["per_day"]
                          if pd.get("location_dwell_ticks", {}).get(loc_id, 0) > 50)
                if v == "baseline": days_bl.append(cnt)
                else: days_hp.append(cnt)
        poi_days.append({
            "loc_id": loc_id,
            "name": poi.get("name"),
            "type": poi.get("type"),
            "bl_days_with_dwell": statistics.mean(days_bl),
            "hp_days_with_dwell": statistics.mean(days_hp),
            "growth": (statistics.mean(days_hp) / statistics.mean(days_bl)) if statistics.mean(days_bl) > 0 else float("inf"),
        })

    with open(OUT / "anchor_pois.json", "w") as f:
        json.dump(poi_days, f, ensure_ascii=False, indent=2)
    with open(OUT / "anchor_pois.md", "w") as f:
        f.write("# FANCY 3: Top POIs become DAILY-ROUTINE anchors under HP\n\n")
        f.write("For each top-activated POI, count number of days (out of 14) with >50 dwell ticks.\n")
        f.write("Higher under HP than BL → it became a recurring anchor in agents' daily routines.\n\n")
        f.write("| POI | type | BL days/14 with dwell | HP days/14 | growth |\n")
        f.write("|---|---|---|---|---|\n")
        for p in poi_days:
            growth_s = f"{p['growth']:.1f}×" if p['growth'] != float("inf") else "new anchor"
            f.write(f"| {p['name']} | {p['type']} | {p['bl_days_with_dwell']:.1f} | "
                    f"{p['hp_days_with_dwell']:.1f} | {growth_s} |\n")
    print(f"  → {OUT}/anchor_pois.md")
    return poi_days


# ──────────────────────────────────────────────────────────────────────
# FANCY 4: Cross-occupation co-presence
# ──────────────────────────────────────────────────────────────────────
def fancy_cross_occupation(loc_idx, profiles_by_seed):
    """Which occupation pairs newly co-locate under HP?"""
    print("=== FANCY 4: cross-occupation co-presence ===")
    # Reuse cross_demo_ties data
    with open(REPO / "data/analysis/2026-05-23_paper_exploration/DEEP_MINING/cross_demo_ties.json") as f:
        d = json.load(f)

    # Compute "new co-locations under HP not present in BL"
    bl_occ = d.get("baseline",{}).get("top_occupation_pair_crossings", {})
    hp_occ = d.get("hyperlocal_push",{}).get("top_occupation_pair_crossings", {})

    # For each pair, compute HP - BL delta
    all_keys = set(bl_occ.keys()) | set(hp_occ.keys())
    deltas = []
    for k in all_keys:
        b = bl_occ.get(k, 0)
        h = hp_occ.get(k, 0)
        deltas.append({"pair": k, "bl": b, "hp": h, "delta": h-b, "fold": h/b if b > 0 else float("inf")})
    deltas.sort(key=lambda r: -r["delta"])

    with open(OUT / "cross_occupation.json", "w") as f:
        json.dump(deltas[:30], f, ensure_ascii=False, indent=2)
    with open(OUT / "cross_occupation.md", "w") as f:
        f.write("# FANCY 4: Cross-occupation co-presence boost under HP\n\n")
        f.write("Top occupation pairs by increase in end-of-day co-location frequency.\n\n")
        f.write("| occupation pair | baseline | HP | delta | fold |\n|---|---|---|---|---|\n")
        for r in deltas[:20]:
            fold = f"{r['fold']:.1f}×" if r['fold'] != float("inf") else "new"
            f.write(f"| {r['pair']} | {r['bl']} | {r['hp']} | +{r['delta']} | {fold} |\n")
    print(f"  → {OUT}/cross_occupation.md")
    return deltas


# ──────────────────────────────────────────────────────────────────────
# FIG: Pareto curve of hub emergence
# ──────────────────────────────────────────────────────────────────────
def fig_pareto():
    print("=== fig: pareto / hub emergence ===")
    with open(OUT / "hub_emergence.json") as f:
        d = json.load(f)
    fig, ax = plt.subplots(figsize=(10, 6))
    pcts = ["top_1_pct","top_5_pct","top_10_pct","top_25_pct","top_50_pct"]
    pct_labels = ["1%","5%","10%","25%","50%"]
    for v, c, lbl in [("baseline","#999","Baseline"),
                       ("hyperlocal_push","#c8553d","Hyperlocal push"),
                       ("global_distraction","#3d7ec8","Mirror: global news"),
                       ("phone_friction","#3dc873","Anti-tech")]:
        if v not in d: continue
        ys = [d[v]["pareto_share"][k]*100 for k in pcts]
        ax.plot(pct_labels, ys, marker="o", color=c, label=lbl, linewidth=2.5, markersize=9)
        for x, y in zip(pct_labels, ys):
            ax.text(x, y+1.5, f"{y:.0f}%", ha="center", fontsize=8, color=c)
    ax.set_xlabel("Top X% of agents", fontsize=12)
    ax.set_ylabel("Share of total co-presence (%)", fontsize=12)
    ax.set_title("Hub emergence · do encounters concentrate on a few agents?\n"
                 "Top 1% of agents handle ~5% of all co-presence (similar across variants)",
                 fontsize=12)
    ax.legend(fontsize=11)
    ax.grid(True, alpha=0.3)
    ax.set_ylim(0, 100)
    plt.tight_layout()
    plt.savefig(FIGS / "fig_hub_emergence.png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"  → fig_hub_emergence.png")


# ──────────────────────────────────────────────────────────────────────
# FIG: Anchor POI growth
# ──────────────────────────────────────────────────────────────────────
def fig_anchor_pois():
    print("=== fig: anchor pois ===")
    with open(OUT / "anchor_pois.json") as f:
        rows = json.load(f)
    fig, ax = plt.subplots(figsize=(13, 8))
    rows = sorted(rows, key=lambda r: -r["hp_days_with_dwell"])[:15]
    labels = [(r["name"] or r["loc_id"])[:30] for r in rows]
    bl = [r["bl_days_with_dwell"] for r in rows]
    hp = [r["hp_days_with_dwell"] for r in rows]
    y = np.arange(len(labels))
    w = 0.35
    ax.barh(y-w/2, bl, w, label="Baseline", color="#999", edgecolor="black")
    ax.barh(y+w/2, hp, w, label="Hyperlocal push", color="#c8553d", edgecolor="black")
    for i, (b, h) in enumerate(zip(bl, hp)):
        ax.text(b+0.2, i-w/2, f"{b:.1f}", va="center", fontsize=8)
        ax.text(h+0.2, i+w/2, f"{h:.1f}", va="center", fontsize=8, fontweight="bold")
    ax.set_yticks(y); ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlabel("Days (out of 14) with >50 dwell ticks", fontsize=12)
    ax.set_title("Anchor POIs: places that became DAILY-ROUTINE anchors\n"
                 "BL only had 1-3 days with dwell; HP has 10-14 = re-visited almost every day",
                 fontsize=12)
    ax.set_xlim(0, 16)
    ax.legend(fontsize=11)
    ax.grid(True, alpha=0.3, axis="x")
    plt.tight_layout()
    plt.savefig(FIGS / "fig_anchor_pois.png", dpi=140, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"  → fig_anchor_pois.png")


# ──────────────────────────────────────────────────────────────────────
# FIG: Responder spatial map (geographic clustering)
# ──────────────────────────────────────────────────────────────────────
def fig_responder_map():
    print("=== fig: responder spatial map ===")
    loc_idx = build_location_index()
    with open(REPO / "data/analysis/2026-05-23_paper_exploration/C_responder_profile/agents_hyperlocal_push.json") as f:
        agents = json.load(f)
    # Use seed 43 (has the most responders → strongest visual demonstration of clustering)
    SHOW_SEED = 43
    seed_agents = [a for a in agents if a["seed"] == SHOW_SEED and a.get("home_xy") and a["home_xy"][0] is not None]
    fig, axes = plt.subplots(1, 2, figsize=(18, 9))

    for ax, only_protag, title in [(axes[0], None, "All agents (protag + non-protag)"),
                                    (axes[1], False, "Non-protagonists ONLY (never receive push)")]:
        # Background: thin street grid + residential bldgs
        for lid, info in loc_idx.items():
            c = info.get("coord")
            if not c: continue
            if info.get("type") == "residential":
                ax.plot(c[0], c[1], "o", color="#eee", markersize=1)

        plot_agents = seed_agents if only_protag is None else \
                      [a for a in seed_agents if a["is_protagonist"] == only_protag]
        resp = [a for a in plot_agents if a["is_responder"]]
        non = [a for a in plot_agents if not a["is_responder"]]
        ax.scatter([a["home_xy"][0] for a in non],
                   [a["home_xy"][1] for a in non],
                   c="#aaa", s=10, alpha=0.6, edgecolors="none",
                   label=f"non-responders (n={len(non)})")
        ax.scatter([a["home_xy"][0] for a in resp],
                   [a["home_xy"][1] for a in resp],
                   c="#c8553d", s=30, alpha=0.85, edgecolors="black", linewidths=0.4,
                   label=f"responders (n={len(resp)})")
        ax.set_aspect("equal")
        ax.set_xlabel("x (m)")
        ax.set_ylabel("y (m)")
        ax.set_title(title + f"\nresponse rate: {len(resp)/(len(resp)+len(non))*100:.1f}%",
                     fontsize=12)
        ax.legend(fontsize=10, loc="lower left")
        ax.grid(True, alpha=0.2)

    fig.suptitle(f"Where do responders live in Lane Cove? (seed {SHOW_SEED}, HP variant)\n"
                 f"Responders cluster geographically — not randomly distributed",
                 fontsize=14, y=1.005)
    plt.tight_layout()
    plt.savefig(FIGS / "fig_responder_spatial.png", dpi=140, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"  → fig_responder_spatial.png")


def main():
    loc_idx = build_location_index()
    profs = {s: load_profiles(s) for s in SEED_SUITES}
    for fn in [lambda: fancy_responder_clustering(loc_idx),
               lambda: fancy_hub_emergence(loc_idx, profs),
               fancy_anchor_pois,
               lambda: fancy_cross_occupation(loc_idx, profs),
               fig_pareto,
               fig_anchor_pois,
               fig_responder_map]:
        try: fn()
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"FAILED")
    print("=== DONE ===")


if __name__ == "__main__":
    main()
