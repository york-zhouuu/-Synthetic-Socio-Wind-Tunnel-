"""[Auto D-I batch] 6 follow-on analyses using positions.json + atlas + profiles.

D: walking footprint (total distance) per variant per day
E: location diversity (unique locs visited) per agent
F: encounter location-type decomposition
G: habit stickiness (intervention vs post deviation per responder)
H: personality correlates with response
I: home-to-target distance vs responder rate
"""
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
    43: "08d79c69cc045b32.json",
    44: "7cf41bf8960a72d8.json",
    45: "39fa81f5889f6d8b.json",
}
VARIANTS = ["baseline", "hyperlocal_push", "global_distraction", "phone_friction"]
VARIANTS_INT = ["hyperlocal_push", "global_distraction", "phone_friction"]

sys.path.insert(0, str(REPO / "tools"))
from backfill_publishable_metrics import (
    build_location_index,
    _build_agent_tick_position_table,
    _agent_position_at_tick,
)

DWELL_BUCKETS = {
    "residential":   {"residential"},
    "commercial":    {"shop","restaurant","cafe","bar","hotel","office","commercial",
                      "hospital","school","entertainment","community","worship",
                      "utility","industrial"},
    "public_outdoor": {"outdoor_park","outdoor_playground","outdoor_garden"},
    "street":        {"outdoor_street"},
}

def bucket_for(loc_type):
    for b, types in DWELL_BUCKETS.items():
        if loc_type in types:
            return b
    return "unknown"


def load_profiles(seed):
    with open(REPO / f"data/population_cache/v1/{SEED_POPCACHE[seed]}") as f:
        d = json.load(f)
    return {p["agent_id"]: p for p in d["profiles"]}


# ──────────────────────────────────────────────────────────────────────
# D: walking footprint
# ──────────────────────────────────────────────────────────────────────
def analysis_d_walking_footprint(loc_idx, profiles_by_seed):
    out = OUT_ROOT / "D_walking_footprint"
    out.mkdir(exist_ok=True)
    print("=== D: walking footprint ===")
    # Per (seed, variant), per agent, sum distance over consecutive location changes
    # Then aggregate per day per variant per seed
    results = {}
    for s in SEED_SUITES:
        for v in VARIANTS:
            p_path = SEED_SUITES[s] / f"variant_{v}" / f"seed_{s}_positions.json"
            with open(p_path) as f:
                pdata = json.load(f)
            changes = pdata.get("changes", [])
            # Group by agent
            by_agent = defaultdict(list)
            for c in changes:
                by_agent[c["agent_id"]].append((c["tick"], c["day"], c["location_id"]))
            for aid in by_agent:
                by_agent[aid].sort()
            # Per-agent total distance per day
            per_day_agent_dist = defaultdict(lambda: defaultdict(float))  # day -> agent -> dist
            for aid, evts in by_agent.items():
                for i in range(1, len(evts)):
                    _, day, loc_b = evts[i-1]
                    _, day_now, loc_a = evts[i]
                    if loc_b in loc_idx and loc_a in loc_idx:
                        cb = loc_idx[loc_b]["coord"]; ca = loc_idx[loc_a]["coord"]
                        d = math.hypot(ca[0]-cb[0], ca[1]-cb[1])
                        per_day_agent_dist[day_now][aid] += d
            results[(s,v)] = {
                "total_m_per_day": {d: sum(ds.values()) for d, ds in per_day_agent_dist.items()},
                "median_m_per_agent_per_day": {
                    d: statistics.median(list(ds.values())+[0]*(1000-len(ds)))
                    for d, ds in per_day_agent_dist.items()
                },
                "agents_with_movement": {d: len(ds) for d, ds in per_day_agent_dist.items()},
            }
    # JSON dump
    with open(out / "walking_per_day.json", "w") as f:
        json.dump({f"{s}|{v}": r for (s,v), r in results.items()},
                  f, ensure_ascii=False, indent=2)

    # Aggregate variant table: mean total distance over 14 days
    table = {}
    for v in VARIANTS:
        totals = []
        for s in SEED_SUITES:
            day_totals = results[(s,v)]["total_m_per_day"]
            totals.append(sum(day_totals.values()))
        table[v] = {
            "mean_total_m_over_14days": statistics.mean(totals),
            "per_seed": totals,
        }
    with open(out / "summary.md", "w") as f:
        f.write("# D: Walking footprint (total meters traveled across 1000 agents × 14 days)\n\n")
        f.write("| variant | mean total (km) | per seed (km) | vs BL |\n")
        f.write("|---|---|---|---|\n")
        bl_mean = table["baseline"]["mean_total_m_over_14days"]
        for v in VARIANTS:
            mean_km = table[v]["mean_total_m_over_14days"] / 1000
            per_seed_km = [t/1000 for t in table[v]["per_seed"]]
            ratio = table[v]["mean_total_m_over_14days"] / bl_mean
            f.write(f"| {v} | {mean_km:,.0f} | {[f'{t:.0f}' for t in per_seed_km]} | {ratio:.2f}× |\n")
    print(f"  → wrote {out}/walking_per_day.json + summary.md")
    return table


# ──────────────────────────────────────────────────────────────────────
# E: location diversity
# ──────────────────────────────────────────────────────────────────────
def analysis_e_diversity(loc_idx, profiles_by_seed):
    out = OUT_ROOT / "E_location_diversity"
    out.mkdir(exist_ok=True)
    print("=== E: location diversity ===")
    results = {}
    for s in SEED_SUITES:
        for v in VARIANTS:
            p_path = SEED_SUITES[s] / f"variant_{v}" / f"seed_{s}_positions.json"
            with open(p_path) as f:
                pdata = json.load(f)
            # agent -> set of distinct location_ids EVER visited
            by_agent = defaultdict(set)
            # day -> agent -> set of locations visited that day
            day_agent = defaultdict(lambda: defaultdict(set))
            for c in pdata["changes"]:
                by_agent[c["agent_id"]].add(c["location_id"])
                day_agent[c["day"]][c["agent_id"]].add(c["location_id"])
            results[(s,v)] = {
                "median_unique_locs_per_agent_total": statistics.median(
                    [len(s) for s in by_agent.values()] + [0]*(1000-len(by_agent))),
                "mean_unique_locs_per_agent_total": statistics.mean(
                    [len(s) for s in by_agent.values()] + [0]*(1000-len(by_agent))),
                "per_day_median_unique": {
                    d: statistics.median([len(s) for s in das.values()] + [0]*(1000-len(das)))
                    for d, das in day_agent.items()
                },
            }
    with open(out / "diversity.json", "w") as f:
        json.dump({f"{s}|{v}": r for (s,v), r in results.items()},
                  f, ensure_ascii=False, indent=2)
    # Summary
    with open(out / "summary.md", "w") as f:
        f.write("# E: Location diversity (distinct locs visited per agent across 14 days)\n\n")
        f.write("| variant | mean unique locs/agent (over 14d) | per seed |\n")
        f.write("|---|---|---|\n")
        for v in VARIANTS:
            means = [results[(s,v)]["mean_unique_locs_per_agent_total"] for s in SEED_SUITES]
            f.write(f"| {v} | {statistics.mean(means):.1f} | {[f'{m:.1f}' for m in means]} |\n")
    print(f"  → wrote {out}/diversity.json + summary.md")


# ──────────────────────────────────────────────────────────────────────
# F: encounter location shift (from per_day.location_dwell_ticks proxy)
# ──────────────────────────────────────────────────────────────────────
def analysis_f_encounter_locations(loc_idx, profiles_by_seed):
    out = OUT_ROOT / "F_encounter_locations"
    out.mkdir(exist_ok=True)
    print("=== F: encounter locations ===")
    # Use per_day location_dwell_ticks as proxy for "where encounters happen" —
    # since encounters require co-presence, total dwell ticks at a location
    # bounds encounter potential. Bucket by type.
    results = {}
    for s in SEED_SUITES:
        for v in VARIANTS:
            p = SEED_SUITES[s] / f"variant_{v}" / f"seed_{s}.json"
            with open(p) as f:
                sd = json.load(f)
            buckets = defaultdict(int)
            for pd in sd["run_metrics"].get("per_day", []):
                for loc, ticks in pd.get("location_dwell_ticks", {}).items():
                    t = loc_idx.get(loc, {}).get("type", "unknown")
                    b = bucket_for(t)
                    buckets[b] += ticks
            total = sum(buckets.values()) or 1
            results[(s,v)] = {b: v/total for b, v in buckets.items()}
    with open(out / "encounter_locations.json", "w") as f:
        json.dump({f"{s}|{v}": r for (s,v), r in results.items()},
                  f, ensure_ascii=False, indent=2)
    # Summary
    with open(out / "summary.md", "w") as f:
        f.write("# F: Co-presence/encounter location decomposition\n\n")
        f.write("Percent of total dwell ticks (= encounter potential) by location type\n\n")
        f.write("| variant | residential | commercial | public_outdoor | street | unknown |\n")
        f.write("|---|---|---|---|---|---|\n")
        for v in VARIANTS:
            means = {b: statistics.mean(results[(s,v)].get(b,0) for s in SEED_SUITES)
                     for b in ["residential","commercial","public_outdoor","street","unknown"]}
            f.write(f"| {v} | {means['residential']*100:.1f}% | "
                    f"{means['commercial']*100:.1f}% | "
                    f"{means['public_outdoor']*100:.1f}% | "
                    f"{means['street']*100:.1f}% | "
                    f"{means['unknown']*100:.1f}% |\n")
    print(f"  → wrote {out}/encounter_locations.json + summary.md")


# ──────────────────────────────────────────────────────────────────────
# G: habit stickiness — compare intervention vs post deviation
# ──────────────────────────────────────────────────────────────────────
def analysis_g_stickiness(loc_idx, profiles_by_seed):
    out = OUT_ROOT / "G_habit_stickiness"
    out.mkdir(exist_ok=True)
    print("=== G: habit stickiness ===")

    def per_agent_dev(seed, variant, days):
        base = SEED_SUITES[seed] / "variant_baseline" / f"seed_{seed}_positions.json"
        self = SEED_SUITES[seed] / f"variant_{variant}" / f"seed_{seed}_positions.json"
        base_t = _build_agent_tick_position_table(base)
        self_t = _build_agent_tick_position_table(self)
        per_agent = {}
        for aid in set(base_t) & set(self_t):
            dists = []
            for d in days:
                for t in range(d*288, (d+1)*288, 12):
                    l_s = _agent_position_at_tick(self_t[aid], t)
                    l_b = _agent_position_at_tick(base_t[aid], t)
                    if l_s and l_b and l_s in loc_idx and l_b in loc_idx:
                        cs = loc_idx[l_s]["coord"]; cb = loc_idx[l_b]["coord"]
                        dists.append(math.hypot(cs[0]-cb[0], cs[1]-cb[1]))
            per_agent[aid] = statistics.mean(dists) if dists else 0.0
        return per_agent

    INT_DAYS = list(range(4,10))
    POST_DAYS = list(range(10,14))
    summary = {}
    for s in SEED_SUITES:
        for v in VARIANTS_INT:
            int_dev = per_agent_dev(s, v, INT_DAYS)
            post_dev = per_agent_dev(s, v, POST_DAYS)
            # responders = >20m during intervention
            responders = {aid for aid, d in int_dev.items() if d > 20.0}
            non_resp = set(int_dev) - responders
            r_post = [post_dev.get(aid,0) for aid in responders]
            n_post = [post_dev.get(aid,0) for aid in non_resp]
            r_int = [int_dev[aid] for aid in responders]
            summary[(s,v)] = {
                "n_responders": len(responders),
                "n_non_responders": len(non_resp),
                "responder_int_mean": statistics.mean(r_int) if r_int else 0,
                "responder_post_mean": statistics.mean(r_post) if r_post else 0,
                "post/intervention_ratio": (statistics.mean(r_post)/statistics.mean(r_int)) if r_int and statistics.mean(r_int)>0 else 0,
                "non_responder_post_mean": statistics.mean(n_post) if n_post else 0,
            }
    with open(out / "stickiness.json", "w") as f:
        json.dump({f"{s}|{v}": r for (s,v), r in summary.items()},
                  f, ensure_ascii=False, indent=2)
    with open(out / "summary.md", "w") as f:
        f.write("# G: Habit stickiness — responders' deviation in post-period vs intervention\n\n")
        f.write("Responder threshold: >20m mean deviation during day 4-9.\n")
        f.write("`post/intervention_ratio` = mean post-period dev ÷ mean intervention dev.\n")
        f.write("> 1.0 = MORE deviation after intervention stopped (sticky habit / network effect)\n")
        f.write("< 1.0 = revert toward baseline (transient effect)\n\n")
        f.write("| seed | variant | n_responders | int_dev_m | post_dev_m | ratio | non_resp_post_dev |\n")
        f.write("|---|---|---|---|---|---|---|\n")
        for (s,v), r in summary.items():
            f.write(f"| {s} | {v} | {r['n_responders']} | {r['responder_int_mean']:.1f} | "
                    f"{r['responder_post_mean']:.1f} | {r['post/intervention_ratio']:.2f}× | "
                    f"{r['non_responder_post_mean']:.1f} |\n")
    print(f"  → wrote {out}/stickiness.json + summary.md")


# ──────────────────────────────────────────────────────────────────────
# H: personality correlates
# ──────────────────────────────────────────────────────────────────────
def analysis_h_personality(loc_idx, profiles_by_seed):
    out = OUT_ROOT / "H_personality"
    out.mkdir(exist_ok=True)
    print("=== H: personality correlates ===")
    # For each variant, load agents_<variant>.json and compute correlations
    import math as m
    rows_by_variant = {}
    for v in VARIANTS_INT:
        agent_file = OUT_ROOT / f"C_responder_profile/agents_{v}.json"
        if not agent_file.exists():
            continue
        with open(agent_file) as f:
            agents = json.load(f)
        # also load full personality from profiles
        for r in agents:
            prof = profiles_by_seed.get(r["seed"], {}).get(r["agent_id"], {})
            p = prof.get("personality", {})
            r.update({
                "openness": p.get("openness"),
                "conscientiousness": p.get("conscientiousness"),
                "extraversion": p.get("extraversion"),
                "agreeableness": p.get("agreeableness"),
                "neuroticism": p.get("neuroticism"),
                "curiosity": p.get("curiosity"),
                "routine_adherence": p.get("routine_adherence"),
                "risk_tolerance": p.get("risk_tolerance"),
            })
        rows_by_variant[v] = agents

    # Pearson correlation for each big5/extension trait vs deviation_m
    def pearson(xs, ys):
        n = len(xs)
        if n < 2: return None
        mx = sum(xs)/n; my = sum(ys)/n
        nu = sum((x-mx)*(y-my) for x,y in zip(xs,ys))
        sx = m.sqrt(sum((x-mx)**2 for x in xs))
        sy = m.sqrt(sum((y-my)**2 for y in ys))
        return nu / (sx * sy) if sx*sy else None

    summary = {}
    for v, agents in rows_by_variant.items():
        summary[v] = {}
        for trait in ["openness","conscientiousness","extraversion","agreeableness",
                      "neuroticism","curiosity","routine_adherence","risk_tolerance"]:
            xs = []; ys = []
            for r in agents:
                if r.get(trait) is not None:
                    xs.append(r[trait]); ys.append(r["deviation_m"])
            summary[v][trait] = {"r": pearson(xs, ys), "n": len(xs)}
    with open(out / "personality_correlations.json", "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    with open(out / "summary.md", "w") as f:
        f.write("# H: Personality trait correlations with trajectory deviation\n\n")
        f.write("Pearson r between trait (0-1) and per-agent mean deviation (m) during intervention.\n\n")
        for v in VARIANTS_INT:
            f.write(f"## {v}\n\n| trait | Pearson r | n |\n|---|---|---|\n")
            for trait, st in summary[v].items():
                r_val = st["r"]
                r_str = f"{r_val:.3f}" if r_val is not None else "N/A"
                f.write(f"| {trait} | {r_str} | {st['n']} |\n")
            f.write("\n")
    print(f"  → wrote {out}/personality_correlations.json + summary.md")


# ──────────────────────────────────────────────────────────────────────
# I: home-to-target distance
# ──────────────────────────────────────────────────────────────────────
def analysis_i_proximity(loc_idx, profiles_by_seed):
    out = OUT_ROOT / "I_proximity_to_targets"
    out.mkdir(exist_ok=True)
    print("=== I: home-to-target proximity ===")
    # For each variant, use the "top activated" POIs as targets, then for each agent
    # compute distance from home to nearest activated target.
    # Load activation data from analysis A
    with open(OUT_ROOT / "A_poi_activation/activation_per_location.json") as f:
        a_data = json.load(f)
    summary = {}
    for v in VARIANTS_INT:
        acts = list(a_data["activation_vs_baseline"][v].values())
        # Pick "targets" = top 30 most activated locations with abs delta > 100 ticks
        targets = sorted(
            [a for a in acts if a["activation_pct"] > 20 and a["abs_delta"] > 100],
            key=lambda r: -r["activation_pct"])[:50]
        target_coords = [(t["x"], t["y"]) for t in targets if t["x"] is not None]
        if not target_coords:
            summary[v] = {"error": "no targets"}; continue

        # Load this variant's agents file
        with open(OUT_ROOT / f"C_responder_profile/agents_{v}.json") as f:
            agents = json.load(f)
        # Bin agents by distance to nearest target
        rows = []
        for r in agents:
            hx = r.get("home_xy")
            if not hx or hx[0] is None: continue
            min_d = min(math.hypot(hx[0]-tx, hx[1]-ty) for tx,ty in target_coords)
            rows.append({"agent_id": r["agent_id"], "seed": r["seed"],
                         "home_to_nearest_target_m": min_d,
                         "is_responder": r["is_responder"],
                         "is_protagonist": r["is_protagonist"]})
        # Bin by distance
        bins = [(0,200),(200,400),(400,600),(600,800),(800,1000),(1000,1500),(1500,99999)]
        binned = {f"{lo}-{hi}m": {"total":0,"responders":0,"protag_total":0,"protag_resp":0}
                  for lo,hi in bins}
        for rr in rows:
            for lo,hi in bins:
                if lo <= rr["home_to_nearest_target_m"] < hi:
                    k = f"{lo}-{hi}m"
                    binned[k]["total"] += 1
                    if rr["is_responder"]: binned[k]["responders"] += 1
                    if rr["is_protagonist"]:
                        binned[k]["protag_total"] += 1
                        if rr["is_responder"]: binned[k]["protag_resp"] += 1
                    break
        summary[v] = {"n_targets": len(targets), "binned": binned}
    with open(out / "proximity.json", "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    with open(out / "summary.md", "w") as f:
        f.write("# I: Home-to-target distance effect on responder rate\n\n")
        f.write("Targets = top-50 activated POIs per variant (>20% activation, >100 abs delta).\n")
        f.write("Bin agents by distance from home to nearest target.\n\n")
        for v in VARIANTS_INT:
            f.write(f"## {v} (n_targets={summary[v].get('n_targets')})\n\n")
            f.write("| distance bin | n_agents | responders | rate | protag n | protag resp | protag rate |\n")
            f.write("|---|---|---|---|---|---|---|\n")
            for k, c in summary[v]["binned"].items():
                r = c["responders"]; t = c["total"]
                pr = c["protag_resp"]; pt = c["protag_total"]
                rate = f"{r/t*100:.1f}%" if t else "0%"
                p_rate = f"{pr/pt*100:.1f}%" if pt else "0%"
                f.write(f"| {k} | {t} | {r} | {rate} | {pt} | {pr} | {p_rate} |\n")
            f.write("\n")
    print(f"  → wrote {out}/proximity.json + summary.md")


def main():
    print("loading atlas + profiles ...")
    loc_idx = build_location_index()
    profiles_by_seed = {s: load_profiles(s) for s in SEED_SUITES}
    print(f"  atlas={len(loc_idx)}  profiles={sum(len(p) for p in profiles_by_seed.values())}")

    try: analysis_d_walking_footprint(loc_idx, profiles_by_seed)
    except Exception as e: print(f"D failed: {e}")
    try: analysis_e_diversity(loc_idx, profiles_by_seed)
    except Exception as e: print(f"E failed: {e}")
    try: analysis_f_encounter_locations(loc_idx, profiles_by_seed)
    except Exception as e: print(f"F failed: {e}")
    try: analysis_g_stickiness(loc_idx, profiles_by_seed)
    except Exception as e: print(f"G failed: {e}")
    try: analysis_h_personality(loc_idx, profiles_by_seed)
    except Exception as e: print(f"H failed: {e}")
    try: analysis_i_proximity(loc_idx, profiles_by_seed)
    except Exception as e: print(f"I failed: {e}")
    print("=== D-I batch DONE ===")


if __name__ == "__main__":
    main()
