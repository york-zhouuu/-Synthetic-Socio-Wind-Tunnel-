"""F3 · Asymmetry · how often is awareness mutual?

For each physical co-presence between agents A and B at (tick, location),
both A and B emit their own encounter event with the noticed/unnoticed tag.
We pair them up and classify each unique physical co-presence as:

  - MUTUAL       — both A and B cleared the attention gate
  - ONE-WAY      — exactly one of them noticed; the other didn't
  - BOTH MISSED  — neither noticed (just physical adjacency)
  - HALF-OBSERVED — only one of the two events found in snapshot
                    (the other side was evicted or out of sample)

Per-agent we also count two ratios per agent:
  - noticing_rate = (noticed_others) / (total_encounters_as_observer)
  - noticed_by_rate = (others_noticed_me) / (total_encounters_where_im_actor)

Diagonal line on a scatter = "balanced" (you see as much as you are seen).
Above diagonal = "ghost" agents (visible to others, blind themselves).
Below diagonal = "super-noticers" (see a lot, less seen).

Constraint as in F1/F2: snapshot in-memory events ≈ recent 2 days.
"""
import ijson
import json
from pathlib import Path
from collections import defaultdict, Counter
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


def analyze(seed):
    snap = get_snap_path(seed, "baseline")
    print(f"\n=== SEED {seed} BL · {snap.name} ({snap.stat().st_size/1e6:.0f}MB) ===",
          flush=True)

    # Per-encounter table: key=(pair_sorted, tick, location) → {observer_id: noticed_bool}
    enc_table: dict[tuple, dict[str, bool]] = {}
    # Per-agent counters
    per_agent = defaultdict(lambda: {
        "n_obs": 0,        # total events where agent was observer
        "n_noticed": 0,    # of those, how many cleared attention gate
        "n_actor": 0,      # times this agent was the actor (other side observed them)
        "n_noticed_by": 0, # of those, how many times others actually noticed them
    })

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
                if not b:
                    continue
                tick = ev.get("tick")
                loc = ev.get("location_id") or ""
                noticed = "noticed" in (ev.get("tags") or [])

                # Per-agent observer stats (this event = agent a observing b)
                per_agent[a]["n_obs"] += 1
                if noticed:
                    per_agent[a]["n_noticed"] += 1

                # Pair key (sorted to merge both directions)
                pair = tuple(sorted([a, b]))
                key = (pair, tick, loc)
                slot = enc_table.setdefault(key, {})
                slot[a] = noticed
    # End of file walk
    return enc_table, per_agent


def classify(enc_table) -> dict:
    """Classify each unique physical co-presence."""
    n_total = len(enc_table)
    n_both_observed = 0
    n_mutual = 0
    n_oneway = 0
    n_both_missed = 0
    n_half = 0

    for (pair, tick, loc), slot in enc_table.items():
        if len(slot) == 2:
            n_both_observed += 1
            notes = list(slot.values())
            if all(notes):
                n_mutual += 1
            elif any(notes):
                n_oneway += 1
            else:
                n_both_missed += 1
        else:
            n_half += 1

    return {
        "n_pairs_total": n_total,
        "n_both_observed": n_both_observed,
        "n_half_observed": n_half,
        "n_mutual": n_mutual,
        "n_oneway": n_oneway,
        "n_both_missed": n_both_missed,
    }


def actor_stats(enc_table, per_agent_seed):
    """Compute per-agent 'how many times others noticed me' from pair table."""
    actor_acc = defaultdict(lambda: {"n_actor": 0, "n_noticed_by": 0})
    for (pair, tick, loc), slot in enc_table.items():
        # For each side, the OTHER side's notice value tells whether that other
        # side noticed this agent. So agent a's n_noticed_by += slot.get(b, ...).
        for observer, noticed in slot.items():
            other = pair[0] if observer == pair[1] else pair[1]
            actor_acc[other]["n_actor"] += 1
            if noticed:
                actor_acc[other]["n_noticed_by"] += 1
    # Merge into per_agent_seed
    for aid, st in actor_acc.items():
        per_agent_seed[aid]["n_actor"] = st["n_actor"]
        per_agent_seed[aid]["n_noticed_by"] = st["n_noticed_by"]


# Pool across seeds at PAIR level (events with same key but different seeds are
# different physical events) — so just accumulate counts independently per seed,
# then sum.
pool_class = {"n_pairs_total": 0, "n_both_observed": 0, "n_half_observed": 0,
              "n_mutual": 0, "n_oneway": 0, "n_both_missed": 0}
all_agent_rows = []  # per-agent rows for scatter; one row per (agent, seed)

for s in [44, 45]:
    enc_table, per_agent = analyze(s)
    actor_stats(enc_table, per_agent)
    cls = classify(enc_table)
    print(f"  seed {s}: pairs={cls['n_pairs_total']:,d}  "
          f"both_obs={cls['n_both_observed']:,d}  "
          f"half={cls['n_half_observed']:,d}  "
          f"mutual={cls['n_mutual']:,d}  "
          f"oneway={cls['n_oneway']:,d}  "
          f"missed={cls['n_both_missed']:,d}")
    for k in pool_class:
        pool_class[k] += cls[k]

    # Save per-agent rows (only agents with enough samples on BOTH sides)
    for aid, st in per_agent.items():
        if st["n_obs"] >= 20 and st["n_actor"] >= 20:
            noticing_rate = st["n_noticed"] / st["n_obs"]
            noticed_by_rate = st["n_noticed_by"] / st["n_actor"]
            all_agent_rows.append({
                "agent_id": aid,
                "seed": s,
                "n_obs": st["n_obs"],
                "n_noticed": st["n_noticed"],
                "noticing_rate": round(noticing_rate, 4),
                "n_actor": st["n_actor"],
                "n_noticed_by": st["n_noticed_by"],
                "noticed_by_rate": round(noticed_by_rate, 4),
                "delta": round(noticed_by_rate - noticing_rate, 4),
            })

# Summary
print("\n" + "=" * 70)
print(f"POOLED PHYSICAL CO-PRESENCES:")
print(f"  total pairs:        {pool_class['n_pairs_total']:>9,d}")
print(f"  both sides in snap: {pool_class['n_both_observed']:>9,d}"
      f"  ({100*pool_class['n_both_observed']/pool_class['n_pairs_total']:.1f}%)")
print(f"  half-observed:      {pool_class['n_half_observed']:>9,d}"
      f"  ({100*pool_class['n_half_observed']/pool_class['n_pairs_total']:.1f}%)")

bo = pool_class["n_both_observed"]
if bo:
    pct_m = 100 * pool_class["n_mutual"] / bo
    pct_o = 100 * pool_class["n_oneway"] / bo
    pct_n = 100 * pool_class["n_both_missed"] / bo
    print(f"\nOf BOTH-OBSERVED pairs (n={bo:,}):")
    print(f"  MUTUAL noticed:     {pool_class['n_mutual']:>9,d}  ({pct_m:5.2f}%)")
    print(f"  ONE-WAY noticed:    {pool_class['n_oneway']:>9,d}  ({pct_o:5.2f}%)")
    print(f"  both missed:        {pool_class['n_both_missed']:>9,d}  ({pct_n:5.2f}%)")

# Of noticed events at all, what share are mutual vs one-way
n_noticed_events = pool_class["n_oneway"] + 2 * pool_class["n_mutual"]
# Each mutual = 2 noticed events; each one-way = 1
print(f"\nOf all NOTICED events (n={n_noticed_events:,}):")
if n_noticed_events:
    mutual_evs = 2 * pool_class["n_mutual"]
    oneway_evs = pool_class["n_oneway"]
    print(f"  from mutual pairs:  {mutual_evs:>9,d}  "
          f"({100*mutual_evs/n_noticed_events:.1f}%)")
    print(f"  from one-way pairs: {oneway_evs:>9,d}  "
          f"({100*oneway_evs/n_noticed_events:.1f}%)")

# Per-agent scatter summary
print(f"\nPer-agent scatter rows (n_obs>=20 AND n_actor>=20): {len(all_agent_rows):,}")
if all_agent_rows:
    nrs = [r["noticing_rate"] for r in all_agent_rows]
    nbrs = [r["noticed_by_rate"] for r in all_agent_rows]
    deltas = [r["delta"] for r in all_agent_rows]
    print(f"  noticing_rate    median {median(nrs)*100:.2f}%  mean {mean(nrs)*100:.2f}%")
    print(f"  noticed_by_rate  median {median(nbrs)*100:.2f}%  mean {mean(nbrs)*100:.2f}%")
    print(f"  delta (by - rate) median {median(deltas)*100:+.2f}pp  mean {mean(deltas)*100:+.2f}pp")
    # ghost / super-noticer counts
    n_ghost = sum(1 for r in all_agent_rows if r["delta"] > 0.02)
    n_super = sum(1 for r in all_agent_rows if r["delta"] < -0.02)
    n_bal = len(all_agent_rows) - n_ghost - n_super
    print(f"  ghosts (delta > +2pp):       {n_ghost:>4d}")
    print(f"  super-noticers (delta < -2pp): {n_super:>4d}")
    print(f"  balanced (within ±2pp):      {n_bal:>4d}")

# Save
out_data = {
    "method": "BL pooled seed 44+45 · snapshot in-memory encounter events. Pair-level mutual vs one-way classification on (sorted_pair, tick, location) key. Per-agent scatter requires n_obs >= 20 AND n_actor >= 20.",
    "pooled_classification": pool_class,
    "pct_of_both_observed": {
        "mutual_pct": round(100 * pool_class["n_mutual"] / max(bo, 1), 2),
        "oneway_pct": round(100 * pool_class["n_oneway"] / max(bo, 1), 2),
        "both_missed_pct": round(100 * pool_class["n_both_missed"] / max(bo, 1), 2),
    },
    "noticed_event_breakdown": {
        "total_noticed_events": n_noticed_events,
        "from_mutual_pairs": 2 * pool_class["n_mutual"],
        "from_oneway_pairs": pool_class["n_oneway"],
        "mutual_share_pct": round(100 * 2 * pool_class["n_mutual"] / max(n_noticed_events, 1), 2),
        "oneway_share_pct": round(100 * pool_class["n_oneway"] / max(n_noticed_events, 1), 2),
    },
    "per_agent_rows": all_agent_rows,
}
out_path = OUT / "f3_asymmetry_baseline.json"
json.dump(out_data, open(out_path, "w"), ensure_ascii=False, indent=2)
print(f"\n✓ {out_path}  ({out_path.stat().st_size//1024} KB)")
