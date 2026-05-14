"""Audit dwell distribution acceptance criteria for typed-location runs.

Categorizes a suite seed's `space_activation` by atlas type and checks
acceptance thresholds:
- residential dwell ≥ 40% of total
- street dwell ≤ 20% of total

Exit 0 = pass; exit 2 = fail.

Usage:
    python3 tools/audit_dwell_distribution.py <suite_dir> [--atlas data/lanecove_atlas.json]

`<suite_dir>` may be either a single variant_X directory (containing
seed_*.json) or the parent suite directory (audits variant_baseline).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from synthetic_socio_wind_tunnel import Atlas


_RESIDENTIAL_FLOOR = 0.40
_STREET_CEILING = 0.20


def _find_seed_file(target_dir: Path) -> Path:
    """Find a seed_*.json file inside target_dir or a variant subdir."""
    seeds = sorted(target_dir.glob("seed_*.json"))
    if seeds:
        return seeds[0]
    baseline = target_dir / "variant_baseline"
    if baseline.is_dir():
        seeds = sorted(baseline.glob("seed_*.json"))
        if seeds:
            return seeds[0]
    raise FileNotFoundError(
        f"No seed_*.json under {target_dir} or {target_dir}/variant_baseline"
    )


def categorize(space_activation: dict[str, float], atlas: Atlas) -> dict[str, float]:
    """Sum dwell per (building_type | area_type) category."""
    by_cat: dict[str, float] = {}
    for loc_id, dwell in space_activation.items():
        building = atlas.get_building(loc_id)
        outdoor = atlas.get_outdoor_area(loc_id)
        if building is not None:
            cat = building.building_type or "unknown_building"
        elif outdoor is not None:
            cat = outdoor.area_type or "unknown_outdoor"
        else:
            cat = "unknown"
        by_cat[cat] = by_cat.get(cat, 0.0) + float(dwell)
    return by_cat


def audit(seed_file: Path, atlas: Atlas) -> tuple[bool, dict[str, float], dict[str, float]]:
    """Return (passed, dwell_by_cat, shares_by_cat)."""
    with seed_file.open(encoding="utf-8") as fh:
        seed = json.load(fh)
    sp = seed.get("run_metrics", {}).get("space_activation", {})
    if not sp:
        raise ValueError(f"empty space_activation in {seed_file}")

    by_cat = categorize(sp, atlas)
    total = sum(by_cat.values())
    if total <= 0:
        raise ValueError(f"total dwell == 0 in {seed_file}")

    shares = {cat: dwell / total for cat, dwell in by_cat.items()}
    residential_share = shares.get("residential", 0.0)
    street_share = shares.get("street", 0.0)

    passed_residential = residential_share >= _RESIDENTIAL_FLOOR
    passed_street = street_share <= _STREET_CEILING
    return passed_residential and passed_street, by_cat, shares


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite_dir", type=Path)
    parser.add_argument("--atlas", type=Path, default=Path("data/lanecove_atlas.json"))
    args = parser.parse_args()

    seed_file = _find_seed_file(args.suite_dir)
    atlas = Atlas.from_json(args.atlas)
    passed, by_cat, shares = audit(seed_file, atlas)

    print(f"audit source: {seed_file}")
    print(f"thresholds: residential >= {_RESIDENTIAL_FLOOR:.0%}, "
          f"street <= {_STREET_CEILING:.0%}")
    print()
    print("=== dwell by category ===")
    total = sum(by_cat.values())
    for cat, dwell in sorted(by_cat.items(), key=lambda x: -x[1]):
        share = dwell / total
        print(f"  {cat:18s}  {dwell:>10,.0f}  ({share:.1%})")
    print()
    res = shares.get("residential", 0.0)
    street = shares.get("street", 0.0)
    res_ok = "✓" if res >= _RESIDENTIAL_FLOOR else "✗"
    street_ok = "✓" if street <= _STREET_CEILING else "✗"
    print(f"residential_share={res:.3f} (>={_RESIDENTIAL_FLOOR:.2f} {res_ok})")
    print(f"street_share={street:.3f} (<={_STREET_CEILING:.2f} {street_ok})")
    print()
    print(f"ACCEPTANCE: {'PASS' if passed else 'FAIL'}")

    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(main())
