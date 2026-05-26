"""[Auto J-N batch]: Novelty, cost-efficiency, spillover, weekday-weekend, methods variance."""
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
        d = json.load(f)
    return {p["agent_id"]: p for p in d["profiles"]}


def load_changes(seed, variant):
    with open(SEED_SUITES[seed] / f"variant_{variant}" / f"seed_{seed}_positions.json") as f:
        return json.load(f).get("changes", [])


# ──────────────────────────────────────────────────────────────────────
# J: novelty exploration
# ──────────────────────────────────────────────────────────────────────
def analysis_j_novelty():
    out = OUT_ROOT / "J_novelty_exploration"
    out.mkdir(exist_ok=True)
    print("=== J: novelty exploration ===")
    # baseline locations visited during day 0-3 vs intervention day 4-9
    summary = {}
    for s in SEED_SUITES:
        for v in VARIANTS:
            changes = load_changes(s, v)
            agent_baseline_locs = defaultdict(set)  # day 0-3
            agent_int_locs = defaultdict(set)       # day 4-9
            agent_post_locs = defaultdict(set)      # day 10-13
            for c in changes:
                if c["day"] < 4:
                    agent_baseline_locs[c["agent_id"]].add(c["location_id"])
                elif c["day"] < 10:
                    agent_int_locs[c["agent_id"]].add(c["location_id"])
                else:
                    agent_post_locs[c["agent_id"]].add(c["location_id"])
            # For each agent, compute novelty = |int - baseline| / |int|
            novel_count_per_agent = []
            novel_pct_per_agent = []
            for aid in agent_int_locs:
                int_locs = agent_int_locs[aid]
                base_locs = agent_baseline_locs[aid]
                novel = int_locs - base_locs
                novel_count_per_agent.append(len(novel))
                novel_pct_per_agent.append(len(novel) / len(int_locs) if int_locs else 0)
            # And: how many novel locations stuck into post period
            stuck_novel = []
            for aid in agent_post_locs:
                novel_int = agent_int_locs[aid] - agent_baseline_locs[aid]
                still_visited_post = novel_int & agent_post_locs[aid]
                if novel_int:
                    stuck_novel.append(len(still_visited_post) / len(novel_int))
            summary[(s,v)] = {
                "median_novel_locs_per_agent": statistics.median(novel_count_per_agent) if novel_count_per_agent else 0,
                "mean_novel_locs_per_agent": statistics.mean(novel_count_per_agent) if novel_count_per_agent else 0,
                "mean_novel_pct_of_int_visits": statistics.mean(novel_pct_per_agent) if novel_pct_per_agent else 0,
                "mean_stuck_in_post_pct": statistics.mean(stuck_novel) if stuck_novel else 0,
                "n_agents_with_int_visits": len(agent_int_locs),
            }
    with open(out / "novelty.json", "w") as f:
        json.dump({f"{s}|{v}": r for (s,v), r in summary.items()},
                  f, ensure_ascii=False, indent=2)
    with open(out / "summary.md", "w") as f:
        f.write("# J: Novelty exploration during intervention\n\n")
        f.write("- `novel_locs` = locations visited day 4-9 NOT visited day 0-3\n")
        f.write("- `stuck_in_post_pct` = of those novel locs, what fraction revisited day 10-13\n\n")
        f.write("| variant | mean novel locs/agent | mean novel% of visits | mean stuck-in-post% | per-seed (novel locs/agent) |\n")
        f.write("|---|---|---|---|---|\n")
        for v in VARIANTS:
            means_n = [summary[(s,v)]["mean_novel_locs_per_agent"] for s in SEED_SUITES]
            mean_pct_int = [summary[(s,v)]["mean_novel_pct_of_int_visits"] for s in SEED_SUITES]
            mean_stuck = [summary[(s,v)]["mean_stuck_in_post_pct"] for s in SEED_SUITES]
            f.write(f"| {v} | {statistics.mean(means_n):.1f} | "
                    f"{statistics.mean(mean_pct_int)*100:.1f}% | "
                    f"{statistics.mean(mean_stuck)*100:.1f}% | "
                    f"{[f'{m:.1f}' for m in means_n]} |\n")
    print(f"  → wrote {out}/novelty.json + summary.md")


# ──────────────────────────────────────────────────────────────────────
# K: cost efficiency
# ──────────────────────────────────────────────────────────────────────
def analysis_k_cost_efficiency():
    out = OUT_ROOT / "K_cost_efficiency"
    out.mkdir(exist_ok=True)
    print("=== K: cost efficiency ===")
    # Load: cost_total, encounter_total - baseline_encounter, weak_tie_formation, walking distance
    rows = []
    for s in SEED_SUITES:
        cells = {}
        for v in VARIANTS:
            p = SEED_SUITES[s] / f"variant_{v}" / f"seed_{s}.json"
            with open(p) as f:
                d = json.load(f)
            rm = d["run_metrics"]
            cells[v] = {
                "cost_usd": rm.get("cost_breakdown",{}).get("total", 0),
                "encounter_total": rm["encounter_stats"]["total"],
                "encounter_diversity_pairs": rm["encounter_stats"]["diversity_pairs_total"],
                "weak_tie": rm.get("weak_tie_formation_count", 0),
                "dialogue_count": rm.get("dialogue_count", 0),
                "dialogue_live": rm.get("dialogue_live_at_exit", 0),
            }
        bl = cells["baseline"]
        for v in VARIANTS_INT:
            c = cells[v]
            delta_enc = c["encounter_total"] - bl["encounter_total"]
            delta_pairs = c["encounter_diversity_pairs"] - bl["encounter_diversity_pairs"]
            delta_tie = c["weak_tie"] - bl["weak_tie"]
            delta_dial = c["dialogue_live"] - bl["dialogue_live"]
            cost = c["cost_usd"] - bl["cost_usd"]  # incremental cost over BL
            rows.append({
                "seed": s, "variant": v,
                "cost_total_usd": c["cost_usd"],
                "incremental_cost_usd": cost,
                "delta_encounter": delta_enc,
                "delta_diversity_pairs": delta_pairs,
                "delta_weak_tie": delta_tie,
                "delta_dialogue_live": delta_dial,
                "usd_per_extra_encounter": cost/delta_enc if delta_enc > 0 else None,
                "usd_per_extra_diversity_pair": cost/delta_pairs if delta_pairs > 0 else None,
                "usd_per_extra_weak_tie": cost/delta_tie if delta_tie > 0 else None,
                "usd_per_extra_dialogue": cost/delta_dial if delta_dial > 0 else None,
            })
    with open(out / "cost_efficiency.json", "w") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    # Aggregate per variant
    with open(out / "summary.md", "w") as f:
        f.write("# K: Cost efficiency — dollar per social outcome\n\n")
        f.write("Incremental cost = variant total $ − baseline total $.\n\n")
        for v in VARIANTS_INT:
            v_rows = [r for r in rows if r["variant"] == v]
            f.write(f"## {v} (3 seeds)\n\n")
            f.write("| metric | mean | per seed |\n|---|---|---|\n")
            keys = [
                ("incremental_cost_usd", "incremental cost"),
                ("usd_per_extra_encounter", "$/extra encounter (×1000)"),
                ("usd_per_extra_diversity_pair", "$/extra unique pair"),
                ("usd_per_extra_weak_tie", "$/extra weak tie"),
                ("usd_per_extra_dialogue", "$/extra dialogue"),
            ]
            for k, label in keys:
                vals = [r[k] for r in v_rows if r[k] is not None]
                if vals:
                    mean = statistics.mean(vals)
                    if "encounter" in k:
                        mean *= 1000
                    f.write(f"| {label} | {mean:.3f} | {[round(x,4) for x in vals]} |\n")
                else:
                    f.write(f"| {label} | N/A | — |\n")
            f.write("\n")
    print(f"  → wrote {out}/cost_efficiency.json + summary.md")


# ──────────────────────────────────────────────────────────────────────
# L: spillover (geographic peer effect)
# ──────────────────────────────────────────────────────────────────────
def analysis_l_spillover(loc_idx, profiles_by_seed):
    out = OUT_ROOT / "L_spillover"
    out.mkdir(exist_ok=True)
    print("=== L: spillover ===")
    NEIGHBOR_RADIUS = 200.0  # m
    summary = {}
    for v in VARIANTS_INT:
        agent_file = OUT_ROOT / f"C_responder_profile/agents_{v}.json"
        with open(agent_file) as f:
            agents = json.load(f)
        # Index by seed, with home coords
        per_seed = defaultdict(list)
        for r in agents:
            if r.get("home_xy") and r["home_xy"][0] is not None:
                per_seed[r["seed"]].append(r)

        # For each non-protag agent, find protag neighbors within radius
        # Then ask: what's the responder rate of non-protag near protag-responders
        # vs near protag-non-responders?
        n_near_resp = 0; n_near_resp_responders = 0
        n_near_non = 0; n_near_non_responders = 0
        n_far = 0; n_far_responders = 0
        all_pairs_detail = []
        for s, agents_in_seed in per_seed.items():
            protag_agents = [r for r in agents_in_seed if r["is_protagonist"]]
            nonprotag = [r for r in agents_in_seed if not r["is_protagonist"]]
            # For each non-protag, find closest protag
            for npg in nonprotag:
                nx, ny = npg["home_xy"]
                # find protag within radius
                near_protag = []
                for pg in protag_agents:
                    px, py = pg["home_xy"]
                    if math.hypot(nx-px, ny-py) <= NEIGHBOR_RADIUS:
                        near_protag.append(pg)
                if not near_protag:
                    n_far += 1
                    if npg["is_responder"]: n_far_responders += 1
                else:
                    # Has nearby protag — was any of them a responder?
                    any_resp = any(p["is_responder"] for p in near_protag)
                    if any_resp:
                        n_near_resp += 1
                        if npg["is_responder"]: n_near_resp_responders += 1
                    else:
                        n_near_non += 1
                        if npg["is_responder"]: n_near_non_responders += 1
        summary[v] = {
            "neighbor_radius_m": NEIGHBOR_RADIUS,
            "non_protag_near_protag_responder": {
                "n": n_near_resp,
                "responders": n_near_resp_responders,
                "rate": n_near_resp_responders/n_near_resp if n_near_resp else 0,
            },
            "non_protag_near_protag_NON_responder": {
                "n": n_near_non,
                "responders": n_near_non_responders,
                "rate": n_near_non_responders/n_near_non if n_near_non else 0,
            },
            "non_protag_NO_protag_neighbor": {
                "n": n_far,
                "responders": n_far_responders,
                "rate": n_far_responders/n_far if n_far else 0,
            },
        }
    with open(out / "spillover.json", "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    with open(out / "summary.md", "w") as f:
        f.write(f"# L: Spillover — does non-protag respond more if living near protag-responder?\n\n")
        f.write(f"Neighbor radius: {NEIGHBOR_RADIUS}m (home-to-home).\n\n")
        for v, st in summary.items():
            f.write(f"## {v}\n\n")
            f.write("| group | n | responders | rate |\n|---|---|---|---|\n")
            for k, label in [
                ("non_protag_near_protag_responder", "non-protag with ≥1 protag-responder neighbor"),
                ("non_protag_near_protag_NON_responder", "non-protag with only non-responder protag neighbors"),
                ("non_protag_NO_protag_neighbor", "non-protag with no protag within 200m"),
            ]:
                row = st[k]
                f.write(f"| {label} | {row['n']} | {row['responders']} | {row['rate']*100:.1f}% |\n")
            f.write("\n")
    print(f"  → wrote {out}/spillover.json + summary.md")


# ──────────────────────────────────────────────────────────────────────
# M: weekday vs weekend
# ──────────────────────────────────────────────────────────────────────
def analysis_m_weekday():
    out = OUT_ROOT / "M_weekday_weekend"
    out.mkdir(exist_ok=True)
    print("=== M: weekday vs weekend ===")
    # sim_time_start is 2026-04-22 (a Wednesday). So day 0=Wed, day 1=Thu, day 2=Fri,
    # day 3=Sat (weekend), day 4=Sun (weekend), day 5=Mon, ...
    import datetime as dt
    summary = {}
    for s in SEED_SUITES:
        for v in VARIANTS:
            p = SEED_SUITES[s] / f"variant_{v}" / f"seed_{s}.json"
            with open(p) as f:
                d = json.load(f)
            start = d.get("sim_time_start_iso") or d.get("run_metrics",{}).get("sim_time_start_iso")
            # Default
            if not start:
                start = "2026-04-22"
            d0 = dt.date.fromisoformat(start[:10])
            wkday = []; wkend = []
            for pd in d["run_metrics"].get("per_day", []):
                day_date = d0 + dt.timedelta(days=pd["day_index"])
                is_weekend = day_date.weekday() >= 5  # Sat=5, Sun=6
                bucket = wkend if is_weekend else wkday
                bucket.append({
                    "encounter_count": pd.get("encounter_count_total", 0),
                    "distinct_pairs": pd.get("distinct_encounter_pairs", 0),
                    "move_success": pd.get("move_success_count", 0),
                    "new_ties": pd.get("new_ties_today", 0),
                })
            def avg_field(rows, k):
                vs = [r[k] for r in rows if r[k] is not None]
                return statistics.mean(vs) if vs else 0
            summary[(s,v)] = {
                "weekday": {k: avg_field(wkday, k) for k in
                            ["encounter_count","distinct_pairs","move_success","new_ties"]},
                "weekend": {k: avg_field(wkend, k) for k in
                            ["encounter_count","distinct_pairs","move_success","new_ties"]},
            }
    with open(out / "weekday_weekend.json", "w") as f:
        json.dump({f"{s}|{v}": r for (s,v), r in summary.items()},
                  f, ensure_ascii=False, indent=2)
    with open(out / "summary.md", "w") as f:
        f.write(f"# M: Weekday vs weekend split\n\n")
        f.write(f"day 0 = 2026-04-22 (Wed). Weekdays = Mon-Fri; Weekend = Sat-Sun.\n\n")
        for v in VARIANTS:
            f.write(f"## {v}\n\n")
            f.write("| metric | weekday mean | weekend mean | wkend/wkday |\n|---|---|---|---|\n")
            for k in ["encounter_count","distinct_pairs","move_success","new_ties"]:
                wd = statistics.mean([summary[(s,v)]["weekday"][k] for s in SEED_SUITES])
                we = statistics.mean([summary[(s,v)]["weekend"][k] for s in SEED_SUITES])
                ratio = we/wd if wd else 0
                f.write(f"| {k} | {wd:,.0f} | {we:,.0f} | {ratio:.2f}× |\n")
            f.write("\n")
    print(f"  → wrote {out}/weekday_weekend.json + summary.md")


# ──────────────────────────────────────────────────────────────────────
# N: methodological seed 43 vs 44/45
# ──────────────────────────────────────────────────────────────────────
def analysis_n_methods():
    out = OUT_ROOT / "N_methods_variance"
    out.mkdir(exist_ok=True)
    print("=== N: methods variance ===")
    # Compare seed 43 fork vs seed 44/45 fork — what differs about day 0-3 outcome?
    findings = {}
    for s in SEED_SUITES:
        p = SEED_SUITES[s] / "variant_baseline" / f"seed_{s}.json"
        with open(p) as f:
            d = json.load(f)
        rm = d["run_metrics"]
        findings[s] = {
            "code_commit": d.get("variant_metadata") or rm.get("variant_metadata"),
            "encounter_total": rm["encounter_stats"]["total"],
            "weak_tie": rm.get("weak_tie_formation_count"),
            "dialogue_count": rm.get("dialogue_count"),
            "fork_dir_name": str(SEED_SUITES[s].name),
        }
    with open(out / "methods.json", "w") as f:
        json.dump(findings, f, ensure_ascii=False, indent=2)
    with open(out / "summary.md", "w") as f:
        f.write("# N: Methodological notes — seed 43 vs 44/45\n\n")
        f.write("## Fork suite directories\n\n")
        for s, st in findings.items():
            f.write(f"- **seed {s}**: `{st['fork_dir_name']}`\n")
        f.write("\n## Baseline outcome variance (validates protocol)\n\n")
        f.write("| seed | encounter_total | weak_tie | dialogue |\n|---|---|---|---|\n")
        for s, st in findings.items():
            f.write(f"| {s} | {st['encounter_total']:,} | {st['weak_tie']:,} | {st['dialogue_count']:,} |\n")
        f.write("\n## Recommendation\n\n")
        f.write("Trajectory analyses show seed 43 has 3-4× higher per-agent deviation\n"
                "vs seed 44/45. This is because seed 43's baseline-prefix run on\n"
                "2026-05-21 used a different code commit (v6 fork on May 21 vs v7\n"
                "on May 22) and different stochastic seed in the prefix phase.\n\n")
        f.write("For paper-grade analyses, prefer **seed 44 and 45** as the primary\n"
                "reference (same protocol, lower-variance baseline). Use seed 43 for\n"
                "robustness check / triangulation, not as primary numbers.\n")
    print(f"  → wrote {out}/methods.json + summary.md")


def main():
    loc_idx = build_location_index()
    profiles_by_seed = {s: load_profiles(s) for s in SEED_SUITES}
    print(f"loaded atlas={len(loc_idx)}  profiles={sum(len(p) for p in profiles_by_seed.values())}")

    for fn in [analysis_j_novelty, analysis_k_cost_efficiency,
               lambda: analysis_l_spillover(loc_idx, profiles_by_seed),
               analysis_m_weekday, analysis_n_methods]:
        try: fn()
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"failed: {fn}: {e}")
    print("=== J-N batch DONE ===")


if __name__ == "__main__":
    main()
