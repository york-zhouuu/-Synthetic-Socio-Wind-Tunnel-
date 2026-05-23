"""Extract per-day unique visitor counts at Mary's and Mike's discovered POIs.

For shinnyo_australia and 1021_mediterranean:
- BL: how many distinct agents visited each day
- HP: how many distinct agents visited each day

Output: data/analysis/case_studies/poi_timeline.json
"""
import json
from collections import defaultdict
from pathlib import Path

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
OUT = REPO / "data/analysis/case_studies/poi_timeline.json"

POIS = {
    "shinnyo_australia": "Shinnyo Australia (Mary 发现)",
    "1021_mediterranean": "1021 Mediterranean (Mike 发现)",
}

POS_FILES = {
    "baseline": "data/experiments/20260521_185100_publishable_v6_day4to13_fork_seed43_BACKUP_20260522_143245/variant_baseline/seed_43_positions.json",
    "hyperlocal_push": "data/experiments/20260521_185100_publishable_v6_day4to13_fork_seed43_BACKUP_20260522_143245/variant_hyperlocal_push/seed_43_positions.json",
}

out = {poi: {"baseline": {}, "hyperlocal_push": {}} for poi in POIS}

for variant, rel in POS_FILES.items():
    print(f"Loading {variant}...")
    d = json.load(open(REPO / rel))
    # per (poi, day) → set of agents
    per_poi_day_agents = defaultdict(lambda: defaultdict(set))
    for c in d["changes"]:
        if c["location_id"] in POIS:
            per_poi_day_agents[c["location_id"]][c.get("day")].add(c["agent_id"])
    for poi in POIS:
        for day, agents in per_poi_day_agents[poi].items():
            out[poi][variant][str(day)] = len(agents)
    print(f"  {variant} done")

print("\n=== Results ===")
for poi, name in POIS.items():
    print(f"\n{name}:")
    days = sorted(set(out[poi]["baseline"]) | set(out[poi]["hyperlocal_push"]), key=int)
    for d in days:
        bl = out[poi]["baseline"].get(d, 0)
        hp = out[poi]["hyperlocal_push"].get(d, 0)
        bar = "█" * hp + "·" * max(bl, 1) if hp > 0 else "·" * bl
        print(f"  Day {d}: BL={bl:>4} · HP={hp:>4}")

json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=2)
print(f"\nWrote {OUT}")
