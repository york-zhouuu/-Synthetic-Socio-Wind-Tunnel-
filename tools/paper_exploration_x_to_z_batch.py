"""[Auto X-Z batch]: workplace-pull analysis, encounter co-presence dispersion, gini concentration."""
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
# X: workplace pull/away analysis
# ──────────────────────────────────────────────────────────────────────
def analysis_x_workplace_pull(loc_idx, profiles_by_seed):
    out = OUT_ROOT / "X_workplace_pull"
    out.mkdir(exist_ok=True)
    print("=== X: workplace pull/away ===")
    # For each agent, find distance from workplace coord to their actual
    # mean location during intervention vs baseline.
    # Hypothesis: HP makes agents AVOID workplace during off-hours? Or visit MORE?
    results = []
    for s in SEED_SUITES:
        profs = profiles_by_seed[s]
        for v in VARIANTS:
            p_path = SEED_SUITES[s] / f"variant_{v}" / f"seed_{s}_positions.json"
            with open(p_path) as f:
                changes = json.load(f)["changes"]
            # build agent -> last_known_location_by_day
            for c in changes:
                pass  # we'll just sample dwell ticks per day
            # Use per_day.location_dwell_ticks (already aggregated)
            seed_json = SEED_SUITES[s] / f"variant_{v}" / f"seed_{s}.json"
            with open(seed_json) as f:
                sd = json.load(f)
            # Per day: how many ticks did each agent spend AT workplace?
            # Without per-agent dwell, we use a proxy: total dwell at workplace
            # locations summed across all agents
            workplace_locs = set()
            for prof in profs.values():
                wl = prof.get("workplace")
                if wl: workplace_locs.add(wl)
            # Sum dwell at workplace locations per day
            workplace_dwell_per_day = []
            for pd in sd["run_metrics"].get("per_day", []):
                t = sum(pd.get("location_dwell_ticks", {}).get(wl, 0) for wl in workplace_locs)
                workplace_dwell_per_day.append(t)
            results.append({
                "seed": s, "variant": v,
                "n_workplace_locs": len(workplace_locs),
                "workplace_dwell_per_day": workplace_dwell_per_day,
                "total_workplace_dwell": sum(workplace_dwell_per_day),
            })
    with open(out / "workplace.json", "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    # Aggregate
    with open(out / "summary.md", "w") as f:
        f.write("# X: Workplace dwell intensity by variant\n\n")
        f.write("Total ticks spent at workplace locations (any agent at any workplace), pooled per day.\n\n")
        f.write("| variant | baseline (d0-3) | intervention (d4-9) | post (d10-13) | int/bl | post/bl |\n")
        f.write("|---|---|---|---|---|---|\n")
        for v in VARIANTS:
            v_rows = [r for r in results if r["variant"]==v]
            bl_totals = [sum(r["workplace_dwell_per_day"][:4]) for r in v_rows]
            int_totals = [sum(r["workplace_dwell_per_day"][4:10]) for r in v_rows]
            post_totals = [sum(r["workplace_dwell_per_day"][10:14]) for r in v_rows]
            bl_m = statistics.mean(bl_totals); int_m = statistics.mean(int_totals)
            post_m = statistics.mean(post_totals)
            f.write(f"| {v} | {bl_m:,.0f} | {int_m:,.0f} | {post_m:,.0f} | "
                    f"{int_m/bl_m if bl_m else 0:.2f}× | "
                    f"{post_m/bl_m if bl_m else 0:.2f}× |\n")
    print(f"  → wrote {out}/workplace.json + summary.md")


# ──────────────────────────────────────────────────────────────────────
# Y: encounter Gini coefficient (inequality of attention)
# ──────────────────────────────────────────────────────────────────────
def analysis_y_gini():
    out = OUT_ROOT / "Y_encounter_gini"
    out.mkdir(exist_ok=True)
    print("=== Y: encounter Gini concentration ===")
    # Per variant: Gini coefficient of dwell distribution across locations
    # Higher Gini = encounter activity concentrated at few locations
    # Lower Gini = encounter activity diffuse across many locations

    def gini(xs):
        sorted_xs = sorted(xs)
        n = len(sorted_xs)
        if n == 0 or sum(sorted_xs) == 0: return 0
        cum_total = sum(sorted_xs)
        cum_sum = 0; gini_sum = 0
        for i, x in enumerate(sorted_xs):
            cum_sum += x
            gini_sum += (i+1) * x
        return (2 * gini_sum) / (n * cum_total) - (n + 1) / n

    summary = {}
    for s in SEED_SUITES:
        for v in VARIANTS:
            p = SEED_SUITES[s] / f"variant_{v}" / f"seed_{s}.json"
            with open(p) as f:
                sd = json.load(f)
            # sum dwell ticks across 14 days per location
            agg = defaultdict(int)
            for pd in sd["run_metrics"].get("per_day", []):
                for loc, t in pd.get("location_dwell_ticks", {}).items():
                    agg[loc] += t
            vals = list(agg.values())
            summary[(s,v)] = {
                "gini": gini(vals),
                "n_locs": len(vals),
                "top_10_pct_share": sum(sorted(vals, reverse=True)[:len(vals)//10]) / sum(vals) if vals else 0,
            }
    with open(out / "gini.json", "w") as f:
        json.dump({f"{s}|{v}": r for (s,v), r in summary.items()}, f, indent=2)
    with open(out / "summary.md", "w") as f:
        f.write("# Y: Encounter activity concentration (Gini coefficient)\n\n")
        f.write("Gini of dwell-ticks distribution across locations.\n")
        f.write("0 = perfectly equal; 1 = all activity at one location.\n")
        f.write("Higher Gini under intervention → activity becomes more concentrated.\n\n")
        f.write("| variant | Gini | top-10% locations share | n locs | per-seed Gini |\n")
        f.write("|---|---|---|---|---|\n")
        for v in VARIANTS:
            ginis = [summary[(s,v)]["gini"] for s in SEED_SUITES]
            tops = [summary[(s,v)]["top_10_pct_share"] for s in SEED_SUITES]
            nlocs = [summary[(s,v)]["n_locs"] for s in SEED_SUITES]
            f.write(f"| {v} | {statistics.mean(ginis):.3f} | "
                    f"{statistics.mean(tops)*100:.1f}% | "
                    f"{statistics.mean(nlocs):.0f} | "
                    f"{[round(g,3) for g in ginis]} |\n")
    print(f"  → wrote {out}/gini.json + summary.md")


# ──────────────────────────────────────────────────────────────────────
# Z: peak-hour shift — when does encounter peak shift between variants?
# ──────────────────────────────────────────────────────────────────────
def analysis_z_peak_hour():
    out = OUT_ROOT / "Z_peak_hour"
    out.mkdir(exist_ok=True)
    print("=== Z: peak-hour shift ===")
    # Use day-level data: encounter_count_total per day, normalize per day
    # For BL/HP/GD/PF, which day-of-week sees the peak?
    summary = {}
    for s in SEED_SUITES:
        for v in VARIANTS:
            p = SEED_SUITES[s] / f"variant_{v}" / f"seed_{s}.json"
            with open(p) as f:
                sd = json.load(f)
            per_day_enc = [pd.get("encounter_count_total", 0)
                           for pd in sd["run_metrics"].get("per_day", [])]
            # day of week — day 0 = Wed (2026-04-22)
            import datetime as dt
            d0 = dt.date(2026, 4, 22)
            by_dow = defaultdict(list)
            for d_idx, e in enumerate(per_day_enc):
                dow = (d0 + dt.timedelta(days=d_idx)).weekday()
                # weekday names: 0=Mon
                by_dow[dow].append(e)
            summary[(s,v)] = {
                "peak_day_of_week": max(by_dow, key=lambda dow: statistics.mean(by_dow[dow])),
                "by_dow_mean": {dow: statistics.mean(es) for dow, es in by_dow.items()},
            }
    DOW_NAMES = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    with open(out / "peak_dow.json", "w") as f:
        json.dump({f"{s}|{v}": r for (s,v), r in summary.items()},
                  f, ensure_ascii=False, indent=2)
    with open(out / "summary.md", "w") as f:
        f.write("# Z: Peak day-of-week per variant\n\n")
        f.write("Mean encounter count per day-of-week across 3 seeds.\n\n")
        f.write("| variant | Mon | Tue | Wed | Thu | Fri | Sat | Sun |\n|---|---|---|---|---|---|---|---|\n")
        for v in VARIANTS:
            dow_means = []
            for dow in range(7):
                vals = [summary[(s,v)]["by_dow_mean"].get(dow,0) for s in SEED_SUITES]
                dow_means.append(statistics.mean(vals))
            f.write(f"| {v} | ")
            f.write(" | ".join(f"{m:,.0f}" for m in dow_means))
            f.write(" |\n")
    print(f"  → wrote {out}/peak_dow.json + summary.md")


def main():
    loc_idx = build_location_index()
    profiles_by_seed = {s: load_profiles(s) for s in SEED_SUITES}
    print(f"loaded atlas={len(loc_idx)}  profiles={sum(len(p) for p in profiles_by_seed.values())}")
    for fn in [lambda: analysis_x_workplace_pull(loc_idx, profiles_by_seed),
               analysis_y_gini,
               analysis_z_peak_hour]:
        try: fn()
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"FAILED")
    print("=== X-Z batch DONE ===")


if __name__ == "__main__":
    main()
