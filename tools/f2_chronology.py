"""F2 · Chronology · the 24-hour clock of nearby blindness.

Walks BL snapshots and bins every encounter event by hour-of-day (parsed
from simulated_time). Produces:
  - per-hour notice rate (24 buckets)
  - per-hour breakdown by building_type (street vs residential etc) — does
    the street's blindness deepen at rush hour, or is it always low?
  - tick=0 / midnight events flagged separately (potential init artefacts)

Constraint: snapshot in-memory events cover only the most recent ~2 days
(MEMORY_EVENT_EVICT_GRACE_DAYS=2), which happen to be Mon+Tue (2026-05-04,
05-05). So this is a TWO-WEEKDAY hourly profile, not a weekly one.
"""
import ijson
import json
import os
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime
from statistics import mean

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
OUT = REPO / "data/analysis/2026-05-24_hypothesis_validation/F2_chronology"
OUT.mkdir(parents=True, exist_ok=True)
ATLAS = REPO / "data/lanecove_atlas.json"

SEED_DIRS = {
    44: REPO / "data/experiments/20260522_165045_publishable_v7_day4to13_fork_seed44_BACKUP_20260522_213319_FULL_ALLVARIANTS",
    45: REPO / "data/experiments/20260522_212423_publishable_v7_day4to13_fork_seed45_BACKUP_20260523_022549_FULL_ALLVARIANTS",
}


def get_snap_path(seed, variant):
    d = SEED_DIRS[seed] / f"variant_{variant}"
    return next(d.glob(f"seed_{seed}_pid*_tick*.snapshot.json"))


# Load atlas building_type
print("Loading atlas...", flush=True)
atlas = json.load(open(ATLAS))
loc_type = {}
for bid, b in atlas["buildings"].items():
    loc_type[bid] = (b.get("building_type") or "").lower()
out = atlas.get("outdoor_areas", {})
items = out.items() if isinstance(out, dict) else [(o["id"], o) for o in out]
for oid, o in items:
    loc_type[oid] = (o.get("area_type") or "outdoor").lower()


def analyze(seed):
    snap = get_snap_path(seed, "baseline")
    print(f"\n=== SEED {seed} BL · {snap.name} ({snap.stat().st_size/1e6:.0f}MB) ===",
          flush=True)

    # Per-hour-of-day counters
    per_hour = defaultdict(lambda: {"enc": 0, "noticed": 0})
    # Per-(hour, building_type) counters
    per_hour_type = defaultdict(lambda: {"enc": 0, "noticed": 0})
    # Per-day-index counters (for sanity)
    per_day = defaultdict(lambda: {"enc": 0, "noticed": 0})
    # Track flag values
    n_total = 0
    n_no_time = 0
    n_midnight = 0
    sim_time_dates = Counter()

    with open(snap) as f:
        ai = 0
        for aid, events in ijson.kvitems(f, "memory_store_state.agent_events"):
            ai += 1
            if ai % 200 == 0:
                print(f"  {ai}/1000", flush=True)
            for ev in events:
                if ev.get("kind") != "encounter":
                    continue
                st = ev.get("simulated_time")
                if not st:
                    n_no_time += 1
                    continue
                try:
                    dt = datetime.fromisoformat(st)
                except ValueError:
                    n_no_time += 1
                    continue
                hour = dt.hour
                minute = dt.minute
                day_key = dt.strftime("%Y-%m-%d")
                sim_time_dates[day_key] += 1
                # Skip exactly-midnight events (likely init artefact, tick=0)
                if hour == 0 and minute == 0:
                    n_midnight += 1
                    continue

                is_noticed = "noticed" in (ev.get("tags") or [])
                loc = ev.get("location_id") or ""
                btype = loc_type.get(loc, "unknown")

                per_hour[hour]["enc"] += 1
                per_hour_type[(hour, btype)]["enc"] += 1
                per_day[day_key]["enc"] += 1
                if is_noticed:
                    per_hour[hour]["noticed"] += 1
                    per_hour_type[(hour, btype)]["noticed"] += 1
                    per_day[day_key]["noticed"] += 1
                n_total += 1

    print(f"  encounters: {n_total:,}  | no-time: {n_no_time}  | midnight-skipped: {n_midnight}",
          flush=True)
    print(f"  day coverage: {dict(sim_time_dates)}", flush=True)
    return per_hour, per_hour_type, per_day


# Pool across seeds
pooled_hour = defaultdict(lambda: {"enc": 0, "noticed": 0})
pooled_hour_type = defaultdict(lambda: {"enc": 0, "noticed": 0})
pooled_day = defaultdict(lambda: {"enc": 0, "noticed": 0})
for s in [44, 45]:
    h, ht, d = analyze(s)
    for k, v in h.items():
        pooled_hour[k]["enc"] += v["enc"]
        pooled_hour[k]["noticed"] += v["noticed"]
    for k, v in ht.items():
        pooled_hour_type[k]["enc"] += v["enc"]
        pooled_hour_type[k]["noticed"] += v["noticed"]
    for k, v in d.items():
        pooled_day[k]["enc"] += v["enc"]
        pooled_day[k]["noticed"] += v["noticed"]


def rate(c):
    return c["noticed"] / c["enc"] if c["enc"] else 0.0


# Print 24h table
print("\n" + "=" * 70)
print(f"{'HOUR':>6s} {'enc':>10s} {'noticed':>10s} {'rate':>8s}")
hourly_rows = []
for h in range(24):
    c = pooled_hour[h]
    r = rate(c)
    bar = "█" * int(r * 200)
    print(f"  {h:>02d}h  {c['enc']:>10,d} {c['noticed']:>10,d}  {r*100:>5.2f}%  {bar}")
    hourly_rows.append({"hour": h, "enc": c["enc"],
                         "noticed": c["noticed"], "rate": round(r, 4)})

# By day
print("\nDay-of-data sanity:")
for d, c in sorted(pooled_day.items()):
    r = rate(c)
    print(f"  {d}: enc={c['enc']:,d} noticed={c['noticed']:,d} rate={r*100:.2f}%")

# Top building types
print("\nHour × Building-type matrix (top 4 types only)")
TOP_TYPES = ["street", "residential", "commercial", "office"]
matrix = {}
for t in TOP_TYPES:
    row = []
    for h in range(24):
        c = pooled_hour_type[(h, t)]
        row.append({"hour": h, "type": t, "enc": c["enc"],
                    "noticed": c["noticed"], "rate": round(rate(c), 4)})
    matrix[t] = row
    print(f"\n  TYPE = {t}")
    for cell in row:
        bar = "█" * int(cell["rate"] * 200)
        print(f"    {cell['hour']:>02d}h enc={cell['enc']:>6,d} noticed={cell['noticed']:>5,d} rate={cell['rate']*100:>5.2f}% {bar}")

# Summary stats: deepest/highest hours
sorted_h = sorted(hourly_rows, key=lambda x: x["rate"])
print(f"\nDeepest 3 hours (lowest notice rate):")
for x in sorted_h[:3]:
    print(f"  {x['hour']:>02d}h  rate={x['rate']*100:.2f}%  enc={x['enc']:,d}")
print(f"\nBrightest 3 hours (highest notice rate):")
for x in sorted_h[-3:]:
    print(f"  {x['hour']:>02d}h  rate={x['rate']*100:.2f}%  enc={x['enc']:,d}")

# Save
out_data = {
    "method": "BL pooled seed 44+45, in-memory snapshot events, hour-of-day bins from simulated_time.hour. Midnight (00:00) events excluded as likely init artefact. Coverage: 2 weekdays (Mon 2026-05-04 + Tue 2026-05-05). Population mean notice rate ~9.5% across 14 days.",
    "hourly": hourly_rows,
    "hourly_by_building_type": matrix,
    "deepest_3_hours": sorted_h[:3],
    "brightest_3_hours": sorted_h[-3:],
    "day_coverage": {d: {"enc": c["enc"], "noticed": c["noticed"],
                         "rate": round(rate(c), 4)}
                     for d, c in sorted(pooled_day.items())},
}
out_path = OUT / "f2_chronology_baseline.json"
json.dump(out_data, open(out_path, "w"), ensure_ascii=False, indent=2)
print(f"\n✓ {out_path}")
