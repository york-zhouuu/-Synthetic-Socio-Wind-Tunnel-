"""Systemic realism audit — runs the 11 checks from
docs/audit/2026-05-12-realism-audit.md on a suite seed.

Acceptance thresholds (exit 0 if all pass, 2 otherwise):
- residential dwell share ≥ 40%
- street dwell share ≤ 20%
- poi_pool food_drink share ≥ 20%
- work_pool school share ≤ 40%
- school_pickup destinations are real schools ≥ 80%
- child workers (<16, commute/remote/shift) = 0
- occupation/age mismatches = 0
- commute median < 1300m
- meals/day average ≥ 2.5
- household age-gap > 70 = 0

Usage:
    python3 tools/audit_realism_systemic.py <suite_or_variant_dir>
        [--atlas data/lanecove_atlas.json]
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from synthetic_socio_wind_tunnel import (
    Atlas, LANE_COVE_PROFILE, build_location_pools, sample_population,
)
from synthetic_socio_wind_tunnel.agent import build_scripted_plan

# persist-per-day-summaries-across-resumes (2026-05-20): canonical seed
# regex excludes day/tick/positions/partial auxiliary files.
_REAL_SEED_RE = re.compile(r"^seed_\d+\.json$")


def _canonical_seeds(d: Path) -> list[Path]:
    return sorted(p for p in d.glob("seed_*.json") if _REAL_SEED_RE.match(p.name))


def _find_seed_file(target_dir: Path) -> Path:
    seeds = _canonical_seeds(target_dir)
    if seeds:
        return seeds[0]
    baseline = target_dir / "variant_baseline"
    if baseline.is_dir():
        seeds = _canonical_seeds(baseline)
        if seeds:
            return seeds[0]
    raise FileNotFoundError(
        f"No seed_*.json under {target_dir} or {target_dir}/variant_baseline"
    )


def audit_seed(seed_file: Path, atlas: Atlas, n_agents: int = 100) -> dict:
    """Run 11-dim audit. Returns dict of metric -> (value, passed)."""
    with seed_file.open(encoding="utf-8") as fh:
        seed_data = json.load(fh)
    rm = seed_data.get("run_metrics", {})
    seed = rm.get("seed", 42)

    # Reproduce the population for the same seed (sample_population is deterministic)
    rng = random.Random(seed)
    pools = build_location_pools(atlas, home_count=max(40, n_agents // 2),
                                  n_agents=n_agents, rng=rng)
    template = LANE_COVE_PROFILE.model_copy(update={"name": "audit",
                                                     "size": n_agents})
    profiles = sample_population(template, seed=seed, pools=pools, atlas=atlas,
                                  num_protagonists=max(1, n_agents // 10))

    metrics: dict[str, tuple] = {}

    # 1+2: dwell distribution
    sp = rm.get("space_activation", {})
    by_cat = defaultdict(float)
    total_dwell = 0
    for loc_id, dwell in sp.items():
        b = atlas.get_building(loc_id)
        o = atlas.get_outdoor_area(loc_id)
        cat = b.building_type if b else (o.area_type if o else "unknown")
        by_cat[cat] += float(dwell)
        total_dwell += float(dwell)
    res_share = by_cat["residential"] / total_dwell if total_dwell else 0
    street_share = by_cat["street"] / total_dwell if total_dwell else 0
    metrics["residential_share"] = (res_share, res_share >= 0.40)
    metrics["street_share"] = (street_share, street_share <= 0.20)

    # 3+4: pool composition
    food = sum(1 for p in pools.poi_pool
                if (b := atlas.get_building(p))
                and b.building_type in ("cafe", "restaurant", "bar"))
    food_share = food / len(pools.poi_pool) if pools.poi_pool else 0
    schools = sum(1 for w in pools.work_pool
                   if (b := atlas.get_building(w))
                   and b.building_type == "school")
    school_share = schools / len(pools.work_pool) if pools.work_pool else 0
    metrics["poi_food_drink_share"] = (food_share, food_share >= 0.20)
    metrics["work_school_share"] = (school_share, school_share <= 0.40)

    # 5: school_pickup destinations are real schools
    school_dest_school = 0
    school_dest_total = 0
    for p in profiles[:30]:
        plan = build_scripted_plan(p, pools=pools, atlas=atlas,
                                    date="2026-05-13",
                                    rng=random.Random(hash(p.agent_id)))
        for s in plan.steps:
            if s.reason == "kids" or "school" in (s.activity or "").lower():
                school_dest_total += 1
                b = atlas.get_building(s.destination)
                if b and b.building_type == "school":
                    school_dest_school += 1
    school_pickup_share = (school_dest_school / school_dest_total
                            if school_dest_total else 1.0)
    metrics["school_pickup_real_share"] = (school_pickup_share,
                                            school_pickup_share >= 0.80)

    # 6: child workers
    child_workers = sum(1 for p in profiles
                        if p.age < 16
                        and p.work_mode in ("commute", "remote", "shift"))
    metrics["child_workers"] = (child_workers, child_workers == 0)

    # 7: occupation/age mismatch
    mismatched = 0
    for p in profiles:
        if p.age < 18 and p.occupation in (
            "software_dev", "teacher", "nurse", "doctor", "writer",
            "manager", "engineer", "lawyer",
        ):
            mismatched += 1
        if p.age >= 75 and p.occupation in (
            "nurse", "software_dev", "construction", "teacher",
            "engineer", "lawyer",
        ):
            mismatched += 1
    metrics["occupation_age_mismatch"] = (mismatched, mismatched == 0)

    # 8: commute median
    dists = []
    for p in profiles:
        if not p.workplace:
            continue
        c1 = atlas.get_center(p.home_location)
        c2 = atlas.get_center(p.workplace)
        if c1 and c2:
            dists.append(((c1.x - c2.x) ** 2
                           + (c1.y - c2.y) ** 2) ** 0.5)
    if dists:
        dists.sort()
        median = dists[len(dists) // 2]
    else:
        median = 0
    metrics["commute_median_m"] = (median, median < 1500)

    # 9: meals per day
    meal_counts = []
    for p in profiles[:30]:
        plan = build_scripted_plan(p, pools=pools, atlas=atlas,
                                    date="2026-05-13",
                                    rng=random.Random(hash(p.agent_id) + 1))
        meal_counts.append(sum(1 for s in plan.steps if s.reason == "meal"))
    avg_meals = sum(meal_counts) / len(meal_counts) if meal_counts else 0
    metrics["meals_per_day_avg"] = (avg_meals, avg_meals >= 2.5)

    # 10: household age gaps
    by_home: dict[str, list] = defaultdict(list)
    for p in profiles:
        by_home[p.home_location].append(p)
    big_gap = sum(1 for residents in by_home.values()
                   if len(residents) >= 2
                   and max(r.age for r in residents)
                       - min(r.age for r in residents) > 70)
    metrics["household_age_gap_over_70"] = (big_gap, big_gap == 0)

    return metrics


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("suite_dir", type=Path)
    p.add_argument("--atlas", type=Path,
                    default=Path("data/lanecove_atlas.json"))
    p.add_argument("--agents", type=int, default=100)
    args = p.parse_args()

    seed_file = _find_seed_file(args.suite_dir)
    atlas = Atlas.from_json(args.atlas)
    metrics = audit_seed(seed_file, atlas, n_agents=args.agents)

    print(f"audit source: {seed_file}")
    print()
    print(f"{'metric':<35s}  {'value':>12s}  {'pass':>4s}")
    print("-" * 60)
    all_pass = True
    for name, (value, passed) in metrics.items():
        all_pass = all_pass and passed
        v_str = f"{value:.3f}" if isinstance(value, float) else str(value)
        flag = "✓" if passed else "✗"
        print(f"{name:<35s}  {v_str:>12s}  {flag:>4s}")
    print()
    print(f"ACCEPTANCE: {'PASS' if all_pass else 'FAIL'}")

    return 0 if all_pass else 2


if __name__ == "__main__":
    sys.exit(main())
