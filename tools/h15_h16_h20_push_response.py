"""H15 + H16 + H20 联合分析: HP push topic 响应率 / 时间衰减 / 漏斗
- H15: per push-topic response rate (which event types pull people?)
- H16: time-to-arrival distribution (when do people respond?)
- H20: delivered → consumed → arrived-at-target funnel

主参考: seed 44 + 45 HP variant (β=4 publishable)
"""
import ijson
import json
import re
from pathlib import Path
from collections import defaultdict, Counter
from statistics import median, mean

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
OUT = REPO / "data/analysis/2026-05-24_hypothesis_validation"
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "H15_topic").mkdir(exist_ok=True)
(OUT / "H16_decay").mkdir(exist_ok=True)
(OUT / "H20_funnel").mkdir(exist_ok=True)

SNAPS = {
    44: REPO / "data/experiments/20260522_165045_publishable_v7_day4to13_fork_seed44_BACKUP_20260522_213319_FULL_ALLVARIANTS/variant_hyperlocal_push/seed_44_pid12565_tick4008.snapshot.json",
    45: REPO / "data/experiments/20260522_212423_publishable_v7_day4to13_fork_seed45_BACKUP_20260523_022549_FULL_ALLVARIANTS/variant_hyperlocal_push/seed_45_pid15611_tick4020.snapshot.json",
}
POS = {
    44: REPO / "data/experiments/20260522_165045_publishable_v7_day4to13_fork_seed44_BACKUP_20260522_213319_FULL_ALLVARIANTS/variant_hyperlocal_push/seed_44_positions.json",
    45: REPO / "data/experiments/20260522_212423_publishable_v7_day4to13_fork_seed45_BACKUP_20260523_022549_FULL_ALLVARIANTS/variant_hyperlocal_push/seed_45_positions.json",
}


def extract_topic(content: str) -> str:
    """Categorise push content into a topic bucket.

    Push content format examples:
    - "shinnyo_australia 周六上午 10 点儿童活动..."
    - "plc_sydney_preschool,_lane_cove_campus 周六亲子市集开场啦..."
    - "galuwa_recreation_centre 周日下午 3 点新邻居见面会..."
    Topic = (target_location_key, event_type)
    """
    # First word(s) up to a space = location key
    m = re.match(r"^([a-z_,]+)\s", content)
    loc = m.group(1) if m else "unknown_loc"
    # Detect event type by keyword
    if "儿童活动" in content or "亲子" in content:
        event = "kids_event"
    elif "市集" in content:
        event = "market"
    elif "读书会" in content:
        event = "book_club"
    elif "清扫" in content:
        event = "cleanup"
    elif "新邻居" in content or "见面会" in content:
        event = "meetup"
    elif "运动" in content or "球" in content:
        event = "sports"
    else:
        event = "other"
    return loc, event


def load_hp_data(snap_path):
    """Extract push feed + delivery_log from HP snap."""
    print(f"  reading snap {snap_path.name} ({snap_path.stat().st_size/1e6:.0f}MB)...", flush=True)

    feed = {}  # feed_item_id -> (loc, event, content)
    with open(snap_path) as f:
        for fid, item in ijson.kvitems(f, "attention_service_state.feed_index"):
            content = item.get("content", "")
            loc, event = extract_topic(content)
            feed[fid] = (loc, event, content[:100])
    print(f"    feed_index: {len(feed)} push items", flush=True)

    # delivery_log
    delivered = []  # list of (feed_item_id, recipient_id, delivered_at, delivered_bool)
    with open(snap_path) as f:
        for entry in ijson.items(f, "attention_service_state.delivery_log.item"):
            delivered.append({
                "feed_item_id": entry.get("feed_item_id"),
                "recipient_id": entry.get("recipient_id"),
                "delivered_at": entry.get("delivered_at"),
                "delivered": entry.get("delivered"),
            })
    print(f"    delivery_log: {len(delivered)} entries", flush=True)

    # consumed_feed_item_ids per agent
    consumed_set = set()  # (agent_id, feed_item_id) pairs
    with open(snap_path) as f:
        for aid, ids in ijson.kvitems(f, "memory_store_state.consumed_feed_item_ids"):
            for fid in ids:
                consumed_set.add((aid, fid))
    print(f"    consumed pairs: {len(consumed_set)}", flush=True)

    return feed, delivered, consumed_set


def load_positions(pos_path):
    """Load per-agent timeline of location changes.

    Returns: agent_id -> list of (day, tick_in_day, location_id)
    """
    print(f"  reading positions {pos_path.name} ({pos_path.stat().st_size/1e6:.0f}MB)...", flush=True)
    d = json.load(open(pos_path))
    agent_trail = defaultdict(list)
    for ch in d["changes"]:
        agent_trail[ch["agent_id"]].append((ch["day"], ch["tick"], ch["location_id"]))
    print(f"    {len(agent_trail)} agents, {len(d['changes'])} changes", flush=True)
    return agent_trail


def parse_delivered_at(s):
    """delivered_at = '2026-04-26T00:00:00' -> (day_index, tick_in_day)
    Day 0 starts 2026-04-22. tick = 5 min/tick, 288/day.
    Returns (day_index, tick_in_day) or None if unparseable.
    """
    if not s:
        return None
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(s)
        anchor = datetime.fromisoformat("2026-04-22T00:00:00")
        delta = dt - anchor
        total_minutes = int(delta.total_seconds() / 60)
        day = total_minutes // (24 * 60)
        tick_in_day = (total_minutes % (24 * 60)) // 5
        return (day, tick_in_day)
    except Exception:
        return None


def first_arrival(agent_trail, target_loc, after_day, after_tick, max_days=14):
    """Find first time agent reaches target_loc on/after (after_day, after_tick).

    Returns (day, tick) or None if never arrived within max_days.
    """
    after_global = after_day * 288 + after_tick
    for d, t, loc in agent_trail:
        global_t = d * 288 + t
        if global_t < after_global:
            continue
        if global_t > after_global + max_days * 288:
            break
        if loc == target_loc:
            return (d, t, global_t - after_global)  # ticks elapsed
    return None


def analyse_seed(seed):
    print(f"\n=== SEED {seed} ===", flush=True)
    feed, delivered, consumed = load_hp_data(SNAPS[seed])
    agent_trail = load_positions(POS[seed])

    # Group push by topic (location)
    per_topic = defaultdict(lambda: {
        "delivered": 0,           # H20 layer 1
        "consumed": 0,            # H20 layer 2
        "arrived": 0,             # H20 layer 3
        "arrival_ticks_elapsed": [],  # H16 decay
    })

    # iterate over each delivery
    skipped_no_loc = 0
    skipped_no_trail = 0
    n_total = len(delivered)
    for i, d in enumerate(delivered):
        if i % 1000 == 0:
            print(f"    processing delivery {i}/{n_total}", flush=True)
        if not d["delivered"]:
            continue
        fid = d["feed_item_id"]
        if fid not in feed:
            continue
        loc, event, _ = feed[fid]
        if loc == "unknown_loc":
            skipped_no_loc += 1
            continue
        topic_key = (loc, event)
        per_topic[topic_key]["delivered"] += 1
        aid = d["recipient_id"]
        if (aid, fid) in consumed:
            per_topic[topic_key]["consumed"] += 1
        # arrival check
        dt_parsed = parse_delivered_at(d["delivered_at"])
        if dt_parsed is None:
            continue
        day, tick = dt_parsed
        if aid not in agent_trail:
            skipped_no_trail += 1
            continue
        arr = first_arrival(agent_trail[aid], loc, day, tick, max_days=14)
        if arr is not None:
            per_topic[topic_key]["arrived"] += 1
            per_topic[topic_key]["arrival_ticks_elapsed"].append(arr[2])

    # Compute per-topic stats
    topic_results = []
    for (loc, event), s in per_topic.items():
        if s["delivered"] < 5:
            continue
        consume_rate = s["consumed"] / s["delivered"] if s["delivered"] else 0
        arrive_rate = s["arrived"] / s["delivered"] if s["delivered"] else 0
        arrive_given_consume = s["arrived"] / s["consumed"] if s["consumed"] else 0
        arrival_ticks = s["arrival_ticks_elapsed"]
        topic_results.append({
            "location": loc,
            "event": event,
            "delivered": s["delivered"],
            "consumed": s["consumed"],
            "arrived": s["arrived"],
            "consume_rate": round(consume_rate, 4),
            "arrive_rate": round(arrive_rate, 4),
            "arrive_given_consume": round(arrive_given_consume, 4),
            "arrival_p50_ticks": median(arrival_ticks) if arrival_ticks else None,
            "arrival_p25_ticks": sorted(arrival_ticks)[len(arrival_ticks)//4] if arrival_ticks else None,
            "arrival_p75_ticks": sorted(arrival_ticks)[3*len(arrival_ticks)//4] if arrival_ticks else None,
            "arrival_max_ticks": max(arrival_ticks) if arrival_ticks else None,
        })
    topic_results.sort(key=lambda x: x["arrive_rate"], reverse=True)
    print(f"\n  topic_results: {len(topic_results)} topics with >=5 delivered (skipped {skipped_no_loc} no-loc, {skipped_no_trail} no-trail)", flush=True)

    # Aggregate decay curve (all arrivals)
    all_arrivals = []
    for s in per_topic.values():
        all_arrivals.extend(s["arrival_ticks_elapsed"])
    decay_buckets = Counter()
    for t in all_arrivals:
        # bucket: 0-1h (0-12 ticks), 1-3h, 3-6h, 6-12h, 12-24h, 24-48h, 48-96h, 96+h
        h = t * 5 / 60
        if h < 1: b = "0-1h"
        elif h < 3: b = "1-3h"
        elif h < 6: b = "3-6h"
        elif h < 12: b = "6-12h"
        elif h < 24: b = "12-24h"
        elif h < 48: b = "24-48h"
        elif h < 96: b = "48-96h"
        else: b = "96h+"
        decay_buckets[b] += 1

    # Aggregate funnel
    funnel = {
        "delivered": sum(s["delivered"] for s in per_topic.values()),
        "consumed": sum(s["consumed"] for s in per_topic.values()),
        "arrived": sum(s["arrived"] for s in per_topic.values()),
    }
    if funnel["delivered"]:
        funnel["consume_rate"] = round(funnel["consumed"] / funnel["delivered"], 4)
        funnel["arrive_rate"] = round(funnel["arrived"] / funnel["delivered"], 4)
        funnel["arrive_given_consume"] = round(funnel["arrived"] / funnel["consumed"], 4) if funnel["consumed"] else 0

    return {
        "seed": seed,
        "topic_results": topic_results,
        "decay_buckets": dict(decay_buckets),
        "funnel": funnel,
        "n_arrivals_total": len(all_arrivals),
    }


# Run both seeds
all_results = {}
for s in [44, 45]:
    all_results[s] = analyse_seed(s)

# Combine: pool both seeds
combined_funnel = {
    "delivered": sum(all_results[s]["funnel"]["delivered"] for s in [44, 45]),
    "consumed": sum(all_results[s]["funnel"]["consumed"] for s in [44, 45]),
    "arrived": sum(all_results[s]["funnel"]["arrived"] for s in [44, 45]),
}
combined_funnel["consume_rate"] = round(combined_funnel["consumed"] / combined_funnel["delivered"], 4)
combined_funnel["arrive_rate"] = round(combined_funnel["arrived"] / combined_funnel["delivered"], 4)
combined_funnel["arrive_given_consume"] = round(combined_funnel["arrived"] / combined_funnel["consumed"], 4)

combined_decay = Counter()
for s in [44, 45]:
    for b, c in all_results[s]["decay_buckets"].items():
        combined_decay[b] += c

# Combine topic — by topic key, sum across seeds
topic_pool = defaultdict(lambda: {"delivered": 0, "consumed": 0, "arrived": 0, "arrival_ticks_elapsed": []})
for s in [44, 45]:
    for r in all_results[s]["topic_results"]:
        k = (r["location"], r["event"])
        topic_pool[k]["delivered"] += r["delivered"]
        topic_pool[k]["consumed"] += r["consumed"]
        topic_pool[k]["arrived"] += r["arrived"]

combined_topic = []
for (loc, event), s in topic_pool.items():
    combined_topic.append({
        "location": loc, "event": event,
        "delivered": s["delivered"], "consumed": s["consumed"], "arrived": s["arrived"],
        "consume_rate": round(s["consumed"] / s["delivered"], 4) if s["delivered"] else 0,
        "arrive_rate": round(s["arrived"] / s["delivered"], 4) if s["delivered"] else 0,
        "arrive_given_consume": round(s["arrived"] / s["consumed"], 4) if s["consumed"] else 0,
    })
combined_topic.sort(key=lambda x: x["arrive_rate"], reverse=True)

# Write outputs
json.dump({
    "seeds": [44, 45],
    "combined_funnel": combined_funnel,
    "combined_decay": dict(sorted(combined_decay.items(), key=lambda x: ["0-1h","1-3h","3-6h","6-12h","12-24h","24-48h","48-96h","96h+"].index(x[0]))),
    "combined_topic_response": combined_topic,
    "per_seed": all_results,
}, open(OUT / "H15_H16_H20_combined.json", "w"), ensure_ascii=False, indent=2)

# Headline summary
print("\n" + "=" * 60)
print("H20 · DELIVERED → CONSUMED → ARRIVED funnel (combined seed 44+45)")
print(f"  delivered: {combined_funnel['delivered']}")
print(f"  consumed:  {combined_funnel['consumed']} ({combined_funnel['consume_rate']*100:.1f}%)")
print(f"  arrived:   {combined_funnel['arrived']} ({combined_funnel['arrive_rate']*100:.1f}% of delivered)")
print(f"             ({combined_funnel['arrive_given_consume']*100:.1f}% of those who consumed)")

print("\nH16 · TIME-TO-ARRIVAL decay buckets:")
total_arr = sum(combined_decay.values())
for b in ["0-1h","1-3h","3-6h","6-12h","12-24h","24-48h","48-96h","96h+"]:
    if b in combined_decay:
        c = combined_decay[b]
        print(f"  {b:10s} {c:6d}  ({c/total_arr*100:5.1f}%)")

print("\nH15 · TOP 10 topic response rates (combined):")
for r in combined_topic[:10]:
    print(f"  [{r['event']:12s}] {r['location'][:45]:45s} delivered={r['delivered']:4d} arrived={r['arrived']:4d} ({r['arrive_rate']*100:5.1f}%)")

print("\nBOTTOM 5 topic response rates:")
for r in combined_topic[-5:]:
    print(f"  [{r['event']:12s}] {r['location'][:45]:45s} delivered={r['delivered']:4d} arrived={r['arrived']:4d} ({r['arrive_rate']*100:5.1f}%)")

print(f"\n✓ outputs at {OUT}")
