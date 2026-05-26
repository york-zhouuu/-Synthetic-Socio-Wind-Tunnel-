"""H17: HP 增加的 encounter 是已认识 (BL 已遇到) vs 陌生 (BL 没遇到)?

方法:
1. 从 BL snapshot 提取 tick_metrics_recorder_state.buckets.{day}.distinct_pairs → BL_pairs set
2. 从 HP/GD/PF snapshot 提取同上 → 各 variant pair set
3. 对每个 variant: 算 (a) 与 BL 共有的 pair 数 = "已认识"(强化), (b) 新 pair = "陌生→认识"
4. 加成机制: BL 已有 pair 的 encounter 次数在 HP 翻了几倍? (从 run_metrics.encounter_stats 或重算)

主参考: seed 44 + 45, 4 variants
"""
import ijson
import json
from pathlib import Path
from collections import defaultdict, Counter

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
OUT = REPO / "data/analysis/2026-05-24_hypothesis_validation/H17_familiarity"
OUT.mkdir(parents=True, exist_ok=True)

SEED_DIRS = {
    44: REPO / "data/experiments/20260522_165045_publishable_v7_day4to13_fork_seed44_BACKUP_20260522_213319_FULL_ALLVARIANTS",
    45: REPO / "data/experiments/20260522_212423_publishable_v7_day4to13_fork_seed45_BACKUP_20260523_022549_FULL_ALLVARIANTS",
}

VARIANTS = ["baseline", "hyperlocal_push", "global_distraction", "phone_friction"]


def get_snap_path(seed, variant):
    d = SEED_DIRS[seed] / f"variant_{variant}"
    snaps = list(d.glob(f"seed_{seed}_pid*_tick*.snapshot.json"))
    return snaps[0] if snaps else None


def extract_distinct_pairs(snap_path):
    """Read tick_metrics_recorder_state.buckets.{day}.distinct_pairs across all days.
    Returns: set of (a, b) tuples (sorted) + per-day counts dict.
    """
    pairs = set()
    per_day = {}
    print(f"  reading {snap_path.name} ({snap_path.stat().st_size/1e6:.0f}MB)...", flush=True)
    with open(snap_path) as f:
        for day_key, bucket in ijson.kvitems(f, "tick_metrics_recorder_state.buckets"):
            day = int(day_key)
            day_pairs = bucket.get("distinct_pairs", [])
            per_day[day] = len(day_pairs)
            for p in day_pairs:
                # could be [a, b] list
                if isinstance(p, list) and len(p) == 2:
                    key = tuple(sorted(p))
                    pairs.add(key)
    return pairs, per_day


def analyse_seed(seed):
    print(f"\n=== SEED {seed} ===", flush=True)
    variant_pairs = {}
    variant_per_day = {}
    for v in VARIANTS:
        sp = get_snap_path(seed, v)
        if sp is None:
            print(f"  [SKIP] {v}: no snapshot")
            continue
        pairs, per_day = extract_distinct_pairs(sp)
        variant_pairs[v] = pairs
        variant_per_day[v] = per_day
        print(f"  {v:22s}: {len(pairs)} unique pairs, per-day total = {sum(per_day.values())}", flush=True)

    bl_pairs = variant_pairs.get("baseline", set())

    results = {"seed": seed, "variants": {}}
    for v in VARIANTS:
        if v not in variant_pairs:
            continue
        vp = variant_pairs[v]
        shared_with_bl = vp & bl_pairs        # 已认识 in BL
        new_in_v = vp - bl_pairs              # BL 没认识,v 才认识
        bl_only = bl_pairs - vp               # BL 认识但 v 没了

        results["variants"][v] = {
            "total_unique_pairs": len(vp),
            "shared_with_baseline": len(shared_with_bl),
            "new_in_this_variant_only": len(new_in_v),
            "in_baseline_but_lost": len(bl_only),
            "frac_pairs_already_known_from_bl": round(len(shared_with_bl) / len(vp), 4) if vp else 0,
            "frac_pairs_genuinely_new": round(len(new_in_v) / len(vp), 4) if vp else 0,
            "per_day_distinct_pairs_total": variant_per_day[v],
        }
    return results, variant_pairs


# Run
all_results = {}
all_variant_pairs = {}  # seed -> variant -> set
for s in [44, 45]:
    r, vp = analyse_seed(s)
    all_results[s] = r
    all_variant_pairs[s] = vp

# Combine across seeds: union pairs per variant, then redo overlap
print("\n=== COMBINED (seed 44 ∪ 45) ===")
combined_pairs = {}
for v in VARIANTS:
    combined_pairs[v] = set()
    for s in [44, 45]:
        if v in all_variant_pairs.get(s, {}):
            combined_pairs[v] |= all_variant_pairs[s][v]
    print(f"  {v:22s}: union {len(combined_pairs[v])} pairs")

bl_combined = combined_pairs["baseline"]
combined_results = {}
for v in VARIANTS:
    vp = combined_pairs[v]
    shared = vp & bl_combined
    new = vp - bl_combined
    combined_results[v] = {
        "total_unique_pairs": len(vp),
        "shared_with_baseline": len(shared),
        "new_pairs": len(new),
        "frac_already_known": round(len(shared) / len(vp), 4) if vp else 0,
        "frac_new": round(len(new) / len(vp), 4) if vp else 0,
    }

# Write
json.dump({
    "method": "tick_metrics_recorder_state.buckets.{day}.distinct_pairs",
    "seeds": [44, 45],
    "per_seed": all_results,
    "combined": combined_results,
}, open(OUT / "h17_familiarity.json", "w"), ensure_ascii=False, indent=2)

# Headline
print("\n" + "=" * 60)
print("H17 · HP 增加的 pair 是已认识 vs 新陌生? (combined)")
for v in VARIANTS:
    r = combined_results[v]
    print(f"  {v:22s}: total {r['total_unique_pairs']:6d} | shared w/ BL {r['shared_with_baseline']:6d} ({r['frac_already_known']*100:5.1f}%) | new {r['new_pairs']:6d} ({r['frac_new']*100:5.1f}%)")

# Net change vs BL
bl_n = combined_results["baseline"]["total_unique_pairs"]
print(f"\nNet pair count change vs BL ({bl_n}):")
for v in ["hyperlocal_push", "global_distraction", "phone_friction"]:
    n = combined_results[v]["total_unique_pairs"]
    delta = n - bl_n
    new = combined_results[v]["new_pairs"]
    print(f"  {v:22s}: total {n:6d} (Δ {delta:+5d}, ratio {n/bl_n:.2f}×), new pairs {new}")

print(f"\n✓ output: {OUT / 'h17_familiarity.json'}")
