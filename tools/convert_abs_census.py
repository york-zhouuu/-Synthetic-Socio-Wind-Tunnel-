#!/usr/bin/env python3
"""
convert_abs_census — extract Lane Cove SA2 row from ABS 2021 GCP DataPack
and produce `data/calibration/abs_census_lanecove_2021.json`.

Reads (raw, ~34 MB DataPack folder, gitignored):
    G01  Selected Person Characteristics by Sex   → age, gender
    G09  Country of Birth by Age by Sex          → ethnicity_group
    G17  Total Personal Income (Weekly)          → income_tier
    G37  Tenure and Landlord Type                → housing_tenure
    G62  Method of Travel to Work by Sex         → work_mode

Lane Cove SA2 code: 121011686. Atlas extent slightly over-extends north into
SA2 121011399 (Chatswood West / Lane Cove North) — we use only 121011686 as
the closest single-SA2 match; document this in calibration_report.json.

Usage:
    python3 tools/convert_abs_census.py
    python3 tools/convert_abs_census.py --datapack-dir ~/Downloads/2021_GCP_SA2_for_NSW_short-header

Output:
    data/calibration/abs_census_lanecove_2021.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

LANE_COVE_SA2 = "121011686"
LANE_COVE_SA2_NAME = "Lane Cove"

# Default raw DataPack location (user's Downloads)
_DEFAULT_DATAPACK = Path.home() / "Downloads" / "2021_GCP_SA2_for_NSW_short-header" / "2021 Census GCP Statistical Area 2 for NSW"
_OUT_PATH = Path(__file__).resolve().parents[1] / "data" / "calibration" / "abs_census_lanecove_2021.json"


def _read_sa2_row(csv_path: Path, sa2_code: str) -> dict[str, int]:
    """Read one SA2 row from a Census CSV. Returns dict[col_name -> int]."""
    if not csv_path.exists():
        raise FileNotFoundError(f"Census CSV not found: {csv_path}")
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("SA2_CODE_2021") == sa2_code:
                # All values are ints (counts)
                return {k: int(v) for k, v in row.items() if k != "SA2_CODE_2021"}
    raise ValueError(f"SA2 {sa2_code} not found in {csv_path.name}")


def _normalize(d: dict[str, float]) -> dict[str, float]:
    """Make values sum to 1.0; tolerate tiny float drift."""
    total = sum(d.values())
    if total <= 0:
        return d
    return {k: v / total for k, v in d.items()}


# ---------------------------------------------------------------------------
# Per-dimension extractors
# ---------------------------------------------------------------------------

def _age_distribution(g01: dict[str, int]) -> dict[str, float]:
    """G01 ABS buckets: 0-4, 5-14, 15-19, 20-24, 25-34, 35-44, 45-54, 55-64, 65-74, 75-84, 85+."""
    buckets = {
        "0-4": g01["Age_0_4_yr_P"],
        "5-14": g01["Age_5_14_yr_P"],
        "15-19": g01["Age_15_19_yr_P"],
        "20-24": g01["Age_20_24_yr_P"],
        "25-34": g01["Age_25_34_yr_P"],
        "35-44": g01["Age_35_44_yr_P"],
        "45-54": g01["Age_45_54_yr_P"],
        "55-64": g01["Age_55_64_yr_P"],
        "65-74": g01["Age_65_74_yr_P"],
        "75-84": g01["Age_75_84_yr_P"],
        "85+": g01["Age_85ov_P"],
    }
    return _normalize(buckets)


def _gender_distribution(g01: dict[str, int]) -> dict[str, float]:
    """ABS Census 2021 only records male/female; non_binary defaults to 0."""
    male = g01["Tot_P_M"]
    female = g01["Tot_P_F"]
    total = male + female
    return {
        "male": male / total if total else 0.487,
        "female": female / total if total else 0.513,
        "non_binary": 0.0,
    }


def _housing_tenure_distribution(g37: dict[str, int]) -> dict[str, float]:
    """
    G37 categories → our 3-bucket schema:
      O_OR_Total          (owned outright)            → owner_occupier
      O_MTG_Total         (owned with mortgage)       → owner_occupier
      R_RE_Agt_Total      (rented, real-estate agent) → renter
      R_ST_h_auth_Total   (rented, state housing)     → public_housing
      R_Com_Hp_*_NS       (community housing)         → public_housing
      R_Per_Tot           (rented, person)            → renter
      Other_landlord types lumped to renter
    """
    # Find owner-occupier columns
    owner = g37.get("O_OR_Total", 0) + g37.get("O_MTG_Total", 0)

    # Public/community housing (state housing authority + community housing)
    public = g37.get("R_ST_h_auth_Total", 0)
    # Community housing provider (R_Com_Hp_*) — sum if present
    community = sum(
        v for k, v in g37.items()
        if k.startswith("R_Com_Hp_") and k.endswith("_Total")
    )
    public += community

    # All other rentals
    total_rented = sum(
        v for k, v in g37.items()
        if k.startswith("R_") and k.endswith("_Total")
    )
    renter = total_rented - public

    raw = {"owner_occupier": owner, "renter": max(0, renter), "public_housing": public}
    return _normalize(raw)


def _income_tier_distribution(g17: dict[str, int]) -> dict[str, float]:
    """
    G17 has 13 income brackets × 9 age groups × 3 sex = a lot of cols.
    We use the per-bracket Tot column (P_<bracket>_Tot) and group into 3 tiers.

    Lane Cove medians (2021): personal weekly $1,033 (per QuickStats LGA) →
    we split by Sydney-wide convention:
      low     = $1 - $799        (low-income brackets)
      mid     = $800 - $1,749    (middle)
      high    = $1,750+          (top quartile)

    Brackets defined in G17 (P_*_Tot):
      Neg_Nil_income, 1_149, 150_299, 300_399, 400_499, 500_649, 650_799,
      800_999, 1000_1249, 1250_1499, 1500_1749, 1750_1999, 2000_2999,
      3000_3499, 3500_more, Not_stated
    """
    low_keys = ["P_Neg_Nil_income_Tot", "P_1_149_Tot", "P_150_299_Tot",
                "P_300_399_Tot", "P_400_499_Tot", "P_500_649_Tot", "P_650_799_Tot"]
    mid_keys = ["P_800_999_Tot", "P_1000_1249_Tot", "P_1250_1499_Tot",
                "P_1500_1749_Tot"]
    high_keys = ["P_1750_1999_Tot", "P_2000_2999_Tot", "P_3000_3499_Tot",
                 "P_3500_more_Tot"]

    low = sum(g17.get(k, 0) for k in low_keys)
    mid = sum(g17.get(k, 0) for k in mid_keys)
    high = sum(g17.get(k, 0) for k in high_keys)

    raw = {"low": low, "mid": mid, "high": high}
    return _normalize(raw)


_TOP_BIRTHPLACES = (
    "Australia", "England", "China", "India", "New_Zealand",
    "Philippines", "Vietnam", "South_Africa", "Hong_Kong_SAR_Ch", "USA",
)


def _ethnicity_distribution(g09: dict[str, int]) -> dict[str, float]:
    """
    Country of birth as proxy for ethnicity_group.
    Top countries kept; tail collapsed to 'other'.

    G09 schema in 2021 GCP: per-country counts split by sex (M_<country>_Tot,
    F_<country>_Tot) — there is no pre-summed P_<country>_Tot. We sum M+F.
    Grand total: M_Tot_Tot + F_Tot_Tot.
    """
    out: dict[str, int] = {}
    top_total = 0
    for country in _TOP_BIRTHPLACES:
        m = g09.get(f"M_{country}_Tot", 0)
        f = g09.get(f"F_{country}_Tot", 0)
        out[country] = m + f
        top_total += m + f

    grand = g09.get("M_Tot_Tot", 0) + g09.get("F_Tot_Tot", 0)
    out["other"] = max(0, grand - top_total)

    return _normalize({k: float(v) for k, v in out.items()})


def _work_mode_distribution(g62: dict[str, int]) -> dict[str, float]:
    """
    G62: Method of Travel to Work by Sex.

    Map to our schema:
      commute    = sum of all transit/car/bike/walk methods (incl. multi-method)
      remote     = Worked_home_P
      shift      = (not directly in G62; defaults to a small share of commute,
                    re-tagged based on G46 if available — leave 0 here, mark
                    as caveat)
      nonworking = Did_not_go_to_work_P + Method_travel_to_work_ns_P

    Note: G62 only counts employed persons aged 15+; nonworking from G62 is
    "employed but did not work that week" — distinct from "not in labour force".
    For population calibration purposes this is the closest proxy; future
    iteration could blend G46 LFS data for true nonworking share.
    """
    # All sub-categories starting with One_method/Two_methods/Three_meth, _P col
    commute = 0
    for k, v in g62.items():
        if not k.endswith("_P"):
            continue
        if k.startswith("One_method") and "Tot_one_method" not in k:
            commute += v
        elif k.startswith("Two_methods") and "Tot_two_methods" not in k:
            commute += v
        elif k.startswith("Three_meth") and "Tot_three_meth" not in k:
            commute += v

    remote = g62.get("Worked_home_P", 0)
    nonworking = g62.get("Did_not_go_to_work_P", 0) + g62.get("Method_travel_to_work_ns_P", 0)

    # G62 doesn't separate shift work; left at 0 with caveat in JSON metadata
    raw = {
        "commute": commute,
        "remote": remote,
        "shift": 0,
        "nonworking": nonworking,
    }
    return _normalize({k: float(v) for k, v in raw.items()})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _read_split_table(datapack_dir: Path, prefix: str, sa2_code: str) -> dict[str, int]:
    """
    Read all split CSVs (e.g. G09A, G09B, ..., G09H) and merge their SA2 row.
    Some tables split by suffix letter; we glob all matching files.
    """
    merged: dict[str, int] = {}
    for path in sorted(datapack_dir.glob(f"2021Census_{prefix}*_NSW_SA2.csv")):
        merged.update(_read_sa2_row(path, sa2_code))
    if not merged:
        raise FileNotFoundError(
            f"no {prefix}* CSV found under {datapack_dir}"
        )
    return merged


def convert(datapack_dir: Path, sa2_code: str = LANE_COVE_SA2) -> dict:
    g01 = _read_sa2_row(datapack_dir / "2021Census_G01_NSW_SA2.csv", sa2_code)
    g37 = _read_sa2_row(datapack_dir / "2021Census_G37_NSW_SA2.csv", sa2_code)
    g62 = _read_sa2_row(datapack_dir / "2021Census_G62_NSW_SA2.csv", sa2_code)
    g09 = _read_split_table(datapack_dir, "G09", sa2_code)
    g17 = _read_split_table(datapack_dir, "G17", sa2_code)

    return {
        "source": (
            "ABS Census 2021 General Community Profile (GCP) DataPack — "
            f"SA2 {sa2_code} {LANE_COVE_SA2_NAME}"
        ),
        "downloaded": str(date.today()),
        "url": (
            "https://www.abs.gov.au/census/find-census-data/datapacks "
            "(General Community Profile, SA2, NSW)"
        ),
        "sa2_code": sa2_code,
        "sa2_name": LANE_COVE_SA2_NAME,
        "tables_used": {
            "G01": "Selected Person Characteristics by Sex (age + gender)",
            "G09": "Country of Birth by Age by Sex (ethnicity proxy)",
            "G17": "Total Personal Income Weekly by Age by Sex",
            "G37": "Tenure and Landlord Type by Dwelling Structure",
            "G62": "Method of Travel to Work by Sex (work mode proxy)",
        },
        "geographic_caveat": (
            "Atlas extent slightly over-extends north into SA2 121011399 "
            "(Chatswood West / Lane Cove North). Calibration uses single-SA2 "
            "121011686 only; future iteration could blend two SA2s by area share."
        ),
        "schema_caveat": (
            "shift work mode is 0 in G62-derived distribution (G62 doesn't "
            "separate shift); future iteration can blend G46 LFS data."
        ),
        "total_population": g01["Tot_P_P"],
        "distributions": {
            "age": _age_distribution(g01),
            "gender": _gender_distribution(g01),
            "housing_tenure": _housing_tenure_distribution(g37),
            "income_tier": _income_tier_distribution(g17),
            "ethnicity_group": _ethnicity_distribution(g09),
            "work_mode": _work_mode_distribution(g62),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--datapack-dir",
        type=Path,
        default=_DEFAULT_DATAPACK,
        help=f"Path to GCP DataPack folder (default: {_DEFAULT_DATAPACK})",
    )
    ap.add_argument("--sa2-code", default=LANE_COVE_SA2)
    ap.add_argument("--output", type=Path, default=_OUT_PATH)
    args = ap.parse_args()

    if not args.datapack_dir.exists():
        sys.stderr.write(
            f"error: DataPack folder not found: {args.datapack_dir}\n"
            "  Download from https://www.abs.gov.au/census/find-census-data/datapacks\n"
            "  Choose: General Community Profile, SA2, NSW.\n"
        )
        return 2

    payload = convert(args.datapack_dir, sa2_code=args.sa2_code)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    print(f"[done] SA2 {args.sa2_code} ({payload['sa2_name']}, "
          f"{payload['total_population']} people) → {args.output}")
    print()
    print("=== distributions ===")
    for dim, dist in payload["distributions"].items():
        top = sorted(dist.items(), key=lambda kv: -kv[1])[:3]
        print(f"  {dim:18} top-3: " + ", ".join(f"{k}={v:.3f}" for k, v in top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
