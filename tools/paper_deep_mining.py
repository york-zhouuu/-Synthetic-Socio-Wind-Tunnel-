"""Deep mining: distance-decay, timing/causal-latency, demographic crossings,
responder churn, specific Lane Cove POI activation."""
from __future__ import annotations
import json
import math
import statistics
from collections import defaultdict, Counter
from pathlib import Path
import sys

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
OUT_ROOT = REPO / "data/analysis/2026-05-23_paper_exploration"
OUT = OUT_ROOT / "DEEP_MINING"
OUT.mkdir(parents=True, exist_ok=True)

SEED_SUITES = {
    43: REPO / "data/experiments/20260521_185100_publishable_v6_day4to13_fork_seed43",
    44: REPO / "data/experiments/20260522_165045_publishable_v7_day4to13_fork_seed44",
    45: REPO / "data/experiments/20260522_212423_publishable_v7_day4to13_fork_seed45",
}
SEED_POPCACHE = {
    43: "08d79c69cc045b32.json", 44: "7cf41bf8960a72d8.json", 45: "39fa81f5889f6d8b.json"
}
VARIANTS = ["baseline", "hyperlocal_push", "global_distraction", "phone_friction"]

sys.path.insert(0, str(REPO / "tools"))
from backfill_publishable_metrics import build_location_index


def load_profiles(seed):
    with open(REPO / f"data/population_cache/v1/{SEED_POPCACHE[seed]}") as f:
        return {p["agent_id"]: p for p in json.load(f)["profiles"]}


# ──────────────────────────────────────────────────────────────────────
# 1. Distance-decay of spillover effect
# ──────────────────────────────────────────────────────────────────────
def deep_distance_decay(loc_idx, profiles_by_seed):
    print("=== Deep 1: distance-decay of spillover ===")
    # Use HP variant only. For each non-protag, find their NEAREST protag-responder
    # by home-to-home distance. Then bucket by 0-100m, 100-200m, ..., 1000m+
    # and compute responder rate per bucket.
    BUCKETS = [0, 50, 100, 150, 200, 300, 400, 500, 700, 1000, 1500, 99999]
    by_bucket = defaultdict(lambda: {"total": 0, "responders": 0})
    by_bucket_no_resp_neighbor = defaultdict(lambda: {"total": 0, "responders": 0})

    with open(OUT_ROOT / "C_responder_profile/agents_hyperlocal_push.json") as f:
        agents = json.load(f)
    by_seed = defaultdict(list)
    for r in agents:
        if r.get("home_xy") and r["home_xy"][0] is not None:
            by_seed[r["seed"]].append(r)

    for s, agents_in_seed in by_seed.items():
        protag_responders = [r for r in agents_in_seed
                             if r["is_protagonist"] and r["is_responder"]]
        protag_non = [r for r in agents_in_seed
                      if r["is_protagonist"] and not r["is_responder"]]
        nonprotag = [r for r in agents_in_seed if not r["is_protagonist"]]

        for npg in nonprotag:
            nx, ny = npg["home_xy"]
            # Distance to nearest protag-responder
            min_d_resp = min(
                (math.hypot(nx-r["home_xy"][0], ny-r["home_xy"][1])
                 for r in protag_responders if r["home_xy"][0] is not None),
                default=float("inf")
            )
            # Distance to nearest protag (any)
            min_d_any = min(
                (math.hypot(nx-r["home_xy"][0], ny-r["home_xy"][1])
                 for r in protag_responders + protag_non if r["home_xy"][0] is not None),
                default=float("inf")
            )
            # Bucket
            for lo, hi in zip(BUCKETS[:-1], BUCKETS[1:]):
                if lo <= min_d_resp < hi:
                    by_bucket[f"{lo}-{hi}m"]["total"] += 1
                    if npg["is_responder"]: by_bucket[f"{lo}-{hi}m"]["responders"] += 1
                    break
            # Also: bucket by distance to ANY protag (control — no responder filter)
            for lo, hi in zip(BUCKETS[:-1], BUCKETS[1:]):
                if lo <= min_d_any < hi:
                    by_bucket_no_resp_neighbor[f"{lo}-{hi}m"]["total"] += 1
                    if npg["is_responder"]: by_bucket_no_resp_neighbor[f"{lo}-{hi}m"]["responders"] += 1
                    break

    rows = []
    for k, c in by_bucket.items():
        rows.append({
            "bucket": k, "total": c["total"], "responders": c["responders"],
            "rate": c["responders"]/c["total"] if c["total"] else 0
        })
    rows.sort(key=lambda r: int(r["bucket"].split("-")[0]))

    with open(OUT / "distance_decay.json", "w") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    with open(OUT / "distance_decay.md", "w") as f:
        f.write("# Distance-decay of spillover effect (HP variant, 3 seeds pooled)\n\n")
        f.write("For each non-protagonist agent, find the **nearest protag-responder**\n")
        f.write("by home-to-home distance. Bucket by distance, compute responder rate.\n\n")
        f.write("If the spillover is truly a 200m spatial mechanism (not selection effect),\n")
        f.write("we expect a sharp distance-decay: high response near, low response far.\n\n")
        f.write("| distance to nearest protag-responder | n non-protag | responders | rate |\n")
        f.write("|---|---|---|---|\n")
        for r in rows:
            f.write(f"| {r['bucket']} | {r['total']} | {r['responders']} | {r['rate']*100:.1f}% |\n")
    print(f"  → wrote distance_decay.json + .md")
    return rows


# ──────────────────────────────────────────────────────────────────────
# 2. Day-by-day spillover buildup
# ──────────────────────────────────────────────────────────────────────
def deep_spillover_timing(loc_idx, profiles_by_seed):
    print("=== Deep 2: spillover timing (day-by-day buildup) ===")
    # For each day during intervention (4-9), compute:
    # protag responder count (cumulative) and non-protag responder count
    # to see if non-protag response LAGS protag response.
    # Use day-specific deviation (not pooled).

    from backfill_publishable_metrics import (
        _build_agent_tick_position_table, _agent_position_at_tick
    )

    daily_stats = defaultdict(lambda: defaultdict(lambda: {"protag_resp":0, "nonprotag_resp":0, "protag_total":0, "nonprotag_total":0}))

    for s in SEED_SUITES:
        base = SEED_SUITES[s] / "variant_baseline" / f"seed_{s}_positions.json"
        self_p = SEED_SUITES[s] / "variant_hyperlocal_push" / f"seed_{s}_positions.json"
        base_t = _build_agent_tick_position_table(base)
        self_t = _build_agent_tick_position_table(self_p)
        profs = profiles_by_seed[s]
        common = set(base_t) & set(self_t)
        # For each day, compute per-agent deviation that day
        for d in range(14):
            for aid in common:
                dists = []
                for t in range(d*288, (d+1)*288, 24):
                    l_s = _agent_position_at_tick(self_t[aid], t)
                    l_b = _agent_position_at_tick(base_t[aid], t)
                    if l_s and l_b and l_s in loc_idx and l_b in loc_idx:
                        cs = loc_idx[l_s]["coord"]; cb = loc_idx[l_b]["coord"]
                        dists.append(math.hypot(cs[0]-cb[0], cs[1]-cb[1]))
                if not dists: continue
                mean_dev = statistics.mean(dists)
                is_resp = mean_dev > 20.0
                is_protag = profs.get(aid, {}).get("is_protagonist", False)
                key = "protag" if is_protag else "nonprotag"
                daily_stats[d][s][f"{key}_total"] += 1
                if is_resp:
                    daily_stats[d][s][f"{key}_resp"] += 1

    # Aggregate across seeds, write
    rows = []
    for d in range(14):
        protag_rates = []; nonprotag_rates = []
        for s in SEED_SUITES:
            st = daily_stats[d][s]
            if st["protag_total"]:
                protag_rates.append(st["protag_resp"] / st["protag_total"])
            if st["nonprotag_total"]:
                nonprotag_rates.append(st["nonprotag_resp"] / st["nonprotag_total"])
        rows.append({
            "day": d,
            "phase": "baseline" if d < 4 else ("intervention" if d < 10 else "post"),
            "protag_response_rate": statistics.mean(protag_rates) if protag_rates else 0,
            "nonprotag_response_rate": statistics.mean(nonprotag_rates) if nonprotag_rates else 0,
            "ratio_protag_to_nonprotag": (statistics.mean(protag_rates) / statistics.mean(nonprotag_rates))
                if nonprotag_rates and statistics.mean(nonprotag_rates) > 0 else None,
            "protag_response_rate_std": statistics.stdev(protag_rates) if len(protag_rates)>1 else 0,
            "nonprotag_response_rate_std": statistics.stdev(nonprotag_rates) if len(nonprotag_rates)>1 else 0,
        })

    with open(OUT / "spillover_timing.json", "w") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    with open(OUT / "spillover_timing.md", "w") as f:
        f.write("# Day-by-day spillover buildup (HP variant)\n\n")
        f.write("Per-day responder rate (mean dev > 20m on that day alone).\n\n")
        f.write("| day | phase | protag rate | non-protag rate | ratio P/N |\n")
        f.write("|---|---|---|---|---|\n")
        for r in rows:
            ratio = r['ratio_protag_to_nonprotag']
            ratio_s = f"{ratio:.1f}×" if ratio is not None else "N/A"
            f.write(f"| {r['day']} | {r['phase']} | "
                    f"{r['protag_response_rate']*100:.1f}% (±{r['protag_response_rate_std']*100:.1f}) | "
                    f"{r['nonprotag_response_rate']*100:.1f}% (±{r['nonprotag_response_rate_std']*100:.1f}) | "
                    f"{ratio_s} |\n")
    print(f"  → wrote spillover_timing.json + .md")
    return rows


# ──────────────────────────────────────────────────────────────────────
# 3. Specific Lane Cove POI activation (real names)
# ──────────────────────────────────────────────────────────────────────
def deep_specific_pois(loc_idx):
    print("=== Deep 3: specific Lane Cove POI activations ===")
    # Load activation data
    with open(OUT_ROOT / "A_poi_activation/activation_per_location.json") as f:
        a_data = json.load(f)

    # For HP, get top 30 activated POIs by absolute delta (dwell ticks), not pct
    # (pct can blow up for near-zero baseline)
    hp_acts = list(a_data["activation_vs_baseline"]["hyperlocal_push"].values())

    # Sort by absolute delta (ticks gained)
    top_by_delta = sorted(hp_acts, key=lambda r: -r["abs_delta"])[:30]
    bot_by_delta = sorted(hp_acts, key=lambda r: r["abs_delta"])[:20]

    # For each, look up the proper atlas entry to get real names, building_type etc
    with open(REPO / "data/lanecove_atlas.json") as f:
        atlas = json.load(f)
    buildings = atlas["buildings"]
    outdoor = atlas.get("outdoor_areas", {})
    if isinstance(outdoor, list):
        outdoor = {o["id"]: o for o in outdoor}

    def lookup(loc_id):
        if loc_id in buildings:
            b = buildings[loc_id]
            return {
                "name": b.get("name"),
                "type": b.get("building_type"),
                "tags": b.get("osm_tags", {}),
                "kind": "building",
            }
        if loc_id in outdoor:
            o = outdoor[loc_id]
            return {
                "name": o.get("name") or o.get("road_name"),
                "type": o.get("area_type"),
                "kind": "outdoor",
            }
        return None

    rows_up = []
    for r in top_by_delta:
        info = lookup(r["loc_id"]) or {}
        rows_up.append({
            "loc_id": r["loc_id"],
            "name": info.get("name") or r.get("name"),
            "type": info.get("type") or r.get("type"),
            "kind": info.get("kind"),
            "bl_dwell_ticks": int(r["bl_mean"]),
            "hp_dwell_ticks": int(r["variant_mean"]),
            "abs_delta_ticks": int(r["abs_delta"]),
            "activation_pct": r["activation_pct"],
        })
    rows_dn = []
    for r in bot_by_delta:
        info = lookup(r["loc_id"]) or {}
        rows_dn.append({
            "loc_id": r["loc_id"],
            "name": info.get("name") or r.get("name"),
            "type": info.get("type") or r.get("type"),
            "kind": info.get("kind"),
            "bl_dwell_ticks": int(r["bl_mean"]),
            "hp_dwell_ticks": int(r["variant_mean"]),
            "abs_delta_ticks": int(r["abs_delta"]),
            "activation_pct": r["activation_pct"],
        })

    with open(OUT / "specific_pois.json", "w") as f:
        json.dump({"top_activated": rows_up, "top_deactivated": rows_dn},
                  f, ensure_ascii=False, indent=2)
    with open(OUT / "specific_pois.md", "w") as f:
        f.write("# Specific Lane Cove POIs activated/deactivated under HP\n\n")
        f.write("Ranked by absolute Δ in dwell ticks (mean across 3 seeds).\n\n")
        f.write("## Top 30 most activated (people spent MORE time here under HP)\n\n")
        f.write("| # | name | type | BL ticks | HP ticks | Δ ticks | activation % |\n")
        f.write("|---|---|---|---|---|---|---|\n")
        for i, r in enumerate(rows_up, 1):
            f.write(f"| {i} | {r['name']} | {r['type']} | {r['bl_dwell_ticks']:,} | "
                    f"{r['hp_dwell_ticks']:,} | +{r['abs_delta_ticks']:,} | "
                    f"{r['activation_pct']:+.1f}% |\n")
        f.write("\n## Top 20 most deactivated (people spent LESS time here under HP)\n\n")
        f.write("| # | name | type | BL ticks | HP ticks | Δ ticks | activation % |\n")
        f.write("|---|---|---|---|---|---|---|\n")
        for i, r in enumerate(rows_dn, 1):
            f.write(f"| {i} | {r['name']} | {r['type']} | {r['bl_dwell_ticks']:,} | "
                    f"{r['hp_dwell_ticks']:,} | {r['abs_delta_ticks']:,} | "
                    f"{r['activation_pct']:+.1f}% |\n")
    print(f"  → wrote specific_pois.json + .md")
    return rows_up, rows_dn


# ──────────────────────────────────────────────────────────────────────
# 4. Cross-demographic tie formation (who connects with whom)
# ──────────────────────────────────────────────────────────────────────
def deep_cross_demo_ties(loc_idx, profiles_by_seed):
    print("=== Deep 4: cross-demographic ties ===")
    # Use end_of_day_location_by_agent: for each day, find pairs of agents at SAME location
    # at end of day. Then look at the demographic crossing.
    # NOTE: this is approximation of "ties" — true tie formation event log not exposed
    # at the run_metrics level. We use spatial co-presence at end of day as proxy.

    summary = {}
    for v in ["baseline", "hyperlocal_push", "phone_friction", "global_distraction"]:
        cross_pairs = defaultdict(int)  # (age_bucket_a, age_bucket_b) → count
        within_pairs = 0
        cross_count = 0
        total_count = 0
        occupation_cross = defaultdict(int)

        for s in SEED_SUITES:
            profs = profiles_by_seed[s]
            p = SEED_SUITES[s] / f"variant_{v}" / f"seed_{s}.json"
            with open(p) as f:
                sd = json.load(f)
            for pd_idx, pd in enumerate(sd["run_metrics"]["per_day"]):
                if pd_idx < 4 or pd_idx >= 10: continue  # intervention only
                eod = pd.get("end_of_day_location_by_agent", {}) or {}
                loc_to_agents = defaultdict(list)
                for aid, loc in eod.items():
                    loc_to_agents[loc].append(aid)
                # for each location with 2+ agents, sample pairs
                for loc, ags in loc_to_agents.items():
                    if len(ags) < 2: continue
                    # only consider sample for speed (first 50 agents per loc)
                    sample = ags[:50]
                    for i in range(len(sample)):
                        for j in range(i+1, len(sample)):
                            a, b = sample[i], sample[j]
                            pa = profs.get(a, {}); pb = profs.get(b, {})
                            age_a = pa.get("age", 0); age_b = pb.get("age", 0)
                            def bk(age):
                                return ("18-24" if age<25 else "25-34" if age<35 else
                                        "35-49" if age<50 else "50-64" if age<65 else "65+")
                            ba, bb = bk(age_a), bk(age_b)
                            pair_key = tuple(sorted([ba, bb]))
                            cross_pairs[pair_key] += 1
                            if ba == bb: within_pairs += 1
                            else: cross_count += 1
                            total_count += 1
                            # Cross-occupation
                            oa, ob = pa.get("occupation","?"), pb.get("occupation","?")
                            if oa != ob:
                                occupation_cross[tuple(sorted([oa,ob]))] += 1
        summary[v] = {
            "total_eod_copresence_pairs": total_count,
            "within_age_bucket": within_pairs,
            "cross_age_bucket": cross_count,
            "cross_age_pct": cross_count/total_count if total_count else 0,
            "top_age_pair_crossings": dict(sorted(
                cross_pairs.items(), key=lambda x: -x[1])[:10]),
            "top_occupation_pair_crossings": dict(sorted(
                occupation_cross.items(), key=lambda x: -x[1])[:15]),
        }

    with open(OUT / "cross_demo_ties.json", "w") as f:
        json.dump({v: {
            "total_eod_copresence_pairs": st["total_eod_copresence_pairs"],
            "within_age_bucket": st["within_age_bucket"],
            "cross_age_bucket": st["cross_age_bucket"],
            "cross_age_pct": st["cross_age_pct"],
            "top_age_pair_crossings": {f"{k[0]}/{k[1]}": v for k,v in st["top_age_pair_crossings"].items()},
            "top_occupation_pair_crossings": {f"{k[0]}/{k[1]}": v for k,v in st["top_occupation_pair_crossings"].items()},
        } for v, st in summary.items()}, f, ensure_ascii=False, indent=2)

    with open(OUT / "cross_demo_ties.md", "w") as f:
        f.write("# Cross-demographic co-presence (proxy for tie diversity)\n\n")
        f.write("End-of-day same-location pair counts (intervention period day 4-9, 3 seeds pooled).\n\n")
        f.write("| variant | total pairs | within age | cross age | cross % |\n")
        f.write("|---|---|---|---|---|\n")
        for v, st in summary.items():
            tot = st["total_eod_copresence_pairs"]
            within = st["within_age_bucket"]; cross = st["cross_age_bucket"]
            pct = st["cross_age_pct"]*100
            f.write(f"| {v} | {tot:,} | {within:,} | {cross:,} | {pct:.1f}% |\n")
    print(f"  → wrote cross_demo_ties.json + .md")


# ──────────────────────────────────────────────────────────────────────
# 5. Effect sizes with proper CV% / CIs across 3 seeds
# ──────────────────────────────────────────────────────────────────────
def deep_effect_sizes():
    print("=== Deep 5: effect sizes with CV% across 3 seeds ===")
    metrics_with_ci = {}

    def get_metric(seed, variant, path):
        p = SEED_SUITES[seed] / f"variant_{variant}" / f"seed_{seed}.json"
        with open(p) as f:
            sd = json.load(f)
        cur = sd["run_metrics"]
        for k in path:
            if isinstance(cur, dict): cur = cur.get(k)
            else: return None
        return cur

    metric_specs = [
        ("encounter_total", ["encounter_stats", "total"], "raw encounters (millions)", 1e6),
        ("unique_pairs", ["encounter_stats", "diversity_pairs_total"], "unique pairs (thousands)", 1000),
        ("weak_tie", ["weak_tie_formation_count"], "weak ties (thousands)", 1000),
        ("dialogue_live_at_exit", ["dialogue_live_at_exit"], "active dialogues at exit", 1),
        ("replan_count", ["extensions", "replan_count"], "replans", 1),
    ]

    out_rows = []
    for label, path, friendly, scale in metric_specs:
        bl_vals = []
        for s in SEED_SUITES:
            v_bl = get_metric(s, "baseline", path)
            if v_bl is not None: bl_vals.append(v_bl)
        bl_mean = statistics.mean(bl_vals)
        bl_cv = statistics.stdev(bl_vals)/bl_mean*100 if len(bl_vals)>1 and bl_mean else 0

        row = {
            "metric": label,
            "friendly": friendly,
            "scale_divisor": scale,
            "baseline": {
                "mean": bl_mean / scale,
                "cv_pct": bl_cv,
                "per_seed": [v/scale for v in bl_vals],
            },
            "variants": {},
        }
        for v in ["hyperlocal_push", "global_distraction", "phone_friction"]:
            vals = []
            for s in SEED_SUITES:
                vv = get_metric(s, v, path)
                if vv is not None: vals.append(vv)
            if not vals: continue
            v_mean = statistics.mean(vals)
            v_cv = statistics.stdev(vals)/v_mean*100 if len(vals)>1 and v_mean else 0
            row["variants"][v] = {
                "mean": v_mean / scale,
                "cv_pct": v_cv,
                "per_seed": [vv/scale for vv in vals],
                "fold_vs_baseline": v_mean / bl_mean if bl_mean else 0,
            }
        out_rows.append(row)

    with open(OUT / "effect_sizes.json", "w") as f:
        json.dump(out_rows, f, ensure_ascii=False, indent=2)
    with open(OUT / "effect_sizes.md", "w") as f:
        f.write("# Effect sizes with proper variance markers (n=3 seeds)\n\n")
        f.write("Each metric reports: mean across 3 seeds + CV% + fold-change vs baseline + per-seed values.\n\n")
        for r in out_rows:
            f.write(f"## {r['friendly']} (`{r['metric']}`)\n\n")
            bl = r["baseline"]
            f.write(f"**Baseline**: {bl['mean']:.2f} (CV {bl['cv_pct']:.1f}%, per seed: "
                    f"{[round(v,2) for v in bl['per_seed']]})\n\n")
            f.write("| variant | mean | CV% | fold vs BL | per seed |\n")
            f.write("|---|---|---|---|---|\n")
            for v, st in r["variants"].items():
                f.write(f"| {v} | {st['mean']:.2f} | {st['cv_pct']:.1f}% | "
                        f"**{st['fold_vs_baseline']:.2f}×** | "
                        f"{[round(vv,2) for vv in st['per_seed']]} |\n")
            f.write("\n")
    print(f"  → wrote effect_sizes.json + .md")


# ──────────────────────────────────────────────────────────────────────
# 6. Responder churn — same people every day or rotating?
# ──────────────────────────────────────────────────────────────────────
def deep_responder_churn(loc_idx, profiles_by_seed):
    print("=== Deep 6: responder churn ===")
    from backfill_publishable_metrics import (
        _build_agent_tick_position_table, _agent_position_at_tick
    )
    # For HP variant only, compute per-agent day-by-day deviation, then check
    # how many agents were responders on day 4 / 5 / ... and how many were
    # responders on ALL 6 intervention days vs only some.

    seed_to_per_day = {}
    for s in SEED_SUITES:
        base = SEED_SUITES[s] / "variant_baseline" / f"seed_{s}_positions.json"
        self_p = SEED_SUITES[s] / "variant_hyperlocal_push" / f"seed_{s}_positions.json"
        base_t = _build_agent_tick_position_table(base)
        self_t = _build_agent_tick_position_table(self_p)
        common = sorted(set(base_t) & set(self_t))
        # agent -> [day -> bool responder]
        agent_days = {aid: [False]*14 for aid in common}
        for d in range(14):
            for aid in common:
                dists = []
                for t in range(d*288, (d+1)*288, 24):
                    l_s = _agent_position_at_tick(self_t[aid], t)
                    l_b = _agent_position_at_tick(base_t[aid], t)
                    if l_s and l_b and l_s in loc_idx and l_b in loc_idx:
                        cs = loc_idx[l_s]["coord"]; cb = loc_idx[l_b]["coord"]
                        dists.append(math.hypot(cs[0]-cb[0], cs[1]-cb[1]))
                if dists and statistics.mean(dists) > 20.0:
                    agent_days[aid][d] = True
        seed_to_per_day[s] = agent_days

    # Aggregate: across 3 seeds, for HP, compute distribution of "how many intervention days did the agent respond"
    DAYS_INT = range(4, 10)
    by_persistence = Counter()  # number of int days responded -> count
    response_on_day = defaultdict(int)  # day -> count agents responding
    response_on_day_total = defaultdict(int)
    for s, agent_days in seed_to_per_day.items():
        for aid, days_arr in agent_days.items():
            int_responses = sum(1 for d in DAYS_INT if days_arr[d])
            by_persistence[int_responses] += 1
            for d in DAYS_INT:
                response_on_day_total[d] += 1
                if days_arr[d]:
                    response_on_day[d] += 1

    summary = {
        "by_intervention_days_responded": dict(by_persistence),
        "response_rate_per_day": {
            d: response_on_day[d] / response_on_day_total[d]
            for d in DAYS_INT
        },
        "total_unique_responders_at_least_once": sum(
            cnt for k, cnt in by_persistence.items() if k > 0
        ),
        "total_persistent_responders_all_6_days": by_persistence.get(6, 0),
        "n_agents_pooled": sum(by_persistence.values()),
    }

    with open(OUT / "responder_churn.json", "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    with open(OUT / "responder_churn.md", "w") as f:
        f.write("# Responder churn — same agents every day or rotating?\n\n")
        f.write("HP variant only. Per-agent day-by-day responder status (mean dev > 20m that day).\n\n")
        n = summary["n_agents_pooled"]
        f.write(f"## Distribution of intervention-day responses (n={n} agents pooled across 3 seeds)\n\n")
        f.write("| # intervention days responded | count | % of all agents |\n")
        f.write("|---|---|---|\n")
        for k in range(7):
            c = by_persistence.get(k, 0)
            f.write(f"| {k} days | {c} | {c/n*100:.1f}% |\n")
        f.write(f"\n**Unique responders (at least 1 day)**: {summary['total_unique_responders_at_least_once']} ({summary['total_unique_responders_at_least_once']/n*100:.1f}%)\n")
        f.write(f"**Persistent responders (all 6 days)**: {summary['total_persistent_responders_all_6_days']} ({summary['total_persistent_responders_all_6_days']/n*100:.1f}%)\n\n")
        f.write("## Per-day response rate (all 3000 agents pooled)\n\n")
        f.write("| day | rate |\n|---|---|\n")
        for d in DAYS_INT:
            f.write(f"| {d} | {summary['response_rate_per_day'][d]*100:.1f}% |\n")
    print(f"  → wrote responder_churn.json + .md")


def main():
    print("loading atlas + profiles ...")
    loc_idx = build_location_index()
    profs = {s: load_profiles(s) for s in SEED_SUITES}
    print(f"  atlas={len(loc_idx)}  profiles={sum(len(p) for p in profs.values())}")

    for fn in [
        lambda: deep_distance_decay(loc_idx, profs),
        lambda: deep_spillover_timing(loc_idx, profs),
        lambda: deep_specific_pois(loc_idx),
        lambda: deep_cross_demo_ties(loc_idx, profs),
        deep_effect_sizes,
        lambda: deep_responder_churn(loc_idx, profs),
    ]:
        try: fn()
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"FAILED")
    print("=== DEEP MINING DONE ===")


if __name__ == "__main__":
    main()
