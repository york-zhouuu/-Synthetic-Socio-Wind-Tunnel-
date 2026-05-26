"""F3 · The hub-shape of awareness · pair-level concentration.

Since the simulation's attention gate is bilateral (proven in
f3_asymmetry.py: 0 one-way pairs in 82K observations), "asymmetric
awareness" doesn't exist as a measurable structure here.

This pivot measures CONCENTRATION instead: across the universe of
(A, B) sorted pairs that experience at least one physical co-presence,
how unequally is the mutual-notice volume distributed?

Pair-level statistics:
  - For each sorted pair, count UNIQUE physical co-presences where both
    sides cleared the attention gate (n_mutual).
  - Compute Lorenz curve at the pair level: what % of pair universe
    accounts for what % of total mutual notices?

Per-agent statistics:
  - For each agent A, build {partner_id: n_mutual} dict.
  - Compute top-K share: what fraction of A's mutual notices comes
    from their K most-noticed partners (K = 1, 3, 5, 10)?
  - Compute n_distinct_partners ever noticed.

Constraint: snapshot in-memory ~= recent 2 days; this is a TWO-WEEKDAY
concentration profile.
"""
import ijson
import json
from pathlib import Path
from collections import defaultdict
from statistics import median, mean

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
OUT = REPO / "data/analysis/2026-05-24_hypothesis_validation/F3_asymmetry"
OUT.mkdir(parents=True, exist_ok=True)

SEED_DIRS = {
    44: REPO / "data/experiments/20260522_165045_publishable_v7_day4to13_fork_seed44_BACKUP_20260522_213319_FULL_ALLVARIANTS",
    45: REPO / "data/experiments/20260522_212423_publishable_v7_day4to13_fork_seed45_BACKUP_20260523_022549_FULL_ALLVARIANTS",
}


def get_snap_path(seed, variant):
    d = SEED_DIRS[seed] / f"variant_{variant}"
    return next(d.glob(f"seed_{seed}_pid*_tick*.snapshot.json"))


def analyze_seed(seed):
    snap = get_snap_path(seed, "baseline")
    print(f"\n=== SEED {seed} BL · {snap.name} "
          f"({snap.stat().st_size/1e6:.0f}MB) ===", flush=True)

    # Pair table: (sorted_pair, tick, loc) → {observer: noticed_bool}
    enc_table: dict[tuple, dict[str, bool]] = {}

    with open(snap) as f:
        ai = 0
        for aid, events in ijson.kvitems(f, "memory_store_state.agent_events"):
            ai += 1
            if ai % 200 == 0:
                print(f"  {ai}/1000", flush=True)
            for ev in events:
                if ev.get("kind") != "encounter":
                    continue
                a = aid
                b = ev.get("actor_id")
                if not b or b == a:
                    continue
                tick = ev.get("tick")
                loc = ev.get("location_id") or ""
                noticed = "noticed" in (ev.get("tags") or [])
                pair = tuple(sorted([a, b]))
                key = (pair, tick, loc)
                enc_table.setdefault(key, {})[a] = noticed
    return enc_table


def compute_pair_notice_counts(enc_table):
    """For each sorted pair, count UNIQUE physical mutual-noticed events."""
    pair_notice = defaultdict(int)        # pair → mutual notice count
    pair_total = defaultdict(int)         # pair → total physical co-presences
    for (pair, tick, loc), slot in enc_table.items():
        pair_total[pair] += 1
        if len(slot) == 2 and all(slot.values()):
            pair_notice[pair] += 1
    return dict(pair_notice), dict(pair_total)


def per_agent_partner_counts(pair_notice):
    """agent → {partner: notice_count}."""
    per_agent = defaultdict(lambda: defaultdict(int))
    for (a, b), n in pair_notice.items():
        if n <= 0:
            continue
        per_agent[a][b] += n
        per_agent[b][a] += n
    return per_agent


def per_agent_concentration(per_agent_partners):
    rows = []
    for aid, partners in per_agent_partners.items():
        total = sum(partners.values())
        if total < 5:  # too few notices to compute concentration meaningfully
            continue
        sorted_vals = sorted(partners.values(), reverse=True)
        n_partners = len(sorted_vals)

        def top_k_share(k):
            return sum(sorted_vals[:k]) / total if total else 0

        rows.append({
            "agent_id": aid,
            "n_total_noticed": total,
            "n_distinct_partners": n_partners,
            "top1_share": round(top_k_share(1), 4),
            "top3_share": round(top_k_share(3), 4),
            "top5_share": round(top_k_share(5), 4),
            "top10_share": round(top_k_share(10), 4),
        })
    return rows


def lorenz(values):
    """Returns x = cumulative % of population (pairs), y = cumulative %
    of total (notice volume). Sorted descending by notice."""
    sorted_v = sorted(values, reverse=True)
    total = sum(sorted_v)
    n = len(sorted_v)
    xs = [0.0]
    ys = [0.0]
    cum = 0
    for i, v in enumerate(sorted_v, 1):
        cum += v
        xs.append(i / n * 100)
        ys.append(cum / total * 100)
    return xs, ys


def gini(values):
    """Standard Gini on sorted ascending values."""
    sorted_v = sorted(values)
    n = len(sorted_v)
    if n == 0 or sum(sorted_v) == 0:
        return 0
    cum = 0
    g = 0
    for i, v in enumerate(sorted_v, 1):
        cum += v
        g += (n + 1 - i) * v
    return 1 - 2 * g / (n * cum) + 1 / n


# ============== run ==============

pool_pair_notice = defaultdict(int)
pool_pair_total = defaultdict(int)
pool_per_agent_partners = defaultdict(lambda: defaultdict(int))

for s in [44, 45]:
    enc_table = analyze_seed(s)
    pair_notice, pair_total = compute_pair_notice_counts(enc_table)
    print(f"  seed {s}: pairs={len(pair_total):,d}  "
          f"mutual-noticed pairs={sum(1 for v in pair_notice.values() if v>0):,d}  "
          f"total mutual events={sum(pair_notice.values()):,d}")
    for k, v in pair_notice.items():
        pool_pair_notice[k] += v
    for k, v in pair_total.items():
        pool_pair_total[k] += v

# Pool per-agent partners across seeds (each agent appears once per seed)
per_agent_partners_per_seed = defaultdict(lambda: defaultdict(int))
for s in [44, 45]:
    # rebuild for each seed (we already lost the per-seed dict above)
    enc_table = analyze_seed(s) if False else None  # reuse via pool — fine
# Simpler: just compute per-agent partners from pooled pair_notice
per_agent_partners = per_agent_partner_counts(pool_pair_notice)

# Pair concentration
pair_values = [v for v in pool_pair_notice.values() if v > 0]
print("\n" + "=" * 70)
print(f"PAIR-LEVEL CONCENTRATION (n={len(pair_values):,d} pairs with ≥1 mutual notice)")
print(f"  total mutual-notice events: {sum(pair_values):,d}")
print(f"  pair-level Gini: {gini(pair_values):.3f}")

# Lorenz milestones
xs, ys = lorenz(pair_values)
for milestone_pct in [10, 20, 50]:
    # x is cum % of pairs, y is cum % of notices
    # find first x >= milestone_pct, report y
    idx = next((i for i, x in enumerate(xs) if x >= milestone_pct), len(xs)-1)
    print(f"  top {milestone_pct}% of pairs absorb {ys[idx]:.1f}% of mutual notices")

# Distribution of pair notice counts
from collections import Counter
notice_count_dist = Counter(pair_values)
print("\nPair notice count distribution:")
for c in sorted(notice_count_dist.keys())[:15]:
    print(f"  count={c:>3d}  pairs={notice_count_dist[c]:>6,d}")
print(f"  ... max={max(notice_count_dist.keys())}")

# Per-agent concentration
agent_rows = per_agent_concentration(per_agent_partners)
print(f"\nPER-AGENT CONCENTRATION (n={len(agent_rows):,d} agents w/ >=5 noticed)")
if agent_rows:
    for k in ["top1_share", "top3_share", "top5_share", "top10_share"]:
        vals = [r[k] for r in agent_rows]
        print(f"  {k:14s}  median {median(vals)*100:5.1f}%  mean {mean(vals)*100:5.1f}%")
    print()
    n_partner_vals = [r["n_distinct_partners"] for r in agent_rows]
    n_total_vals = [r["n_total_noticed"] for r in agent_rows]
    print(f"  n_distinct_partners:  median {median(n_partner_vals):.0f}  "
          f"mean {mean(n_partner_vals):.1f}")
    print(f"  n_total_noticed:      median {median(n_total_vals):.0f}  "
          f"mean {mean(n_total_vals):.1f}")

# Stranger (1-time) vs repeat (>1) split of total notice volume
n_stranger_pairs = sum(1 for v in pair_values if v == 1)
n_repeat_pairs = sum(1 for v in pair_values if v > 1)
n_stranger_notices = sum(v for v in pair_values if v == 1)
n_repeat_notices = sum(v for v in pair_values if v > 1)
n_total_notices = sum(pair_values)
print(f"\nSTRANGER vs REPEAT split:")
print(f"  1-time pairs: {n_stranger_pairs:,d} ({100*n_stranger_pairs/len(pair_values):.1f}%) "
      f"→ {n_stranger_notices:,d} notices ({100*n_stranger_notices/n_total_notices:.1f}%)")
print(f"  repeat pairs: {n_repeat_pairs:,d} ({100*n_repeat_pairs/len(pair_values):.1f}%) "
      f"→ {n_repeat_notices:,d} notices ({100*n_repeat_notices/n_total_notices:.1f}%)")
mean_rep_per_repeat = n_repeat_notices / n_repeat_pairs if n_repeat_pairs else 0
print(f"  avg notices per repeat pair: {mean_rep_per_repeat:.1f}")

# Build Lorenz xy for output
lorenz_xs, lorenz_ys = lorenz(pair_values)

# Save
out_data = {
    "method": "BL pooled seed 44+45 · snapshot in-memory encounter events. "
              "Pair-level mutual notice count from de-duped (sorted_pair, tick, location) keys "
              "where both observers cleared the attention gate. Per-agent partner counts "
              "derived from pair_notice. Per-agent concentration filtered to agents with "
              ">=5 total noticed events.",
    "n_pairs_with_mutual": len(pair_values),
    "total_mutual_events": sum(pair_values),
    "gini": round(gini(pair_values), 4),
    "lorenz_milestones": {
        "top_10pct_pairs_absorb_pct": round(ys[next(i for i, x in enumerate(xs) if x >= 10)], 2),
        "top_20pct_pairs_absorb_pct": round(ys[next(i for i, x in enumerate(xs) if x >= 20)], 2),
        "top_50pct_pairs_absorb_pct": round(ys[next(i for i, x in enumerate(xs) if x >= 50)], 2),
    },
    "stranger_vs_repeat": {
        "n_stranger_pairs": n_stranger_pairs,
        "n_repeat_pairs": n_repeat_pairs,
        "stranger_notices": n_stranger_notices,
        "repeat_notices": n_repeat_notices,
        "stranger_pair_pct": round(100*n_stranger_pairs/len(pair_values), 2),
        "stranger_notice_pct": round(100*n_stranger_notices/n_total_notices, 2),
        "repeat_notice_pct": round(100*n_repeat_notices/n_total_notices, 2),
        "avg_notices_per_repeat_pair": round(mean_rep_per_repeat, 2),
    },
    "pair_notice_count_distribution": {
        str(c): notice_count_dist[c] for c in sorted(notice_count_dist.keys())
    },
    "per_agent_concentration_rows": agent_rows,
    "agent_summary": {
        "n_agents": len(agent_rows),
        "top1_median_pct": round(median([r["top1_share"] for r in agent_rows])*100, 2)
                            if agent_rows else 0,
        "top3_median_pct": round(median([r["top3_share"] for r in agent_rows])*100, 2)
                            if agent_rows else 0,
        "top5_median_pct": round(median([r["top5_share"] for r in agent_rows])*100, 2)
                            if agent_rows else 0,
        "top10_median_pct": round(median([r["top10_share"] for r in agent_rows])*100, 2)
                             if agent_rows else 0,
        "n_distinct_partners_median": median([r["n_distinct_partners"] for r in agent_rows])
                                       if agent_rows else 0,
        "n_total_noticed_median": median([r["n_total_noticed"] for r in agent_rows])
                                   if agent_rows else 0,
    },
    "lorenz_xs": [round(x, 3) for x in lorenz_xs],
    "lorenz_ys": [round(y, 3) for y in lorenz_ys],
}
out_path = OUT / "f3_concentration_baseline.json"
json.dump(out_data, open(out_path, "w"), ensure_ascii=False, indent=2)
print(f"\n✓ {out_path}  ({out_path.stat().st_size//1024} KB)")
