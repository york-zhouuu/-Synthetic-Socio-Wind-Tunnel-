"""[Auto-C] Responder profile: who are the 12% that physically respond?

For each variant (HP/GD/PF), identify "responders" = agents with non-zero
mean trajectory deviation. Cross-ref with population_cache demographics.
Compute:
- responder rate by gender / age_bucket / occupation / household_role
- spatial: distance from home_location to target_location (HP only)
- protagonist vs non-protagonist breakdown
"""
from __future__ import annotations
import json
import math
import statistics
from collections import defaultdict, Counter
from pathlib import Path
import sys

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
OUT = REPO / "data/analysis/2026-05-23_paper_exploration/C_responder_profile"
OUT.mkdir(parents=True, exist_ok=True)

SEEDS = {43: None, 44: None, 45: None}
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
VARIANTS_INT = ["hyperlocal_push", "global_distraction", "phone_friction"]

sys.path.insert(0, str(REPO / "tools"))
from backfill_publishable_metrics import (
    build_location_index,
    _build_agent_tick_position_table,
    _agent_position_at_tick,
)


def load_profiles(seed: int) -> dict:
    """Return {agent_id: profile_dict} from population cache."""
    p = REPO / f"data/population_cache/v1/{SEED_POPCACHE[seed]}"
    with open(p) as f:
        d = json.load(f)
    profiles = d.get("profiles", [])
    out = {}
    for prof in profiles:
        out[prof["agent_id"]] = prof
    return out


def compute_per_agent_deviation(seed: int, variant: str,
                                loc_idx: dict, days: list[int]) -> dict[str, float]:
    """Compute mean Euclidean deviation from baseline per agent over specified days."""
    base = SEED_SUITES[seed] / "variant_baseline" / f"seed_{seed}_positions.json"
    self = SEED_SUITES[seed] / f"variant_{variant}" / f"seed_{seed}_positions.json"
    base_t = _build_agent_tick_position_table(base)
    self_t = _build_agent_tick_position_table(self)
    per_agent = {}
    common = set(base_t) & set(self_t)
    for aid in common:
        dists = []
        for d in days:
            for t in range(d*288, (d+1)*288, 12):
                l_s = _agent_position_at_tick(self_t[aid], t)
                l_b = _agent_position_at_tick(base_t[aid], t)
                if l_s and l_b and l_s in loc_idx and l_b in loc_idx:
                    cs = loc_idx[l_s]["coord"]; cb = loc_idx[l_b]["coord"]
                    dx = cs[0] - cb[0]; dy = cs[1] - cb[1]
                    dists.append(math.sqrt(dx*dx + dy*dy))
        per_agent[aid] = statistics.mean(dists) if dists else 0.0
    return per_agent


def categorize_age(age):
    if age is None: return "?"
    if age < 25: return "18-24"
    if age < 35: return "25-34"
    if age < 50: return "35-49"
    if age < 65: return "50-64"
    return "65+"


def categorize_responder(dev_m, threshold=20.0):
    """Binary: responded or not (>20m mean deviation per day)."""
    return "responder" if dev_m > threshold else "non_responder"


def main():
    loc_idx = build_location_index()
    print(f"loaded atlas: {len(loc_idx)} locations")

    # Compute per-agent deviation per (seed, variant) on intervention days (4-9)
    intervention_days = list(range(4, 10))
    all_results = {}  # (seed, variant) -> {agent_id: deviation_m}
    print("=== computing per-agent deviations (intervention period day 4-9) ===")
    for s in SEED_SUITES:
        for v in VARIANTS_INT:
            print(f"  seed {s} / {v} ...", end=" ", flush=True)
            all_results[(s,v)] = compute_per_agent_deviation(s, v, loc_idx, intervention_days)
            print(f"{len(all_results[(s,v)])} agents")

    # Load profiles per seed
    profiles_by_seed = {s: load_profiles(s) for s in SEED_SUITES}
    print(f"profiles loaded: {sum(len(p) for p in profiles_by_seed.values())} total")

    # Aggregate: per-variant responder profile
    THRESHOLD = 20.0  # 20m mean dev/tick = responder
    profile_summary = {}
    for v in VARIANTS_INT:
        # Combine across 3 seeds
        # Per category: count agents in each demographic bucket × responder/non
        by_demo: dict[str, Counter] = defaultdict(Counter)
        # Also: collect per-agent records for distance-to-target analysis
        agent_records = []
        for s in SEED_SUITES:
            devs = all_results[(s,v)]
            profs = profiles_by_seed[s]
            for aid, dev in devs.items():
                p = profs.get(aid, {})
                cls = categorize_responder(dev, THRESHOLD)
                # bucket per dimension
                by_demo["gender"][(p.get("gender","?"), cls)] += 1
                by_demo["age_bucket"][(categorize_age(p.get("age")), cls)] += 1
                by_demo["occupation"][(p.get("occupation","?"), cls)] += 1
                by_demo["household"][(p.get("household","?"), cls)] += 1
                by_demo["household_role"][(p.get("household_role","?"), cls)] += 1
                by_demo["ethnicity_group"][(p.get("ethnicity_group","?"), cls)] += 1
                by_demo["income_tier"][(p.get("income_tier","?"), cls)] += 1
                by_demo["education_level"][(p.get("education_level","?"), cls)] += 1
                by_demo["work_mode"][(p.get("work_mode","?"), cls)] += 1
                by_demo["is_protagonist"][(p.get("is_protagonist", False), cls)] += 1
                home_loc = p.get("home_location")
                workplace = p.get("workplace")
                home_xy = loc_idx.get(home_loc, {}).get("coord", (None, None))
                work_xy = loc_idx.get(workplace, {}).get("coord", (None, None))
                agent_records.append({
                    "seed": s, "agent_id": aid, "deviation_m": dev,
                    "is_responder": cls == "responder",
                    "is_protagonist": p.get("is_protagonist", False),
                    "age": p.get("age"), "gender": p.get("gender"),
                    "occupation": p.get("occupation"),
                    "household": p.get("household"),
                    "income_tier": p.get("income_tier"),
                    "home_loc": home_loc, "home_xy": home_xy,
                    "workplace": workplace, "work_xy": work_xy,
                    "extraversion": p.get("personality", {}).get("extraversion"),
                    "openness": p.get("personality", {}).get("openness"),
                })

        profile_summary[v] = {
            "by_demo": {dim: dict(counter) for dim, counter in by_demo.items()},
            "n_total": len(agent_records),
            "n_responders": sum(1 for r in agent_records if r["is_responder"]),
            "responder_rate": sum(1 for r in agent_records if r["is_responder"]) / max(1, len(agent_records)),
            "agent_records_sample": agent_records[:5],  # truncate big payload
        }
        # Also save full records (small enough — ~3000 agents per variant)
        with open(OUT / f"agents_{v}.json", "w") as f:
            # Convert tuples in home_xy to lists
            for r in agent_records:
                hx = r.get("home_xy"); wx = r.get("work_xy")
                r["home_xy"] = list(hx) if hx and hx[0] is not None else None
                r["work_xy"] = list(wx) if wx and wx[0] is not None else None
            json.dump(agent_records, f, ensure_ascii=False, indent=2)
        print(f"  → wrote agents_{v}.json ({len(agent_records)} records)")

    # Write JSON summary
    with open(OUT / "responder_profile_summary.json", "w") as f:
        # Serialize tuple keys as joined strings for JSON
        out = {}
        for v, ps in profile_summary.items():
            out[v] = {
                "by_demo": {
                    dim: {f"{k[0]}|{k[1]}": cnt for k, cnt in cd.items()}
                    for dim, cd in ps["by_demo"].items()
                },
                "n_total": ps["n_total"],
                "n_responders": ps["n_responders"],
                "responder_rate": ps["responder_rate"],
            }
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"  → wrote responder_profile_summary.json")

    # Markdown: per-variant responder rate by demographic
    with open(OUT / "responder_rates_by_demo.md", "w") as f:
        f.write("# Responder rate by demographic (threshold: >20m mean deviation per tick during day 4-9)\n\n")
        f.write(f"Pooled across 3 seeds. Total agents per variant ~3000 "
                f"(1000 × 3 seeds).\n\n")
        for v in VARIANTS_INT:
            ps = profile_summary[v]
            f.write(f"## {v} — overall responder rate: "
                    f"{ps['responder_rate']*100:.1f}% "
                    f"({ps['n_responders']:,}/{ps['n_total']:,})\n\n")
            for dim in ["is_protagonist", "gender", "age_bucket", "household",
                        "household_role", "occupation", "income_tier",
                        "education_level", "work_mode", "ethnicity_group"]:
                cnts = ps["by_demo"].get(dim, {})
                # Pivot: bucket -> {responder, non_responder}
                pivot = defaultdict(lambda: {"responder":0, "non_responder":0})
                for (bucket, cls), cnt in cnts.items():
                    pivot[bucket][cls] = cnt
                # Sort buckets by total descending
                rows = sorted(pivot.items(),
                              key=lambda kv: -(kv[1]["responder"]+kv[1]["non_responder"]))
                f.write(f"### {dim}\n\n")
                f.write("| bucket | responders | non-responders | total | rate |\n")
                f.write("|---|---|---|---|---|\n")
                for bucket, cnts2 in rows[:15]:  # top 15 buckets
                    r = cnts2["responder"]; nr = cnts2["non_responder"]
                    tot = r + nr
                    rate = r / tot if tot else 0
                    f.write(f"| {bucket} | {r} | {nr} | {tot} | {rate*100:.1f}% |\n")
                f.write("\n")
    print(f"  → wrote responder_rates_by_demo.md")

    # Scatter plot: deviation distribution + scatter
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Histogram of deviations per variant
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    for i, v in enumerate(VARIANTS_INT):
        ax = axes[i]
        all_devs = []
        for s in SEED_SUITES:
            all_devs.extend(all_results[(s,v)].values())
        # Log-scale histogram (because of bimodal: many 0s + heavy tail)
        ax.hist([d for d in all_devs if d > 0], bins=50, color="#d62728", alpha=0.7)
        ax.axvline(THRESHOLD, color="black", linestyle="--",
                   label=f"responder threshold ({THRESHOLD}m)")
        ax.set_yscale("log")
        ax.set_title(f"{v}\n(non-zero deviations, log scale)")
        ax.set_xlabel("mean deviation per tick (m)")
        ax.set_ylabel("agent count (log)")
        ax.legend()
    plt.tight_layout()
    plt.savefig(OUT / "deviation_histogram.png", dpi=140)
    plt.close()
    print(f"  → wrote deviation_histogram.png")

    # Scatter: extraversion vs deviation (top variant: HP)
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    for i, v in enumerate(VARIANTS_INT):
        ax = axes[i]
        xs = []; ys = []; cs = []
        with open(OUT / f"agents_{v}.json") as af:
            agent_list = json.load(af)
        for r in agent_list:
            if r.get("extraversion") is None: continue
            xs.append(r["extraversion"])
            ys.append(r["deviation_m"])
            cs.append("#d62728" if r["is_protagonist"] else "#777777")
        ax.scatter(xs, ys, c=cs, s=10, alpha=0.4)
        ax.set_xlabel("extraversion (0-1)")
        ax.set_ylabel("mean deviation per tick (m)")
        ax.set_title(f"{v}\n(red = protagonist, grey = non-protag)")
        ax.set_yscale("symlog")
        ax.axhline(THRESHOLD, color="blue", linestyle="--", linewidth=0.5)
        ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUT / "extraversion_vs_deviation.png", dpi=140)
    plt.close()
    print(f"  → wrote extraversion_vs_deviation.png")

    # README
    with open(OUT / "README.md", "w") as f:
        f.write("# Analysis C: Responder profile (who moves under intervention)\n\n")
        f.write(f"For each variant (HP/GD/PF), we compute per-agent mean trajectory\n"
                f"deviation from baseline across the intervention period (day 4-9, every 12 ticks).\n"
                f"An agent is a \"responder\" if mean dev > {THRESHOLD}m.\n\n")
        f.write("## Files\n")
        f.write("- `responder_rates_by_demo.md` — rate by gender/age/occupation/etc per variant\n")
        f.write("- `responder_profile_summary.json` — aggregated counts\n")
        f.write("- `agents_<variant>.json` — full per-agent records (deviation + demographics)\n")
        f.write("- `deviation_histogram.png` — distribution per variant\n")
        f.write("- `extraversion_vs_deviation.png` — personality correlation scatter\n\n")
        f.write("## Headlines\n\n")
        for v in VARIANTS_INT:
            ps = profile_summary[v]
            f.write(f"- **{v}**: {ps['responder_rate']*100:.1f}% responder rate "
                    f"({ps['n_responders']:,}/{ps['n_total']:,})\n")
    print(f"  → wrote README.md")


if __name__ == "__main__":
    main()
