"""[Auto O-S batch]: time-of-day, network metrics, tie strength dynamics, info cascade."""
from __future__ import annotations
import json
import math
import statistics
from collections import defaultdict, Counter
from pathlib import Path
import sys

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
OUT_ROOT = REPO / "data/analysis/2026-05-23_paper_exploration"

SEED_SUITES = {
    43: REPO / "data/experiments/20260521_185100_publishable_v6_day4to13_fork_seed43",
    44: REPO / "data/experiments/20260522_165045_publishable_v7_day4to13_fork_seed44",
    45: REPO / "data/experiments/20260522_212423_publishable_v7_day4to13_fork_seed45",
}
SEED_POPCACHE = {
    43: "08d79c69cc045b32.json", 44: "7cf41bf8960a72d8.json", 45: "39fa81f5889f6d8b.json"
}
VARIANTS = ["baseline", "hyperlocal_push", "global_distraction", "phone_friction"]
VARIANTS_INT = ["hyperlocal_push", "global_distraction", "phone_friction"]

sys.path.insert(0, str(REPO / "tools"))
from backfill_publishable_metrics import build_location_index


def load_profiles(seed):
    with open(REPO / f"data/population_cache/v1/{SEED_POPCACHE[seed]}") as f:
        return {p["agent_id"]: p for p in json.load(f)["profiles"]}


# ──────────────────────────────────────────────────────────────────────
# O: Time-of-day patterns (tick→hour mapping, 288 ticks/day = 5 min each)
# ──────────────────────────────────────────────────────────────────────
def analysis_o_time_of_day(loc_idx):
    out = OUT_ROOT / "O_time_of_day"
    out.mkdir(exist_ok=True)
    print("=== O: time-of-day patterns ===")
    # Each tick = 5 min. day 0 = 24h × 12 ticks/h = 288 ticks
    # Hour of day = (tick % 288) // 12
    # Count position-changes by hour-of-day (proxy for movement intensity)
    summary = {}
    for s in SEED_SUITES:
        for v in VARIANTS:
            p = SEED_SUITES[s] / f"variant_{v}" / f"seed_{s}_positions.json"
            with open(p) as f:
                pdata = json.load(f)
            hour_counts = [0]*24
            for c in pdata.get("changes", []):
                if c.get("day", -1) < 4:  # baseline period
                    continue
                if c.get("day", -1) >= 10:  # post period
                    continue
                hour = (c["tick"] % 288) // 12
                hour_counts[hour] += 1
            summary[(s,v)] = hour_counts
    with open(out / "hour_of_day.json", "w") as f:
        json.dump({f"{s}|{v}": h for (s,v), h in summary.items()},
                  f, ensure_ascii=False, indent=2)
    # Aggregate
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(12, 6))
    hours = list(range(24))
    colors = {"baseline":"#777","hyperlocal_push":"#d62728","global_distraction":"#1f77b4","phone_friction":"#2ca02c"}
    for v in VARIANTS:
        mean_hourly = [statistics.mean(summary[(s,v)][h] for s in SEED_SUITES) for h in hours]
        ax.plot(hours, mean_hourly, marker="o", color=colors[v], label=v, linewidth=2)
    ax.set_xlabel("hour of day"); ax.set_ylabel("location-change events (avg over 3 seeds, days 4-9)")
    ax.set_title("Time-of-day movement intensity by variant (intervention period day 4-9)")
    ax.set_xticks(hours); ax.grid(True, alpha=0.3); ax.legend()
    plt.tight_layout()
    plt.savefig(out / "time_of_day.png", dpi=140)
    plt.close()

    with open(out / "summary.md", "w") as f:
        f.write("# O: Time-of-day movement intensity\n\n")
        f.write("Position-change events per hour, averaged across 3 seeds, intervention period (days 4-9).\n\n")
        f.write("| hour | BL | HP | GD | PF |\n|---|---|---|---|---|\n")
        for h in hours:
            row = [statistics.mean(summary[(s,v)][h] for s in SEED_SUITES) for v in VARIANTS]
            f.write(f"| {h:02d}:00 | {row[0]:.0f} | {row[1]:.0f} | {row[2]:.0f} | {row[3]:.0f} |\n")
    print(f"  → wrote {out}/hour_of_day.json + summary.md + time_of_day.png")


# ──────────────────────────────────────────────────────────────────────
# P: tie strength dynamics
# ──────────────────────────────────────────────────────────────────────
def analysis_p_tie_strength():
    out = OUT_ROOT / "P_tie_strength"
    out.mkdir(exist_ok=True)
    print("=== P: tie strength dynamics ===")
    # Track tie_count_strong / weak / total across 14 days per variant
    series = {(s,v): {"weak":[], "strong":[], "total":[]}
              for s in SEED_SUITES for v in VARIANTS}
    for s in SEED_SUITES:
        for v in VARIANTS:
            p = SEED_SUITES[s] / f"variant_{v}" / f"seed_{s}.json"
            with open(p) as f:
                d = json.load(f)
            for pd in d["run_metrics"].get("per_day", []):
                series[(s,v)]["weak"].append(pd.get("tie_count_weak"))
                series[(s,v)]["strong"].append(pd.get("tie_count_strong"))
                series[(s,v)]["total"].append(pd.get("tie_count_total"))
    with open(out / "tie_series.json", "w") as f:
        json.dump({f"{s}|{v}": x for (s,v), x in series.items()},
                  f, ensure_ascii=False, indent=2)
    # Plot
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    for idx, (kind, ax) in enumerate(zip(["weak","strong","total"], axes)):
        for v in VARIANTS:
            means = []
            for d_idx in range(14):
                vals = [series[(s,v)][kind][d_idx] for s in SEED_SUITES
                        if d_idx < len(series[(s,v)][kind]) and series[(s,v)][kind][d_idx] is not None]
                means.append(statistics.mean(vals) if vals else 0)
            color = {"baseline":"#777","hyperlocal_push":"#d62728",
                     "global_distraction":"#1f77b4","phone_friction":"#2ca02c"}[v]
            ax.plot(range(14), means, marker="o", label=v, color=color, linewidth=2)
        ax.axvspan(3.5, 9.5, alpha=0.1, color="red")
        ax.set_title(f"{kind} ties")
        ax.set_xlabel("day"); ax.set_ylabel("tie count")
        ax.grid(True, alpha=0.3); ax.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(out / "tie_strength_curves.png", dpi=140)
    plt.close()

    with open(out / "summary.md", "w") as f:
        f.write("# P: Tie strength dynamics over 14 days\n\n")
        f.write("Pooled across 3 seeds.\n\n")
        for kind in ["weak","strong","total"]:
            f.write(f"## {kind} ties\n\n")
            f.write("| variant | day 3 (end of baseline) | day 9 (end of intervention) | day 13 (end) | growth d3→d9 | growth d3→d13 |\n")
            f.write("|---|---|---|---|---|---|\n")
            for v in VARIANTS:
                d3 = statistics.mean([series[(s,v)][kind][3] for s in SEED_SUITES
                                      if series[(s,v)][kind][3] is not None])
                d9 = statistics.mean([series[(s,v)][kind][9] for s in SEED_SUITES
                                      if series[(s,v)][kind][9] is not None])
                d13 = statistics.mean([series[(s,v)][kind][13] for s in SEED_SUITES
                                       if series[(s,v)][kind][13] is not None])
                g39 = (d9/d3 if d3 else 0)
                g313 = (d13/d3 if d3 else 0)
                f.write(f"| {v} | {d3:,.0f} | {d9:,.0f} | {d13:,.0f} | {g39:.2f}× | {g313:.2f}× |\n")
            f.write("\n")
    print(f"  → wrote {out}/tie_series.json + summary.md + tie_strength_curves.png")


# ──────────────────────────────────────────────────────────────────────
# Q: encounter pair diversity (use diversity_pairs / total ratio as homophily proxy)
# ──────────────────────────────────────────────────────────────────────
def analysis_q_encounter_diversity():
    out = OUT_ROOT / "Q_encounter_diversity"
    out.mkdir(exist_ok=True)
    print("=== Q: encounter diversity ratio ===")
    summary = {}
    for s in SEED_SUITES:
        for v in VARIANTS:
            p = SEED_SUITES[s] / f"variant_{v}" / f"seed_{s}.json"
            with open(p) as f:
                d = json.load(f)
            rm = d["run_metrics"]
            tot = rm["encounter_stats"]["total"]
            uniq = rm["encounter_stats"]["diversity_pairs_total"]
            summary[(s,v)] = {
                "total_encounters": tot,
                "unique_pairs": uniq,
                "diversity_ratio": uniq / tot if tot else 0,  # higher = more strangers, less repeats
            }
    with open(out / "diversity.json", "w") as f:
        json.dump({f"{s}|{v}": r for (s,v), r in summary.items()}, f, indent=2)
    with open(out / "summary.md", "w") as f:
        f.write("# Q: Encounter diversity (unique_pairs / total)\n\n")
        f.write("Lower ratio = same agents bumping into each other repeatedly (homophilous tunnel).\n")
        f.write("Higher ratio = more distinct strangers met (cross-cluster mixing).\n\n")
        f.write("| variant | total enc | unique pairs | div ratio | per-seed ratio |\n")
        f.write("|---|---|---|---|---|\n")
        for v in VARIANTS:
            t = statistics.mean([summary[(s,v)]["total_encounters"] for s in SEED_SUITES])
            u = statistics.mean([summary[(s,v)]["unique_pairs"] for s in SEED_SUITES])
            r = statistics.mean([summary[(s,v)]["diversity_ratio"] for s in SEED_SUITES])
            per_seed = [summary[(s,v)]["diversity_ratio"] for s in SEED_SUITES]
            f.write(f"| {v} | {t:,.0f} | {u:,.0f} | {r:.4f} | {[f'{x:.4f}' for x in per_seed]} |\n")
    print(f"  → wrote {out}/diversity.json + summary.md")


# ──────────────────────────────────────────────────────────────────────
# R: info propagation depth
# ──────────────────────────────────────────────────────────────────────
def analysis_r_info_propagation():
    out = OUT_ROOT / "R_info_propagation"
    out.mkdir(exist_ok=True)
    print("=== R: info propagation ===")
    summary = {}
    for s in SEED_SUITES:
        for v in VARIANTS:
            p = SEED_SUITES[s] / f"variant_{v}" / f"seed_{s}.json"
            with open(p) as f:
                d = json.load(f)
            rm = d["run_metrics"]
            ip = rm.get("info_propagation_hops", {})
            summary[(s,v)] = {
                "info_count": ip.get("info_count_total"),
                "max_hop": ip.get("max_hop_observed"),
                "info_reaching_2plus": ip.get("info_reaching_2plus_hops"),
                "avg_reach": ip.get("avg_reach_per_info"),
                "info_within_target_reach": ip.get("info_within_target_reach"),
            }
    with open(out / "info.json", "w") as f:
        json.dump({f"{s}|{v}": r for (s,v), r in summary.items()}, f, indent=2)
    with open(out / "summary.md", "w") as f:
        f.write("# R: Information propagation\n\n")
        f.write("| variant | info count | max hop | reach ≥2 hop | avg reach/info |\n|---|---|---|---|---|\n")
        for v in VARIANTS:
            ic = statistics.mean([summary[(s,v)]["info_count"] or 0 for s in SEED_SUITES])
            mh = statistics.mean([summary[(s,v)]["max_hop"] or 0 for s in SEED_SUITES])
            r2 = statistics.mean([summary[(s,v)]["info_reaching_2plus"] or 0 for s in SEED_SUITES])
            ar = statistics.mean([summary[(s,v)]["avg_reach"] or 0 for s in SEED_SUITES])
            f.write(f"| {v} | {ic:.0f} | {mh:.1f} | {r2:.0f} | {ar:.2f} |\n")
    print(f"  → wrote {out}/info.json + summary.md")


# ──────────────────────────────────────────────────────────────────────
# S: REPLAN dynamics (timing + frequency of push-triggered replans)
# ──────────────────────────────────────────────────────────────────────
def analysis_s_replan():
    out = OUT_ROOT / "S_replan_dynamics"
    out.mkdir(exist_ok=True)
    print("=== S: replan dynamics ===")
    summary = {}
    for s in SEED_SUITES:
        for v in VARIANTS:
            p = SEED_SUITES[s] / f"variant_{v}" / f"seed_{s}.json"
            with open(p) as f:
                d = json.load(f)
            rm = d["run_metrics"]
            ex = rm.get("extensions", {})
            replan_by_day = ex.get("replan_by_day", {}) or {}
            no_op_by_day = ex.get("replan_no_op_by_day", {}) or {}
            summary[(s,v)] = {
                "replan_total": ex.get("replan_count"),
                "replan_no_op_total": ex.get("replan_no_op_count"),
                "replan_by_day": replan_by_day,
                "no_op_by_day": no_op_by_day,
            }
    with open(out / "replan.json", "w") as f:
        json.dump({f"{s}|{v}": r for (s,v), r in summary.items()}, f, indent=2)
    # plot replan per day
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(12, 6))
    def _day_val(rby, d_idx):
        if isinstance(rby, dict):
            return rby.get(str(d_idx)) or rby.get(d_idx, 0) or 0
        if isinstance(rby, list) and d_idx < len(rby):
            return rby[d_idx] or 0
        return 0
    for v in VARIANTS:
        means = []
        for d_idx in range(14):
            vals = [_day_val(summary[(s,v)]["replan_by_day"], d_idx) for s in SEED_SUITES]
            means.append(statistics.mean(vals))
        color = {"baseline":"#777","hyperlocal_push":"#d62728",
                 "global_distraction":"#1f77b4","phone_friction":"#2ca02c"}[v]
        ax.plot(range(14), means, marker="o", label=v, color=color, linewidth=2)
    ax.axvspan(3.5, 9.5, alpha=0.1, color="red", label="intervention")
    ax.set_xlabel("day"); ax.set_ylabel("replan events"); ax.grid(True, alpha=0.3); ax.legend()
    ax.set_title("Daily replan events by variant")
    plt.tight_layout()
    plt.savefig(out / "replan_per_day.png", dpi=140)
    plt.close()

    with open(out / "summary.md", "w") as f:
        f.write("# S: Replan dynamics\n\n")
        f.write("Replan events = LLM-triggered plan changes due to interruption.\n\n")
        f.write("| variant | replan_total | replan_no_op | no_op_rate | per-seed total |\n|---|---|---|---|---|\n")
        for v in VARIANTS:
            tots = [summary[(s,v)]["replan_total"] or 0 for s in SEED_SUITES]
            nots = [summary[(s,v)]["replan_no_op_total"] or 0 for s in SEED_SUITES]
            mean_t = statistics.mean(tots); mean_n = statistics.mean(nots)
            no_rate = mean_n/mean_t if mean_t else 0
            f.write(f"| {v} | {mean_t:.0f} | {mean_n:.0f} | {no_rate*100:.1f}% | {tots} |\n")
    print(f"  → wrote {out}/replan.json + summary.md + replan_per_day.png")


def main():
    loc_idx = build_location_index()
    for fn in [lambda: analysis_o_time_of_day(loc_idx),
               analysis_p_tie_strength,
               analysis_q_encounter_diversity,
               analysis_r_info_propagation,
               analysis_s_replan]:
        try: fn()
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"FAILED: {fn}: {e}")
    print("=== O-S batch DONE ===")


if __name__ == "__main__":
    main()
