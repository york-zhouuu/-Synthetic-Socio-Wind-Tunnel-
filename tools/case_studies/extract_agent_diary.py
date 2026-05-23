"""Extract per-day stays + replan moments from positions.json for case study agents.

For each day, output structured data:
- stays: list of (arrived_tick, arrived_time, location_id, location_name, location_type,
                  duration_ticks, duration_minutes, x, y)
- replans: each transition between stays
- distance_walked_m: sum of segment lengths
- new_locations: HP-only locations visited that day

Output: data/analysis/case_studies/{agent_id}_diary.json
"""
import json
import math
from collections import defaultdict
from pathlib import Path

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
ATLAS_PATH = REPO / "data/lanecove_atlas.json"
POP_CACHE = REPO / "data/population_cache/v1"
OUT_DIR = REPO / "data/analysis/case_studies"
OUT_DIR.mkdir(parents=True, exist_ok=True)

POS_FILES = {
    43: {
        "baseline": "data/experiments/20260521_185100_publishable_v6_day4to13_fork_seed43_BACKUP_20260522_143245/variant_baseline/seed_43_positions.json",
        "hyperlocal_push": "data/experiments/20260521_185100_publishable_v6_day4to13_fork_seed43_BACKUP_20260522_143245/variant_hyperlocal_push/seed_43_positions.json",
    },
}

# Tick = 5 minutes (288 ticks/day)
TICKS_PER_DAY = 288
MIN_STAY_TICKS = 4  # 20 minutes = a meaningful stay

HEROES = [
    {"aid": "a_43_0405", "seed": 43, "label": "mary"},
    {"aid": "a_43_0192", "seed": 43, "label": "mike"},
    {"aid": "a_43_0012", "seed": 43, "label": "agent_12"},  # 64yo construction worker, Mary's neighbor at Shinnyo
]


def centroid_xy(verts):
    if not verts: return None
    xs = [v["x"] for v in verts] if isinstance(verts[0], dict) else [v[0] for v in verts]
    ys = [v["y"] for v in verts] if isinstance(verts[0], dict) else [v[1] for v in verts]
    return sum(xs)/len(xs), sum(ys)/len(ys)


print("Loading atlas...")
atlas = json.load(open(ATLAS_PATH))
LOC2META = {}
for bid, b in atlas["buildings"].items():
    verts = b.get("polygon", {}).get("vertices", [])
    if verts:
        c = centroid_xy(verts)
        if c:
            LOC2META[bid] = {
                "name": b.get("name") or "",
                "type": b.get("building_type") or "",
                "x": c[0], "y": c[1],
                "kind": "building",
                "description": b.get("description") or "",
            }
outdoor = atlas.get("outdoor_areas", {})
outdoor_iter = outdoor.items() if isinstance(outdoor, dict) else [(o["id"], o) for o in outdoor]
for oid, o in outdoor_iter:
    verts = o.get("polygon", {}).get("vertices", [])
    if verts:
        c = centroid_xy(verts)
        if c:
            LOC2META[oid] = {
                "name": o.get("name") or "",
                "type": o.get("area_type") or "",
                "x": c[0], "y": c[1],
                "kind": "outdoor",
                "description": o.get("description") or "",
            }


# Load profile cache
print("Loading profiles...")
profiles = {}
import os
for f in os.listdir(POP_CACHE):
    d = json.load(open(POP_CACHE / f))
    for p in d.get("profiles", []):
        aid = p.get("agent_id")
        if aid:
            profiles[aid] = p


def tick_to_hhmm(tick_in_day):
    """Tick 0 = 00:00, tick = 5 min."""
    minutes = tick_in_day * 5
    h = (minutes // 60) % 24
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


def detect_stays(chronological, day):
    """For a day's chronological position changes, detect stays
    (location visited >= MIN_STAY_TICKS consecutive ticks).

    Stay duration capped at TICKS_PER_DAY (288 = 24h) — anything longer is
    implausible and almost always a artifact of the day-boundary calculation.
    """
    if not chronological:
        return []
    stays = []
    day_changes = [c for c in chronological if c.get("day") == day]
    if not day_changes:
        return []
    MAX_STAY_TICKS = TICKS_PER_DAY  # cap any single stay at 24 hours

    cur_loc = None
    cur_start = None
    for c in day_changes:
        if cur_loc is None:
            cur_loc = c["location_id"]
            cur_start = c["tick"]
            continue
        if c["location_id"] != cur_loc:
            duration = min(c["tick"] - cur_start, MAX_STAY_TICKS)
            if duration >= MIN_STAY_TICKS:
                meta = LOC2META.get(cur_loc, {})
                stays.append({
                    "loc": cur_loc,
                    "name": meta.get("name") or cur_loc,
                    "type": meta.get("type") or "?",
                    "kind": meta.get("kind") or "?",
                    "arrived_tick": cur_start,
                    "arrived_time": tick_to_hhmm(cur_start % TICKS_PER_DAY),
                    "duration_ticks": duration,
                    "duration_min": duration * 5,
                    "x": meta.get("x"), "y": meta.get("y"),
                })
            cur_loc = c["location_id"]
            cur_start = c["tick"]
    # Last stay: positions.json only logs CHANGES; agent may have moved later
    # without further logging. Cap at DEFAULT_LAST_STAY_TICKS = 24 (2h) which
    # matches typical activity duration (cafe / class / fitness session).
    DEFAULT_LAST_STAY_TICKS = 24  # 2 hours = realistic visit length
    if cur_loc:
        meta = LOC2META.get(cur_loc, {})
        duration = DEFAULT_LAST_STAY_TICKS
        if duration >= MIN_STAY_TICKS:
            stays.append({
                "loc": cur_loc,
                "name": meta.get("name") or cur_loc,
                "type": meta.get("type") or "?",
                "kind": meta.get("kind") or "?",
                "arrived_tick": cur_start,
                "arrived_time": tick_to_hhmm(cur_start % TICKS_PER_DAY),
                "duration_ticks": duration,
                "duration_min": duration * 5,
                "x": meta.get("x"), "y": meta.get("y"),
            })
    return stays


def compute_day_distance(chronological, day):
    """Sum segment lengths between consecutive locations on a day."""
    day_changes = [c for c in chronological if c.get("day") == day]
    total = 0.0
    prev_xy = None
    for c in day_changes:
        meta = LOC2META.get(c["location_id"])
        if meta is None: continue
        if prev_xy is not None:
            dx = meta["x"] - prev_xy[0]; dy = meta["y"] - prev_xy[1]
            d = math.sqrt(dx*dx + dy*dy)
            if d < 200:  # ignore teleports
                total += d
        prev_xy = (meta["x"], meta["y"])
    return total


def extract_chrono(pos_path, target_aid):
    d = json.load(open(pos_path))
    seq = []
    for c in d["changes"]:
        if c["agent_id"] == target_aid:
            seq.append({"tick": c["tick"], "day": c.get("day"),
                        "location_id": c["location_id"]})
    seq.sort(key=lambda c: c["tick"])
    return seq


for hero in HEROES:
    aid = hero["aid"]; seed = hero["seed"]; label = hero["label"]
    print(f"\n=== Processing {label} ({aid}) ===")
    bl = extract_chrono(REPO / POS_FILES[seed]["baseline"], aid)
    hp = extract_chrono(REPO / POS_FILES[seed]["hyperlocal_push"], aid)
    print(f"  BL events: {len(bl)}, HP events: {len(hp)}")

    diary = {
        "agent_id": aid,
        "label": label,
        "profile": profiles.get(aid, {}),
        "days": []
    }

    # Per-day breakdown
    all_days = sorted(set(c["day"] for c in bl + hp if c.get("day") is not None))
    bl_locs_total = set()
    hp_locs_total = set()
    for c in bl: bl_locs_total.add(c["location_id"])
    for c in hp: hp_locs_total.add(c["location_id"])

    for day in all_days:
        bl_stays = detect_stays(bl, day)
        hp_stays = detect_stays(hp, day)
        bl_locs_day = {s["loc"] for s in bl_stays}
        hp_locs_day = {s["loc"] for s in hp_stays}
        new_today = hp_locs_day - bl_locs_total  # locations Mary went to in HP that don't appear ANYWHERE in BL

        diary["days"].append({
            "day": day,
            "bl_stays": bl_stays,
            "hp_stays": hp_stays,
            "n_bl_stays": len(bl_stays),
            "n_hp_stays": len(hp_stays),
            "bl_distance_m": round(compute_day_distance(bl, day), 1),
            "hp_distance_m": round(compute_day_distance(hp, day), 1),
            "new_locations_today": [{"loc": l, "name": LOC2META.get(l, {}).get("name", l),
                                     "type": LOC2META.get(l, {}).get("type", "?")}
                                    for l in new_today
                                    if LOC2META.get(l, {}).get("name")],
        })

    out_path = OUT_DIR / f"{label}_diary.json"
    json.dump(diary, open(out_path, "w"), ensure_ascii=False, indent=2)
    print(f"  Written: {out_path} ({out_path.stat().st_size / 1e3:.0f} KB)")

    # Print summary
    print(f"\n  {label} 14-day diary summary:")
    for d in diary["days"]:
        new_named = [n["name"] for n in d["new_locations_today"] if n["name"] and not n["name"].startswith("road_")]
        marker = " ★" if new_named else ""
        print(f"    Day {d['day']}: BL {d['n_bl_stays']} stays ({d['bl_distance_m']:.0f}m) · "
              f"HP {d['n_hp_stays']} stays ({d['hp_distance_m']:.0f}m)" +
              (f"  ★ NEW: {', '.join(new_named[:3])}" if new_named else ""))
