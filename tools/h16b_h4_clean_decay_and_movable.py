"""H16b: 排除"推送到达时 agent 已在 target"的 noise, 重算真衰减曲线
N4_profile: BL↔HP 末态距离 >100m 的 ~30% movable agents 是谁?demographic profile

主参考: seed 44 + 45
"""
import ijson
import json
import math
import os
from pathlib import Path
from collections import defaultdict, Counter
from statistics import median, mean

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
OUT = REPO / "data/analysis/2026-05-24_hypothesis_validation"
OUT_H16B = OUT / "H16b_clean_decay"; OUT_H16B.mkdir(parents=True, exist_ok=True)
OUT_N4 = OUT / "N4_movable_profile"; OUT_N4.mkdir(parents=True, exist_ok=True)

ATLAS = REPO / "data/lanecove_atlas.json"
POP_CACHE = REPO / "data/population_cache/v1"

SEED_DIRS = {
    44: REPO / "data/experiments/20260522_165045_publishable_v7_day4to13_fork_seed44_BACKUP_20260522_213319_FULL_ALLVARIANTS",
    45: REPO / "data/experiments/20260522_212423_publishable_v7_day4to13_fork_seed45_BACKUP_20260523_022549_FULL_ALLVARIANTS",
}


def get_snap_path(seed, variant):
    d = SEED_DIRS[seed] / f"variant_{variant}"
    return next(d.glob(f"seed_{seed}_pid*_tick*.snapshot.json"))


def get_pos_path(seed, variant):
    d = SEED_DIRS[seed] / f"variant_{variant}"
    return d / f"seed_{seed}_positions.json"


print("Loading atlas centroids...", flush=True)
atlas = json.load(open(ATLAS))
loc_xy = {}
for bid, b in atlas["buildings"].items():
    verts = b.get("polygon", {}).get("vertices", [])
    if verts:
        xs = [v["x"] for v in verts]; ys = [v["y"] for v in verts]
        loc_xy[bid] = (sum(xs)/len(xs), sum(ys)/len(ys))
out = atlas.get("outdoor_areas", {})
out_iter = out.items() if isinstance(out, dict) else [(o["id"], o) for o in out]
for oid, o in out_iter:
    verts = o.get("polygon", {}).get("vertices", [])
    if verts:
        xs = [v["x"] for v in verts]; ys = [v["y"] for v in verts]
        loc_xy[oid] = (sum(xs)/len(xs), sum(ys)/len(ys))
print(f"  {len(loc_xy)} centroids", flush=True)


def load_profiles(seed):
    profiles = {}
    for f in os.listdir(POP_CACHE):
        d = json.load(open(POP_CACHE / f))
        if d.get("key_inputs", {}).get("seed") != seed:
            continue
        for p in d.get("profiles", []):
            aid = p.get("agent_id")
            if aid:
                profiles[aid] = p
    return profiles


def parse_delivered_at(s, anchor_iso="2026-04-22T00:00:00"):
    from datetime import datetime
    if not s: return None
    try:
        dt = datetime.fromisoformat(s)
        anchor = datetime.fromisoformat(anchor_iso)
        total_min = int((dt - anchor).total_seconds() / 60)
        return (total_min // (24*60), (total_min % (24*60)) // 5)
    except Exception:
        return None


def parse_topic_loc(content):
    import re
    m = re.match(r"^([a-z_,]+)\s", content)
    return m.group(1) if m else None


# ============================================================
# H16b: Clean decay - exclude "already at target when push arrives"
# ============================================================

print("\n" + "=" * 60)
print("H16b · CLEAN DECAY CURVE (exclude pre-existing at target)")

clean_decay_combined = Counter()
already_there_count = 0
true_responder_count = 0
never_arrived_count = 0
total_deliveries = 0

per_seed_results = {}

for seed in [44, 45]:
    print(f"\n  === seed {seed} ===", flush=True)
    snap = get_snap_path(seed, "hyperlocal_push")
    pos = get_pos_path(seed, "hyperlocal_push")

    # feed
    feed = {}
    print(f"    reading feed_index from {snap.name}...", flush=True)
    with open(snap) as f:
        for fid, item in ijson.kvitems(f, "attention_service_state.feed_index"):
            loc = parse_topic_loc(item.get("content", ""))
            if loc:
                feed[fid] = loc

    # delivery
    deliveries = []
    print(f"    reading delivery_log...", flush=True)
    with open(snap) as f:
        for entry in ijson.items(f, "attention_service_state.delivery_log.item"):
            if entry.get("delivered"):
                fid = entry.get("feed_item_id")
                if fid in feed:
                    deliveries.append({
                        "fid": fid,
                        "aid": entry.get("recipient_id"),
                        "dt": entry.get("delivered_at"),
                        "target": feed[fid],
                    })
    print(f"    {len(deliveries)} delivered pushes with known target", flush=True)

    # positions per agent (sorted by global tick)
    print(f"    reading positions...", flush=True)
    d = json.load(open(pos))
    trails = defaultdict(list)
    for c in d["changes"]:
        trails[c["agent_id"]].append((c["day"] * 288 + c["tick"], c["location_id"]))
    for aid in trails:
        trails[aid].sort()

    seed_decay = Counter()
    seed_already_there = 0
    seed_true_responders = 0
    seed_never = 0
    n_proc = 0
    for d_entry in deliveries:
        n_proc += 1
        if n_proc % 2000 == 0:
            print(f"      processing {n_proc}/{len(deliveries)}", flush=True)
        aid = d_entry["aid"]
        target = d_entry["target"]
        dt = parse_delivered_at(d_entry["dt"])
        if dt is None or aid not in trails:
            continue
        push_tick = dt[0] * 288 + dt[1]
        trail = trails[aid]
        # find agent location at push_tick
        # bisect: find last position change at or before push_tick
        from bisect import bisect_right
        idx = bisect_right([t[0] for t in trail], push_tick) - 1
        loc_at_push = trail[idx][1] if idx >= 0 else None

        if loc_at_push == target:
            seed_already_there += 1
            continue  # exclude - already there

        # find first arrival at target STRICTLY AFTER push_tick
        arrived_at = None
        for t, loc in trail:
            if t <= push_tick:
                continue
            if loc == target:
                arrived_at = t
                break

        if arrived_at is None:
            seed_never += 1
            continue

        elapsed_ticks = arrived_at - push_tick
        elapsed_h = elapsed_ticks * 5 / 60
        if elapsed_h < 1: b = "0-1h"
        elif elapsed_h < 3: b = "1-3h"
        elif elapsed_h < 6: b = "3-6h"
        elif elapsed_h < 12: b = "6-12h"
        elif elapsed_h < 24: b = "12-24h"
        elif elapsed_h < 48: b = "24-48h"
        elif elapsed_h < 96: b = "48-96h"
        else: b = "96h+"
        seed_decay[b] += 1
        seed_true_responders += 1

    per_seed_results[seed] = {
        "deliveries": len(deliveries),
        "already_at_target": seed_already_there,
        "true_responders": seed_true_responders,
        "never_arrived": seed_never,
        "decay_buckets": dict(seed_decay),
    }
    print(f"    already_there: {seed_already_there}  true_responders: {seed_true_responders}  never: {seed_never}", flush=True)

    for k, v in seed_decay.items():
        clean_decay_combined[k] += v
    already_there_count += seed_already_there
    true_responder_count += seed_true_responders
    never_arrived_count += seed_never
    total_deliveries += len(deliveries)


print("\n" + "=" * 60)
print("H16b · COMBINED clean decay (seed 44+45)")
print(f"  Total delivered:     {total_deliveries}")
print(f"  Already at target:   {already_there_count} ({already_there_count/total_deliveries*100:.1f}%)  [excluded]")
print(f"  True responders:     {true_responder_count} ({true_responder_count/total_deliveries*100:.1f}%)")
print(f"  Never arrived:       {never_arrived_count} ({never_arrived_count/total_deliveries*100:.1f}%)")
print()
print("True-responder decay (denominator = true responders):")
total_clean = sum(clean_decay_combined.values())
for b in ["0-1h", "1-3h", "3-6h", "6-12h", "12-24h", "24-48h", "48-96h", "96h+"]:
    n = clean_decay_combined.get(b, 0)
    print(f"  {b:10s} {n:6d}  ({n/total_clean*100:5.1f}%)")

json.dump({
    "method": "exclude deliveries where agent already at target_loc at push tick",
    "per_seed": per_seed_results,
    "combined": {
        "total_delivered": total_deliveries,
        "already_at_target": already_there_count,
        "true_responders": true_responder_count,
        "never_arrived": never_arrived_count,
        "decay_buckets": dict(clean_decay_combined),
        "decay_pct": {b: round(c/total_clean*100, 2) for b, c in clean_decay_combined.items()},
    },
}, open(OUT_H16B / "h16b_clean_decay.json", "w"), ensure_ascii=False, indent=2)
print(f"\n✓ {OUT_H16B / 'h16b_clean_decay.json'}")


# ============================================================
# N4: Who are the 30% movable?
# ============================================================
print("\n" + "=" * 60)
print("N4 · MOVABLE 30% — demographic profile")
print("=" * 60)


def dist_m(a, b):
    if a not in loc_xy or b not in loc_xy: return None
    return math.hypot(loc_xy[a][0]-loc_xy[b][0], loc_xy[a][1]-loc_xy[b][1])


def load_end_locs(snap_path):
    end = {}
    with open(snap_path) as f:
        for aid, e in ijson.kvitems(f, "ledger_state.entities"):
            loc = e.get("location_id")
            if loc:
                end[aid] = loc
    return end


# Load BL + HP end_locs per seed + profiles
movable_agents = []  # list of (seed, aid, drift_m, profile)
nonmovable_agents = []

for seed in [44, 45]:
    print(f"\n  === seed {seed} ===", flush=True)
    profs = load_profiles(seed)
    bl_end = load_end_locs(get_snap_path(seed, "baseline"))
    hp_end = load_end_locs(get_snap_path(seed, "hyperlocal_push"))
    print(f"    profiles {len(profs)} | BL {len(bl_end)} HP {len(hp_end)}", flush=True)

    for aid in set(bl_end) & set(hp_end):
        if aid not in profs:
            continue
        d = dist_m(bl_end[aid], hp_end[aid])
        if d is None:
            continue
        p = profs[aid]
        rec = (seed, aid, d, p)
        if d > 100:
            movable_agents.append(rec)
        else:
            nonmovable_agents.append(rec)

print(f"\n  movable (>100m drift BL↔HP):  {len(movable_agents)}")
print(f"  non-movable:                   {len(nonmovable_agents)}")


def get_age_bucket(age):
    if age < 18: return "child<18"
    if age < 25: return "18-24"
    if age < 35: return "25-34"
    if age < 45: return "35-44"
    if age < 55: return "45-54"
    if age < 65: return "55-64"
    if age < 75: return "65-74"
    return "75+"


def cross_tab(field_fn, label, movs=movable_agents, nons=nonmovable_agents):
    """For a profile-field-fn returning a category, compute:
    - distribution among movable vs non-movable
    - response rate per category = movable / (movable + non)
    """
    mov_counts = Counter()
    non_counts = Counter()
    for _, _, _, p in movs:
        mov_counts[field_fn(p)] += 1
    for _, _, _, p in nons:
        non_counts[field_fn(p)] += 1
    all_cats = sorted(set(mov_counts) | set(non_counts))
    rows = []
    for c in all_cats:
        m = mov_counts.get(c, 0)
        n = non_counts.get(c, 0)
        total = m + n
        rate = m / total if total else 0
        rows.append((c, m, n, total, rate))
    rows.sort(key=lambda x: -x[4])  # by rate desc
    print(f"\n  {label}")
    print(f"    {'category':<25s} {'mov':>5s} {'non':>5s} {'tot':>5s} {'rate':>7s}")
    for c, m, n, t, r in rows:
        print(f"    {str(c)[:25]:<25s} {m:5d} {n:5d} {t:5d} {r*100:6.1f}%")
    return rows


def get_age(p):
    a = p.get("age", 0)
    return get_age_bucket(a) if isinstance(a, (int, float)) else "unknown"


def get_personality_bucket(p, key):
    v = (p.get("personality") or {}).get(key)
    if v is None: return "unknown"
    if v < 0.33: return f"{key} low (<0.33)"
    if v < 0.67: return f"{key} mid"
    return f"{key} high (>0.67)"


# Run cross tabs
print("\nN4 cross-tab summary (rate = fraction movable per category)")
res_age = cross_tab(get_age, "by age bucket")
res_occ = cross_tab(lambda p: p.get("occupation", "unknown"), "by occupation")
res_hh = cross_tab(lambda p: p.get("household", "unknown"), "by household")
res_inc = cross_tab(lambda p: p.get("income_tier", "unknown"), "by income_tier")
res_ten = cross_tab(lambda p: p.get("housing_tenure", "unknown"), "by housing_tenure")
res_eth = cross_tab(lambda p: p.get("ethnicity_group", "unknown"), "by ethnicity")
res_gen = cross_tab(lambda p: p.get("gender", "unknown"), "by gender")
res_pro = cross_tab(lambda p: "protagonist" if p.get("is_protagonist") else "non-protagonist", "by is_protagonist")
res_ext = cross_tab(lambda p: get_personality_bucket(p, "extraversion"), "by extraversion bucket")
res_open = cross_tab(lambda p: get_personality_bucket(p, "openness"), "by openness bucket")
res_neur = cross_tab(lambda p: get_personality_bucket(p, "neuroticism"), "by neuroticism bucket")
res_risk = cross_tab(lambda p: get_personality_bucket(p, "risk_tolerance"), "by risk_tolerance")
res_rout = cross_tab(lambda p: get_personality_bucket(p, "routine_adherence"), "by routine_adherence")

json.dump({
    "method": "BL vs HP end_location drift >100m = movable",
    "movable_n": len(movable_agents),
    "nonmovable_n": len(nonmovable_agents),
    "movable_rate": round(len(movable_agents)/(len(movable_agents)+len(nonmovable_agents)), 4),
    "by_age": [{"cat": c, "movable": m, "nonmov": n, "total": t, "rate": round(r, 4)} for c,m,n,t,r in res_age],
    "by_occupation": [{"cat": c, "movable": m, "nonmov": n, "total": t, "rate": round(r, 4)} for c,m,n,t,r in res_occ],
    "by_household": [{"cat": c, "movable": m, "nonmov": n, "total": t, "rate": round(r, 4)} for c,m,n,t,r in res_hh],
    "by_income": [{"cat": c, "movable": m, "nonmov": n, "total": t, "rate": round(r, 4)} for c,m,n,t,r in res_inc],
    "by_housing_tenure": [{"cat": c, "movable": m, "nonmov": n, "total": t, "rate": round(r, 4)} for c,m,n,t,r in res_ten],
    "by_ethnicity": [{"cat": c, "movable": m, "nonmov": n, "total": t, "rate": round(r, 4)} for c,m,n,t,r in res_eth],
    "by_gender": [{"cat": c, "movable": m, "nonmov": n, "total": t, "rate": round(r, 4)} for c,m,n,t,r in res_gen],
    "by_protagonist": [{"cat": c, "movable": m, "nonmov": n, "total": t, "rate": round(r, 4)} for c,m,n,t,r in res_pro],
    "by_extraversion": [{"cat": c, "movable": m, "nonmov": n, "total": t, "rate": round(r, 4)} for c,m,n,t,r in res_ext],
    "by_openness": [{"cat": c, "movable": m, "nonmov": n, "total": t, "rate": round(r, 4)} for c,m,n,t,r in res_open],
    "by_neuroticism": [{"cat": c, "movable": m, "nonmov": n, "total": t, "rate": round(r, 4)} for c,m,n,t,r in res_neur],
    "by_risk_tolerance": [{"cat": c, "movable": m, "nonmov": n, "total": t, "rate": round(r, 4)} for c,m,n,t,r in res_risk],
    "by_routine_adherence": [{"cat": c, "movable": m, "nonmov": n, "total": t, "rate": round(r, 4)} for c,m,n,t,r in res_rout],
}, open(OUT_N4 / "n4_movable_profile.json", "w"), ensure_ascii=False, indent=2)

print(f"\n✓ {OUT_N4 / 'n4_movable_profile.json'}")
print("\n\nDONE")
