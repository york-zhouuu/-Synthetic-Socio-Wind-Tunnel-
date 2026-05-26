"""[Auto T-W batch]: case study agents, cross-cohort tie formation, encounter co-location,
deeper stickiness analysis."""
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
# T: Case study — track 5 exemplar agents day-by-day
# ──────────────────────────────────────────────────────────────────────
def analysis_t_case_studies(loc_idx, profiles_by_seed):
    out = OUT_ROOT / "T_case_studies"
    out.mkdir(exist_ok=True)
    print("=== T: case studies ===")
    # Load agents data with deviations
    with open(OUT_ROOT / "C_responder_profile/agents_hyperlocal_push.json") as f:
        hp_agents = json.load(f)
    # Pick 5 archetypes
    high_resp = sorted([r for r in hp_agents if r["is_responder"]],
                       key=lambda r: -r["deviation_m"])[:1]
    non_resp = [r for r in hp_agents if not r["is_responder"]
                and r["is_protagonist"]][:1]
    spillover = sorted([r for r in hp_agents if r["is_responder"]
                        and not r["is_protagonist"]],
                       key=lambda r: -r["deviation_m"])[:1]
    median_resp = sorted([r for r in hp_agents if r["is_responder"]],
                         key=lambda r: r["deviation_m"])[len([r for r in hp_agents if r["is_responder"]])//2:][:1]
    # also 1 GD responder
    with open(OUT_ROOT / "C_responder_profile/agents_global_distraction.json") as f:
        gd_agents = json.load(f)
    gd_top = sorted([r for r in gd_agents if r["is_responder"]],
                    key=lambda r: -r["deviation_m"])[:1]

    cases = []
    for label, source, agents_list in [
        ("HIGH responder (protag, biggest deviation)", "HP", high_resp),
        ("MEDIAN responder (protag)", "HP", median_resp),
        ("SPILLOVER responder (non-protag)", "HP", spillover),
        ("NON-responder (protag)", "HP", non_resp),
        ("GD-top responder", "GD", gd_top),
    ]:
        if not agents_list: continue
        a = agents_list[0]
        seed = a["seed"]
        variant = "hyperlocal_push" if source == "HP" else "global_distraction"
        prof = profiles_by_seed[seed].get(a["agent_id"], {})
        # Load positions for this agent
        pos_var = SEED_SUITES[seed] / f"variant_{variant}" / f"seed_{seed}_positions.json"
        pos_bl  = SEED_SUITES[seed] / "variant_baseline" / f"seed_{seed}_positions.json"
        with open(pos_var) as f:
            var_changes = [c for c in json.load(f)["changes"] if c["agent_id"] == a["agent_id"]]
        with open(pos_bl) as f:
            bl_changes = [c for c in json.load(f)["changes"] if c["agent_id"] == a["agent_id"]]
        cases.append({
            "label": label,
            "source_variant": variant,
            "seed": seed,
            "agent_id": a["agent_id"],
            "deviation_m": a["deviation_m"],
            "is_responder": a["is_responder"],
            "profile": {
                "name": prof.get("name"), "age": prof.get("age"),
                "gender": prof.get("gender"), "occupation": prof.get("occupation"),
                "household": prof.get("household"), "role": prof.get("household_role"),
                "income_tier": prof.get("income_tier"),
                "is_protagonist": prof.get("is_protagonist"),
                "home_location": prof.get("home_location"),
                "workplace": prof.get("workplace"),
                "personality": prof.get("personality"),
                "identity_text": (prof.get("identity_text") or "")[:300],
                "life_pattern": (prof.get("life_pattern") or "")[:200] if isinstance(prof.get("life_pattern"),str) else prof.get("life_pattern"),
            },
            "n_var_changes": len(var_changes),
            "n_bl_changes": len(bl_changes),
            "var_changes_sample": var_changes[:30],
            "bl_changes_sample": bl_changes[:30],
        })

    with open(out / "case_studies.json", "w") as f:
        json.dump(cases, f, ensure_ascii=False, indent=2)

    # Markdown narrative
    with open(out / "summary.md", "w") as f:
        f.write("# T: Case-study agents\n\n")
        f.write("5 exemplar agents tracked through their 14-day journey.\n\n")
        for c in cases:
            p = c["profile"]
            f.write(f"## {c['label']}\n\n")
            f.write(f"- **Agent**: `{c['agent_id']}` (seed {c['seed']}, {c['source_variant']})\n")
            f.write(f"- **Demographics**: {p.get('age')}yo {p.get('gender')} {p.get('occupation')}, "
                    f"{p.get('household')} ({p.get('role')}), income: {p.get('income_tier')}\n")
            f.write(f"- **Protagonist**: {p.get('is_protagonist')}\n")
            f.write(f"- **Home**: `{p.get('home_location')}`  /  **Work**: `{p.get('workplace')}`\n")
            f.write(f"- **Mean deviation**: {c['deviation_m']:.1f}m  /  Responder: {c['is_responder']}\n")
            pers = p.get("personality") or {}
            if isinstance(pers, dict):
                f.write(f"- **Personality**: extraversion {pers.get('extraversion',0):.2f}, "
                        f"openness {pers.get('openness',0):.2f}, "
                        f"curiosity {pers.get('curiosity',0):.2f}, "
                        f"routine_adherence {pers.get('routine_adherence',0):.2f}\n")
            f.write(f"- **Identity text**: {p.get('identity_text','')}\n\n")
            f.write(f"- **Position changes**: variant run={c['n_var_changes']}, "
                    f"baseline run={c['n_bl_changes']}\n\n")
            f.write("\n")
    print(f"  → wrote {out}/case_studies.json + summary.md")


# ──────────────────────────────────────────────────────────────────────
# U: cross-cohort tie analysis
# ──────────────────────────────────────────────────────────────────────
def analysis_u_cross_cohort(profiles_by_seed):
    out = OUT_ROOT / "U_cross_cohort"
    out.mkdir(exist_ok=True)
    print("=== U: cross-cohort analysis ===")
    # For each variant, examine encounter dwell-location decomposition
    # cross-tabulated with agent demographics — proxy: where did each demographic
    # cohort spend more time?
    # Simpler: read end_of_day_location_by_agent per day, count
    # which demographic cohorts ended up at the same location.
    # For 14 days × 1000 agents × 4 variants, this is feasible.

    co_loc = {}
    for s in SEED_SUITES:
        profs = profiles_by_seed[s]
        for v in VARIANTS:
            p = SEED_SUITES[s] / f"variant_{v}" / f"seed_{s}.json"
            with open(p) as f:
                sd = json.load(f)
            # Count: per location_id, how many distinct (age_bucket, occupation) tuples ended there per day
            location_demo_diversity = []
            for pd_idx, pd in enumerate(sd["run_metrics"]["per_day"]):
                eod_loc = pd.get("end_of_day_location_by_agent", {}) or {}
                # location -> set of (age_bucket, occupation)
                loc_demos = defaultdict(set)
                for aid, loc in eod_loc.items():
                    prof = profs.get(aid, {})
                    age = prof.get("age", 0)
                    occ = prof.get("occupation", "?")
                    age_bucket = ("18-24" if age<25 else "25-34" if age<35 else
                                  "35-49" if age<50 else "50-64" if age<65 else "65+")
                    loc_demos[loc].add((age_bucket, occ))
                diversity = [len(s) for s in loc_demos.values()]
                if diversity:
                    location_demo_diversity.append({
                        "day": pd_idx,
                        "n_locations": len(loc_demos),
                        "median_diversity": statistics.median(diversity),
                        "max_diversity": max(diversity),
                    })
            co_loc[(s,v)] = location_demo_diversity

    # Aggregate
    with open(out / "demo_diversity_per_loc.json", "w") as f:
        json.dump({f"{s}|{v}": d for (s,v), d in co_loc.items()},
                  f, ensure_ascii=False, indent=2)
    with open(out / "summary.md", "w") as f:
        f.write("# U: Cross-cohort co-location analysis\n\n")
        f.write("Per location_id (end-of-day), count distinct (age_bucket, occupation) tuples.\n")
        f.write("Higher diversity = more demographic mixing at that location.\n\n")
        f.write("| variant | mean median_diversity | mean max_diversity | mean n_locations |\n")
        f.write("|---|---|---|---|\n")
        for v in VARIANTS:
            md_vals = []; max_vals = []; nl_vals = []
            for s in SEED_SUITES:
                for entry in co_loc[(s,v)]:
                    md_vals.append(entry["median_diversity"])
                    max_vals.append(entry["max_diversity"])
                    nl_vals.append(entry["n_locations"])
            f.write(f"| {v} | {statistics.mean(md_vals):.2f} | "
                    f"{statistics.mean(max_vals):.1f} | "
                    f"{statistics.mean(nl_vals):.0f} |\n")
    print(f"  → wrote {out}/demo_diversity_per_loc.json + summary.md")


# ──────────────────────────────────────────────────────────────────────
# V: Encounter location-type by repeat vs unique (use Q's diversity ratio)
# already covered. Skip / placeholder
# ──────────────────────────────────────────────────────────────────────
def analysis_v_repeat_vs_unique():
    """Note: this is conceptual — full impl needs per-encounter event log.
    Provide partial via dwell location buckets weighted by total vs unique encounters."""
    out = OUT_ROOT / "V_repeat_vs_unique"
    out.mkdir(exist_ok=True)
    print("=== V: repeat vs unique encounters ===")
    # Already have:
    # - dwell location decomposition (F)
    # - total encounters / diversity pairs (Q)
    # Derived metric: encounter intensity per location type
    rows = []
    for s in SEED_SUITES:
        for v in VARIANTS:
            p = SEED_SUITES[s] / f"variant_{v}" / f"seed_{s}.json"
            with open(p) as f:
                sd = json.load(f)
            rm = sd["run_metrics"]
            tot = rm["encounter_stats"]["total"]
            uniq = rm["encounter_stats"]["diversity_pairs_total"]
            # repeats per pair = tot / uniq
            rows.append({
                "seed": s, "variant": v,
                "total_encounters": tot,
                "unique_pairs": uniq,
                "avg_repeats_per_pair": tot/uniq if uniq else 0,
            })
    with open(out / "repeats.json", "w") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    with open(out / "summary.md", "w") as f:
        f.write("# V: Repeat encounters per unique pair (proxy for tie strengthening)\n\n")
        f.write("avg_repeats_per_pair = total_encounters / unique_pairs.\n")
        f.write("Higher = same people bump more (relationship deepening).\n\n")
        f.write("| variant | mean repeats/pair | per-seed |\n|---|---|---|\n")
        for v in VARIANTS:
            vrows = [r for r in rows if r["variant"]==v]
            avg = statistics.mean([r["avg_repeats_per_pair"] for r in vrows])
            ps = [r["avg_repeats_per_pair"] for r in vrows]
            f.write(f"| {v} | {avg:.1f} | {[f'{x:.1f}' for x in ps]} |\n")
    print(f"  → wrote {out}/repeats.json + summary.md")


# ──────────────────────────────────────────────────────────────────────
# W: deeper stickiness — compare actual walking + diversity in INT vs POST
# ──────────────────────────────────────────────────────────────────────
def analysis_w_deeper_stickiness(loc_idx):
    out = OUT_ROOT / "W_deeper_stickiness"
    out.mkdir(exist_ok=True)
    print("=== W: deeper stickiness ===")
    # Compare per-variant int vs post on multiple metrics
    summary = {}
    for s in SEED_SUITES:
        for v in VARIANTS:
            p = SEED_SUITES[s] / f"variant_{v}" / f"seed_{s}.json"
            with open(p) as f:
                sd = json.load(f)
            # Per-day metrics
            int_days = []
            post_days = []
            for pd in sd["run_metrics"]["per_day"]:
                d = pd["day_index"]
                if 4 <= d <= 9:
                    int_days.append(pd)
                elif 10 <= d <= 13:
                    post_days.append(pd)
            # Mean per metric
            metrics_to_check = ["encounter_count_total", "distinct_encounter_pairs",
                                "new_ties_today", "move_success_count",
                                "info_origins_today"]
            summary[(s,v)] = {}
            for m in metrics_to_check:
                int_vals = [pd.get(m) for pd in int_days if pd.get(m) is not None]
                post_vals = [pd.get(m) for pd in post_days if pd.get(m) is not None]
                if int_vals and post_vals:
                    int_mean = statistics.mean(int_vals)
                    post_mean = statistics.mean(post_vals)
                    summary[(s,v)][m] = {
                        "int_mean": int_mean,
                        "post_mean": post_mean,
                        "post_minus_int": post_mean - int_mean,
                        "post_to_int_ratio": post_mean/int_mean if int_mean else 0,
                    }
    with open(out / "stickiness_deep.json", "w") as f:
        json.dump({f"{s}|{v}": x for (s,v), x in summary.items()},
                  f, ensure_ascii=False, indent=2)
    with open(out / "summary.md", "w") as f:
        f.write("# W: Deeper stickiness — multi-metric INT vs POST comparison\n\n")
        f.write("Per-metric mean comparison: intervention (day 4-9) vs post (day 10-13).\n")
        f.write("`post/int_ratio` > 1: effect persists or grows. < 1: revert toward baseline.\n\n")
        for m in ["encounter_count_total", "distinct_encounter_pairs",
                  "new_ties_today", "move_success_count"]:
            f.write(f"## {m}\n\n")
            f.write("| variant | INT mean | POST mean | post/int ratio | mean over seeds |\n")
            f.write("|---|---|---|---|---|\n")
            for v in VARIANTS:
                ratios = []
                int_means = []
                post_means = []
                for s in SEED_SUITES:
                    st = summary[(s,v)].get(m)
                    if st:
                        ratios.append(st["post_to_int_ratio"])
                        int_means.append(st["int_mean"])
                        post_means.append(st["post_mean"])
                if ratios:
                    avg_r = statistics.mean(ratios)
                    avg_i = statistics.mean(int_means); avg_p = statistics.mean(post_means)
                    f.write(f"| {v} | {avg_i:,.0f} | {avg_p:,.0f} | {avg_r:.2f}× | "
                            f"{[round(r,2) for r in ratios]} |\n")
            f.write("\n")
    print(f"  → wrote {out}/stickiness_deep.json + summary.md")


def main():
    loc_idx = build_location_index()
    profiles_by_seed = {s: load_profiles(s) for s in SEED_SUITES}
    print(f"loaded atlas={len(loc_idx)}  profiles={sum(len(p) for p in profiles_by_seed.values())}")
    for fn in [lambda: analysis_t_case_studies(loc_idx, profiles_by_seed),
               lambda: analysis_u_cross_cohort(profiles_by_seed),
               analysis_v_repeat_vs_unique,
               lambda: analysis_w_deeper_stickiness(loc_idx)]:
        try: fn()
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"FAILED: {fn}")
    print("=== T-W batch DONE ===")


if __name__ == "__main__":
    main()
