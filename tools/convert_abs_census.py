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
    """Read one SA2 row from a Census CSV. Returns dict[col_name -> int].
    ABS uses ".." for null / suppressed cells; treat as 0.
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"Census CSV not found: {csv_path}")
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("SA2_CODE_2021") == sa2_code:
                out: dict[str, int] = {}
                for k, v in row.items():
                    if k == "SA2_CODE_2021":
                        continue
                    if not v or v == "..":
                        out[k] = 0
                    else:
                        try:
                            out[k] = int(v)
                        except ValueError:
                            out[k] = 0
                return out
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
# Tier 1 — thesis core extractors (agent-profile-enrich)
# ---------------------------------------------------------------------------

def _community_tenure_distribution(g45: dict[str, int]) -> dict[str, float]:
    """
    G45: Place of Usual Residence 5 Years Ago.
    Buckets: same address = established 5+; same SA2/NSW/elsewhere = recent
    1-5 (we approximate; G45 doesn't directly distinguish <1yr); overseas
    arrivals included.
    Our schema:
      established_5plus = same address 5 years ago
      recent_1_5yr      = different address but same/different SA2/state, plus overseas arrivals
      new_<1yr          = ~1/5 of "recent" as approximation (G45 is 5-year, not 1-year)
    """
    same = g45.get("Sme_Usl_ad_5_yr_ago_as_2021_P", 0)
    # Sum all "Different address" P columns
    different = sum(
        v for k, v in g45.items()
        if k.endswith("_P") and k.startswith("Dif_") and "Tot" not in k
    )
    overseas = g45.get("Ov_5_yrs_ago_P", 0) + g45.get("Overseas_5_yrs_ago_P", 0)
    not_stated = g45.get("Pl_o_us_rsdnce_5_yrs_ago_NS_P", 0) + g45.get("Place_o_usl_resd_5_yrs_ago_NS_P", 0)

    moved_total = different + overseas
    # Approximate split: 1/5 of movers in last year (uniform assumption)
    new_1yr = moved_total / 5
    recent_1_5 = moved_total - new_1yr

    raw = {
        "established_5plus": same,
        "recent_1_5yr": recent_1_5,
        "new_<1yr": new_1yr,
    }
    return _normalize({k: float(v) for k, v in raw.items()})


def _care_hours_from_age_buckets(table: dict[str, int], hour_keys: list[str], total_keys: list[str]) -> dict[str, float]:
    """
    Helper for G24/G26 which split unpaid hours by age bucket.
    `hour_keys` = list of hour-bucket suffix patterns, e.g. ["LT_5_h", "5_14_h", "15_29_h", "30_h_mo"]
    Returns 4-bucket distribution: none / 1_14 / 15_29 / 30plus.
    """
    counts = {key: 0 for key in hour_keys + ["DN", "ns"]}
    for col, val in table.items():
        if not col.startswith(("M_", "F_")):
            continue
        for key in hour_keys:
            if col.endswith(f"_{key}"):
                counts[key] += val
    # G24: M_15_19y_DNUDW (did not undertake unpaid domestic work)
    # G26: M_15_19_DNPCC (did not provide child care)
    for col, val in table.items():
        if col.startswith(("M_", "F_")) and ("DNUDW" in col or "DNPCC" in col):
            counts["DN"] += val
    return counts


def _unpaid_domestic_distribution(g24: dict[str, int]) -> dict[str, float]:
    """G24: Unpaid Domestic Work hours per week."""
    # Hour bucket suffixes vary slightly across A/B halves
    none = 0
    h_1_14 = 0
    h_15_29 = 0
    h_30plus = 0
    for col, val in g24.items():
        if not col.startswith(("M_", "F_")):
            continue
        if "DNUDW" in col:
            none += val
        elif col.endswith("_DUDW_LT_5_h"):
            h_1_14 += val  # <5h falls in 1-14 bucket
        elif col.endswith("_DUDW_5_14_h"):
            h_1_14 += val
        elif col.endswith("_DUDW_15_29_h"):
            h_15_29 += val
        elif col.endswith("_DUDW_30_h_mo"):
            h_30plus += val
    raw = {"none": none, "1_14": h_1_14, "15_29": h_15_29, "30plus": h_30plus}
    return _normalize({k: float(v) for k, v in raw.items()})


def _unpaid_child_care_distribution(g26: dict[str, int]) -> dict[str, float]:
    """
    G26: Unpaid Child Care.
    G26 doesn't break by hours; only "cared / didn't care / cared own + others".
    We map: any care = 15_29 (mid-bucket assumption); no care = none.
    Bucket "1_14" / "30plus" are 0 (G26 lacks granularity).
    """
    cared = 0
    not_cared = 0
    for col, val in g26.items():
        if not col.startswith(("M_", "F_")):
            continue
        if col.endswith("_DNPCC"):
            not_cared += val
        elif "_CF_" in col and ("CCO" in col or "CC_Oth" in col):
            cared += val
    raw = {"none": not_cared, "1_14": 0, "15_29": cared, "30plus": 0}
    return _normalize({k: float(v) for k, v in raw.items()})


def _unpaid_disability_care_distribution(g25: dict[str, int]) -> dict[str, float]:
    """G25: Provided unpaid assistance to person with disability."""
    yes = 0
    no = 0
    for col, val in g25.items():
        if not col.startswith(("M_", "F_")):
            continue
        if "Prvided_unpaid_assist" in col and "No_unpad_asst_prvided" not in col:
            yes += val
        elif "No_unpad_asst_prvided" in col:
            no += val
    raw = {"none": no, "yes": yes}
    return _normalize({k: float(v) for k, v in raw.items()})


def _volunteer_distribution(g23: dict[str, int]) -> dict[str, float]:
    """G23: Voluntary Work for an Organisation or Group."""
    vol = 0
    not_vol = 0
    for col, val in g23.items():
        if not col.startswith(("M_", "F_")):
            continue
        if col.endswith("_Volunteer"):
            vol += val
        elif col.endswith("_N_a_volunteer"):
            not_vol += val
    raw = {"volunteer": vol, "non_volunteer": not_vol}
    return _normalize({k: float(v) for k, v in raw.items()})


# ---------------------------------------------------------------------------
# Tier 2 — refinement extractors
# ---------------------------------------------------------------------------

def _english_proficiency_distribution(g13: dict[str, int]) -> dict[str, float]:
    """
    G13: Language Used at Home by Proficiency in Spoken English.

    ABS combines very_well/well into one bucket "VWorW" and
    not_well/not_at_all into "NWorNAA". We split each combined bucket
    50/50 to populate our 5-bucket Literal schema (approximation).

    Column patterns:
      P_Tot_SEO          = English-only at home (total persons)
      P_Tot_UOLSE_VWorW  = uses other language + speaks English very well/well
      P_Tot_UOLSE_NWorNAA = uses other language + speaks English not well/not at all
    """
    seo = g13.get("P_Tot_SEO", 0)
    vw_or_w = g13.get("P_Tot_UOLSE_VWorW", 0)
    nw_or_naa = g13.get("P_Tot_UOLSE_NWorNAA", 0)

    raw = {
        "english_only": seo,
        "very_well": vw_or_w * 0.5,
        "well": vw_or_w * 0.5,
        "not_well": nw_or_naa * 0.5,
        "not_at_all": nw_or_naa * 0.5,
    }
    return _normalize({k: float(v) for k, v in raw.items()})


def _family_composition_distribution(g29: dict[str, int]) -> dict[str, float]:
    """
    G29: Family Composition.
    Maps ABS family categories to our 7-bucket schema.
    G29 covers families only (not single-person households or group households),
    so we approximate lone_person and group_household as 0; LANE_COVE_PROFILE
    will inject these from G35 / G36 if needed in future iterations.
    """
    # Couple families with children under 15 (CF_ChU15_a_*)
    couple_kids_under_15 = sum(
        v for k, v in g29.items()
        if k.startswith("CF_ChU15_a_") and k.endswith("_P") and "Total" not in k
    )
    # Couple families with no children under 15 but children 15+ (CF_no_ChU15_a_*)
    couple_kids_15plus = sum(
        v for k, v in g29.items()
        if k.startswith("CF_no_ChU15_a_") and k.endswith("_P") and "Total" not in k
    )
    # Couple families with no children
    couple_no_kids = g29.get("CF_no_children_P", 0)
    # One-parent families
    one_parent = sum(
        v for k, v in g29.items()
        if k.startswith("OPF_") and k.endswith("_P") and "Total" not in k
    )
    # Other families (e.g. siblings sharing household)
    other_fam = sum(
        v for k, v in g29.items()
        if k.startswith("Other_") and k.endswith("_P") and "Total" not in k
    )

    raw = {
        "couple_no_kids": couple_no_kids,
        "couple_kids_under_15": couple_kids_under_15,
        "couple_kids_15plus": couple_kids_15plus,
        "one_parent_family": one_parent,
        "other": other_fam,
        # G29 doesn't capture; default 0
        "lone_person": 0,
        "group_household": 0,
    }
    return _normalize({k: float(v) for k, v in raw.items()})


def _dwelling_structure_distribution(g36: dict[str, int]) -> dict[str, float]:
    """G36: Dwelling Structure (Persons in dwellings)."""
    sep = g36.get("OPDs_Separate_house_Persons", 0)
    semi = g36.get("OPDs_SD_r_t_h_th_Tot_Psns", 0)
    flat = g36.get("OPDs_Flt_apart_Tot_Psns", 0)
    other = g36.get("OPDs_Other_dwelling_Tot_Psns", 0) + g36.get("OPDs_Caravan_Persons", 0)
    raw = {
        "separate_house": sep,
        "semi_detached": semi,
        "flat_apartment": flat,
        "other_dwelling": other,
    }
    return _normalize({k: float(v) for k, v in raw.items()})


def _vehicles_distribution(g34: dict[str, int]) -> dict[str, float]:
    """G34: Number of Motor Vehicles per dwelling."""
    z = g34.get("Num_MVs_per_dweling_0_MVs", 0)
    one = g34.get("Num_MVs_per_dweling_1_MVs", 0)
    two = g34.get("Num_MVs_per_dweling_2_MVs", 0)
    three_plus = (g34.get("Num_MVs_per_dweling_3_MVs", 0)
                  + g34.get("Num_MVs_per_dweling_4mo_MVs", 0))
    raw = {"0": z, "1": one, "2": two, "3plus": three_plus}
    return _normalize({k: float(v) for k, v in raw.items()})


def _year_of_arrival_distribution(g10: dict[str, int], g09: dict[str, int]) -> dict[str, float]:
    """
    G10: Country of Birth × Year of Arrival.
    Use `Tot_<year>` row-total columns (year sum across countries) to avoid
    double-counting Country×Year cells. Tot_Tot = total overseas-born.
    Australian-born = G09 grand_total - Tot_Tot.
    """
    pre_2000 = sum(g10.get(f"Tot_{p}", 0) for p in (
        "Before_1951", "1951_1960", "1961_1970", "1971_1980",
        "1981_1990", "1991_2000",
    ))
    y2000_2010 = g10.get("Tot_2001_2010", 0)
    y2011_2015 = g10.get("Tot_2011_2015", 0)
    y2016_2021 = sum(g10.get(f"Tot_{y}", 0) for y in
                     ("2016", "2017", "2018", "2019", "2020", "2021"))

    overseas_total = g10.get("Tot_Tot", 0) or (
        pre_2000 + y2000_2010 + y2011_2015 + y2016_2021
    )
    grand_total = g09.get("M_Tot_Tot", 0) + g09.get("F_Tot_Tot", 0)
    aus_born = max(0, grand_total - overseas_total)

    raw = {
        "australian_born": aus_born,
        "pre_2000": pre_2000,
        "2000_2010": y2000_2010,
        "2011_2015": y2011_2015,
        "2016_2021": y2016_2021,
    }
    return _normalize({k: float(v) for k, v in raw.items()})


# ---------------------------------------------------------------------------
# Tier 3 — completeness extractors
# ---------------------------------------------------------------------------

def _indigenous_distribution(g07: dict[str, int]) -> dict[str, float]:
    """G07: Indigenous Status by Age by Sex. Sum across all ages."""
    indig = sum(
        v for k, v in g07.items()
        if k.endswith("_Indigenous_P") and "Non_Indigenous" not in k
    )
    non_indig = sum(
        v for k, v in g07.items()
        if k.endswith("_Non_Indigenous_P")
    )
    raw = {"indigenous": indig, "non_indigenous": non_indig}
    return _normalize({k: float(v) for k, v in raw.items()})


def _disability_distribution(g18: dict[str, int]) -> dict[str, float]:
    """G18: Core Activity Need for Assistance by Age by Sex."""
    needs = 0
    no_needs = 0
    for col, val in g18.items():
        if not col.startswith(("M_", "F_")):
            continue
        # Pattern: "M_<age>_yrs_Need_for_assistance" / "M_<age>_No_need_for_assistance"
        if "No_need_for_assist" in col or "No_need_for_assist" in col.replace("assistnce", "assistance"):
            no_needs += val
        elif "Need_for_assist" in col and "_ns" not in col:
            needs += val
    raw = {"needs_assistance": needs, "no_assistance": no_needs}
    return _normalize({k: float(v) for k, v in raw.items()})


def _education_distribution(g16: dict[str, int], g49: dict[str, int]) -> dict[str, float]:
    """
    G16+G49: Highest Year of School + Non-School Qualification.

    Schema: G16 covers all 15+ no-longer-at-school by highest year. G49
    covers subset who ALSO have a non-school qual.

    Strategy: postgrad/bachelor/diploma from G49 (override school year).
    Then y12_only / y11_or_below / no_qualification from G16 minus the
    G49 overlap.
    """
    # Use *_Total columns (sum across age buckets per qualification)
    pg = (g49.get("M_PGrad_Deg_Total", 0) + g49.get("F_PGrad_Deg_Total", 0)
          + g49.get("M_GradDip_and_GradCert_Total", 0)
          + g49.get("F_GradDip_and_GradCert_Total", 0))
    bachelor = (g49.get("M_BachDeg_Total", 0) + g49.get("F_BachDeg_Total", 0))
    diploma = (g49.get("M_AdDip_and_Dip_Total", 0) + g49.get("F_AdDip_and_Dip_Total", 0)
               + g49.get("M_Cert_III_IV_Total", 0) + g49.get("F_Cert_III_IV_Total", 0)
               + g49.get("M_Cert_III_IV_NFD_Total", 0) + g49.get("F_Cert_III_IV_NFD_Total", 0))
    g49_total = pg + bachelor + diploma

    # G16 totals (use _Tot suffix; people 15+ no longer at school)
    y12 = g16.get("M_Y12e_Tot", 0) + g16.get("F_Y12e_Tot", 0)
    y11 = g16.get("M_Y11e_Tot", 0) + g16.get("F_Y11e_Tot", 0)
    y10 = g16.get("M_Y10e_Tot", 0) + g16.get("F_Y10e_Tot", 0)
    y9 = g16.get("M_Y9e_Tot", 0) + g16.get("F_Y9e_Tot", 0)
    y8b = g16.get("M_Y8b_Tot", 0) + g16.get("F_Y8b_Tot", 0)
    dng = g16.get("M_DNGTS_Tot", 0) + g16.get("F_DNGTS_Tot", 0)  # did not go to school
    ns = g16.get("M_Hghst_yr_schl_ns_Tot", 0) + g16.get("F_Hghst_yr_schl_ns_Tot", 0)

    # G49 people are mostly Y12-finishers; subtract their G49 count from y12
    y12_only = max(0, y12 - g49_total)
    y11_or_below = y11 + y10 + y9 + y8b + dng
    no_qual = ns

    raw = {
        "postgrad": pg,
        "bachelor": bachelor,
        "diploma": diploma,
        "year_12": y12_only,
        "year_11_or_below": y11_or_below,
        "no_qualification": no_qual,
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


def convert(datapack_dir: Path, sa2_code: str = LANE_COVE_SA2, *, full: bool = False) -> dict:
    g01 = _read_sa2_row(datapack_dir / "2021Census_G01_NSW_SA2.csv", sa2_code)
    g37 = _read_sa2_row(datapack_dir / "2021Census_G37_NSW_SA2.csv", sa2_code)
    g62 = _read_sa2_row(datapack_dir / "2021Census_G62_NSW_SA2.csv", sa2_code)
    g09 = _read_split_table(datapack_dir, "G09", sa2_code)
    g17 = _read_split_table(datapack_dir, "G17", sa2_code)

    distributions = {
        "age": _age_distribution(g01),
        "gender": _gender_distribution(g01),
        "housing_tenure": _housing_tenure_distribution(g37),
        "income_tier": _income_tier_distribution(g17),
        "ethnicity_group": _ethnicity_distribution(g09),
        "work_mode": _work_mode_distribution(g62),
    }

    tables_used = {
        "G01": "Selected Person Characteristics by Sex (age + gender)",
        "G09": "Country of Birth by Age by Sex (ethnicity proxy)",
        "G17": "Total Personal Income Weekly by Age by Sex",
        "G37": "Tenure and Landlord Type by Dwelling Structure",
        "G62": "Method of Travel to Work by Sex (work mode proxy)",
    }

    if full:
        # agent-profile-enrich: 13 additional dimensions
        g07 = _read_sa2_row(datapack_dir / "2021Census_G07_NSW_SA2.csv", sa2_code)
        g10 = _read_split_table(datapack_dir, "G10", sa2_code)
        g13 = _read_split_table(datapack_dir, "G13", sa2_code)
        g16 = _read_split_table(datapack_dir, "G16", sa2_code)
        g18 = _read_sa2_row(datapack_dir / "2021Census_G18_NSW_SA2.csv", sa2_code)
        g23 = _read_sa2_row(datapack_dir / "2021Census_G23_NSW_SA2.csv", sa2_code)
        g24 = _read_split_table(datapack_dir, "G24", sa2_code)
        g25 = _read_sa2_row(datapack_dir / "2021Census_G25_NSW_SA2.csv", sa2_code)
        g26 = _read_split_table(datapack_dir, "G26", sa2_code)
        g29 = _read_sa2_row(datapack_dir / "2021Census_G29_NSW_SA2.csv", sa2_code)
        g34 = _read_sa2_row(datapack_dir / "2021Census_G34_NSW_SA2.csv", sa2_code)
        g36 = _read_sa2_row(datapack_dir / "2021Census_G36_NSW_SA2.csv", sa2_code)
        g45 = _read_sa2_row(datapack_dir / "2021Census_G45_NSW_SA2.csv", sa2_code)
        g49 = _read_split_table(datapack_dir, "G49", sa2_code)

        distributions.update({
            "community_tenure_5yr": _community_tenure_distribution(g45),
            "unpaid_child_care_hours": _unpaid_child_care_distribution(g26),
            "unpaid_domestic_hours": _unpaid_domestic_distribution(g24),
            "unpaid_disability_care_hours": _unpaid_disability_care_distribution(g25),
            "volunteer_status": _volunteer_distribution(g23),
            "english_proficiency": _english_proficiency_distribution(g13),
            "family_composition": _family_composition_distribution(g29),
            "dwelling_structure": _dwelling_structure_distribution(g36),
            "vehicles_at_dwelling": _vehicles_distribution(g34),
            "year_of_arrival_bucket": _year_of_arrival_distribution(g10, g09),
            "indigenous_status": _indigenous_distribution(g07),
            "disability_status": _disability_distribution(g18),
            "education_level": _education_distribution(g16, g49),
        })

        tables_used.update({
            "G07": "Indigenous Status by Age by Sex",
            "G10": "Country of Birth × Year of Arrival",
            "G13": "Language at Home + English Proficiency",
            "G16": "Highest Year of School Completed",
            "G18": "Core Activity Need for Assistance",
            "G23": "Voluntary Work for Organisation/Group",
            "G24": "Unpaid Domestic Work Hours",
            "G25": "Unpaid Assistance to Disabled",
            "G26": "Unpaid Child Care",
            "G29": "Family Composition",
            "G34": "Number of Motor Vehicles per Dwelling",
            "G36": "Dwelling Structure",
            "G45": "Place of Usual Residence 5 Years Ago",
            "G49": "Highest Non-School Qualification",
        })

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
        "tables_used": tables_used,
        "geographic_caveat": (
            "Atlas extent slightly over-extends north into SA2 121011399 "
            "(Chatswood West / Lane Cove North). Calibration uses single-SA2 "
            "121011686 only; future iteration could blend two SA2s by area share."
        ),
        "schema_caveat": (
            "shift work mode is 0 in G62-derived distribution (G62 doesn't "
            "separate shift); future iteration can blend G46 LFS data."
            + (" G26 lacks hour granularity → unpaid_child_care_hours bucket "
               "approximation: any care → 15_29 mid-bucket." if full else "")
        ),
        "total_population": g01["Tot_P_P"],
        "distributions": {
            **distributions,
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
    ap.add_argument(
        "--full", action="store_true",
        help="Also extract 13 thesis-direct dimensions "
             "(community_tenure / unpaid_*_hours / family_composition / etc.)",
    )
    args = ap.parse_args()

    if not args.datapack_dir.exists():
        sys.stderr.write(
            f"error: DataPack folder not found: {args.datapack_dir}\n"
            "  Download from https://www.abs.gov.au/census/find-census-data/datapacks\n"
            "  Choose: General Community Profile, SA2, NSW.\n"
        )
        return 2

    payload = convert(args.datapack_dir, sa2_code=args.sa2_code, full=args.full)
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
