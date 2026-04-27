"""
Calibration helpers — population & behavioral distance metrics.

Implements `validation-strategy` Part IV / Part V via static ABS Census +
Travel Survey + Popular Times snapshots.

Public API:
    compute_population_distance(samples, abs_data) -> dict[dim, p_value]
    assess_population_calibration(p_values, ...) -> CalibrationStatus
    compute_od_chi_squared(sim_OD, abs_OD) -> float
    compute_popular_times_emd(sim_visits, popular_times) -> dict[poi_id, emd]
    assess_behavioral_calibration(...) -> CalibrationStatus

Sim hot path MUST NOT import this module — calibration is offline-only
(see `agent-calibration` change spec D7).
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field
from scipy.stats import chi2_contingency, kstest, wasserstein_distance

from .profile import AgentProfile

# ---------------------------------------------------------------------------
# Status models
# ---------------------------------------------------------------------------

AcceptanceLevel = Literal["strict", "best-effort", "failing"]


class CalibrationStatus(BaseModel):
    """Outcome of one calibration assessment (population OR behavioral)."""
    passed: bool
    acceptance_level: AcceptanceLevel
    details: dict[str, Any] = Field(default_factory=dict)
    failed_dimensions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Population calibration
# ---------------------------------------------------------------------------

# 6 dimensions per validation-strategy Part IV. Discrete fields → chi²;
# continuous → KS. age is bucketed so discrete here.
_POPULATION_DIMENSIONS: tuple[str, ...] = (
    "age", "gender", "housing_tenure", "income_tier",
    "ethnicity_group", "work_mode",
)

# agent-profile-enrich (2026-04-27): tier-based acceptance.
# Tier 1 = original 6 + 5 new thesis-core dims.
# Tier 2 = 5 refinement dims.
# Tier 3 = 3 completeness dims (no failure budget).
_TIER1_NEW_DIMENSIONS: tuple[str, ...] = (
    "community_tenure_5yr", "unpaid_child_care_hours", "unpaid_domestic_hours",
    "unpaid_disability_care_hours", "volunteer_status",
)
_TIER2_DIMENSIONS: tuple[str, ...] = (
    "english_proficiency", "family_composition", "dwelling_structure",
    "vehicles_at_dwelling", "year_of_arrival_bucket",
)
_TIER3_DIMENSIONS: tuple[str, ...] = (
    "indigenous_status", "disability_status", "education_level",
)


def _age_bucket(age: int) -> str:
    """
    Bucket age to match ABS Census 2021 G01 buckets (11 buckets).
    `0-4`, `5-14`, `15-19`, `20-24`, `25-34`, `35-44`, `45-54`, `55-64`,
    `65-74`, `75-84`, `85+`.
    """
    if age < 5:
        return "0-4"
    if age < 15:
        return "5-14"
    if age < 20:
        return "15-19"
    if age < 25:
        return "20-24"
    if age < 35:
        return "25-34"
    if age < 45:
        return "35-44"
    if age < 55:
        return "45-54"
    if age < 65:
        return "55-64"
    if age < 75:
        return "65-74"
    if age < 85:
        return "75-84"
    return "85+"


def _sample_attribute(profile: AgentProfile, dim: str) -> str | None:
    """Map calibration dimension name to AgentProfile attribute value."""
    if dim == "age":
        return _age_bucket(profile.age)
    # Direct field names (original 6 + 13 enrichment fields)
    return getattr(profile, _DIM_TO_FIELD.get(dim, dim), None)


_DIM_TO_FIELD: dict[str, str] = {
    "gender": "gender",
    "housing_tenure": "housing_tenure",
    "income_tier": "income_tier",
    "ethnicity_group": "ethnicity_group",
    "work_mode": "work_mode",
    # agent-profile-enrich (Tier 1)
    "community_tenure_5yr": "community_tenure_5yr",
    "unpaid_child_care_hours": "unpaid_child_care_hours",
    "unpaid_domestic_hours": "unpaid_domestic_hours",
    "unpaid_disability_care_hours": "unpaid_disability_care_hours",
    "volunteer_status": "volunteer_status",
    # Tier 2
    "english_proficiency": "english_proficiency",
    "family_composition": "family_composition",
    "dwelling_structure": "dwelling_structure",
    "vehicles_at_dwelling": "vehicles_at_dwelling",
    "year_of_arrival_bucket": "year_of_arrival_bucket",
    # Tier 3
    "indigenous_status": "indigenous_status",
    "disability_status": "disability_status",
    "education_level": "education_level",
}


def _normalize_distribution(
    counts: Counter, abs_buckets: list[str],
) -> tuple[list[int], list[int]]:
    """
    Align sample counts to ABS bucket order. Returns (sample_counts, abs_counts).
    Buckets present in samples but not in abs_buckets are folded into "other".
    """
    sample_counts = []
    other_count = 0
    for bucket in abs_buckets:
        sample_counts.append(counts.get(bucket, 0))
    seen = set(abs_buckets)
    for bucket, n in counts.items():
        if bucket not in seen:
            other_count += n
    if "other" in abs_buckets:
        # other is already in the alignment
        pass
    elif other_count > 0:
        sample_counts.append(other_count)
        abs_buckets = list(abs_buckets) + ["other"]
    return sample_counts, abs_buckets


def _chi_squared_p(
    samples: list[AgentProfile], abs_dist: dict[str, float], dim: str,
) -> float:
    """Compute chi² p-value for one discrete dimension."""
    n = len(samples)
    if n == 0 or not abs_dist:
        return 0.0

    counts: Counter = Counter()
    skipped = 0
    for p in samples:
        v = _sample_attribute(p, dim)
        if v is None:
            skipped += 1
            continue
        counts[v] += 1

    if not counts:
        return 0.0

    abs_buckets = list(abs_dist.keys())
    sample_aligned, _ = _normalize_distribution(counts, abs_buckets)

    n_aligned = sum(sample_aligned)
    if n_aligned == 0:
        return 0.0

    # Observed vs expected (expected is ABS proportion × n_aligned)
    expected = [abs_dist[b] * n_aligned for b in abs_buckets]
    if len(sample_aligned) > len(expected):
        expected.append(0.0)

    # Build 2×k contingency: row 0 = sample, row 1 = expected scaled.
    # chi2_contingency wants integer counts — round expected.
    expected_int = [max(1, int(round(e))) for e in expected]
    table = np.array([sample_aligned, expected_int])
    if table.sum() == 0 or table.shape[1] < 2:
        return 0.0
    try:
        _chi2, p_value, _dof, _exp = chi2_contingency(table)
    except ValueError:
        return 0.0
    return float(p_value)


def compute_population_distance(
    samples: list[AgentProfile], abs_data: dict[str, Any],
) -> dict[str, float]:
    """
    Returns p-value per population dimension.

    abs_data must follow `data/calibration/abs_census_lanecove_2021.json`
    schema: {"distributions": {<dim>: {<bucket>: <prop>, ...}, ...}}.

    Evaluates all dimensions present in abs_data (original 6 + any
    agent-profile-enrich dims that have been written).
    """
    distributions = abs_data.get("distributions", {})
    p_values: dict[str, float] = {}
    for dim, abs_dist in distributions.items():
        if not abs_dist:
            continue
        # Skip dims we don't know how to map to AgentProfile fields
        if dim != "age" and dim not in _DIM_TO_FIELD:
            continue
        p_values[dim] = _chi_squared_p(samples, abs_dist, dim)
    return p_values


def assess_population_calibration(
    p_values: dict[str, float], *,
    strict_threshold: float = 0.10,
    best_effort_min_dims: int = 4,
) -> CalibrationStatus:
    """
    Decide acceptance level from per-dim p-values, tier-aware.

    Two regimes based on what's evaluated:

    **Original 6 dims only** (no enrichment): legacy behavior:
    - strict = 6/6 pass; best-effort = ≥ 4/6 pass; else failing.

    **Enrichment dims present** (agent-profile-enrich):
    - strict   = original 6 all pass AND Tier 1 new (5) all pass
                 AND Tier 2 (5) ≥ 3 pass
    - best-effort = original 6 ≥ 4 pass AND Tier 1 new (5) ≥ 3 pass
    - failing  = otherwise
    Tier 3 (3 completeness dims) never blocks; status appears in disclosure.
    """
    if not p_values:
        return CalibrationStatus(
            passed=False, acceptance_level="failing",
            details={"reason": "no dimensions evaluated"},
        )

    def _passing(dims: tuple[str, ...]) -> int:
        return sum(1 for d in dims if p_values.get(d, 0.0) > strict_threshold)

    has_enrichment = any(d in p_values for d in _TIER1_NEW_DIMENSIONS)

    orig_pass = _passing(_POPULATION_DIMENSIONS)
    n_orig_present = sum(1 for d in _POPULATION_DIMENSIONS if d in p_values)

    if not has_enrichment:
        # Legacy regime
        if orig_pass == n_orig_present and n_orig_present > 0:
            level: AcceptanceLevel = "strict"
            passed = True
        elif orig_pass >= best_effort_min_dims:
            level = "best-effort"
            passed = True
        else:
            level = "failing"
            passed = False

        return CalibrationStatus(
            passed=passed, acceptance_level=level,
            details={
                "p_values": p_values,
                "n_passing": orig_pass,
                "n_total": n_orig_present,
                "strict_threshold": strict_threshold,
            },
            failed_dimensions=[
                d for d in _POPULATION_DIMENSIONS
                if d in p_values and p_values[d] <= strict_threshold
            ],
        )

    # Tiered regime
    tier1_new_pass = _passing(_TIER1_NEW_DIMENSIONS)
    tier1_new_present = sum(1 for d in _TIER1_NEW_DIMENSIONS if d in p_values)
    tier2_pass = _passing(_TIER2_DIMENSIONS)
    tier2_present = sum(1 for d in _TIER2_DIMENSIONS if d in p_values)
    tier3_pass = _passing(_TIER3_DIMENSIONS)
    tier3_present = sum(1 for d in _TIER3_DIMENSIONS if d in p_values)

    strict_ok = (
        orig_pass == n_orig_present
        and tier1_new_pass == tier1_new_present
        and tier2_pass >= 3
    )
    best_effort_ok = orig_pass >= best_effort_min_dims and tier1_new_pass >= 3

    if strict_ok:
        level = "strict"
        passed = True
    elif best_effort_ok:
        level = "best-effort"
        passed = True
    else:
        level = "failing"
        passed = False

    failing = [
        d for d, p in p_values.items()
        if p <= strict_threshold and d not in _TIER3_DIMENSIONS
    ]
    tier3_failing = [
        d for d in _TIER3_DIMENSIONS
        if d in p_values and p_values[d] <= strict_threshold
    ]

    return CalibrationStatus(
        passed=passed, acceptance_level=level,
        details={
            "p_values": p_values,
            "tier_breakdown": {
                "original_6": {"pass": orig_pass, "total": n_orig_present},
                "tier1_new_5": {"pass": tier1_new_pass, "total": tier1_new_present},
                "tier2_5": {"pass": tier2_pass, "total": tier2_present},
                "tier3_3": {"pass": tier3_pass, "total": tier3_present},
            },
            "tier3_disclosure": tier3_failing,
            "strict_threshold": strict_threshold,
        },
        failed_dimensions=failing,
    )


# ---------------------------------------------------------------------------
# Behavioral calibration
# ---------------------------------------------------------------------------

def compute_od_chi_squared(
    sim_od: np.ndarray, abs_od: np.ndarray,
) -> float:
    """
    chi² p-value for sim journey-to-work OD vs ABS OD.

    Both inputs are 2D matrices of integer trip counts; same shape.
    """
    if sim_od.shape != abs_od.shape:
        raise ValueError(f"OD shape mismatch: sim {sim_od.shape} vs abs {abs_od.shape}")
    sim_total = sim_od.sum()
    abs_total = abs_od.sum()
    if sim_total == 0 or abs_total == 0:
        return 0.0

    # Align: scale ABS to sim totals, then chi² as [sim, scaled_abs] table.
    scale = sim_total / abs_total
    abs_scaled = np.maximum(1, np.round(abs_od * scale)).astype(int)

    table = np.array([sim_od.flatten(), abs_scaled.flatten()])
    # Drop columns where both are zero (chi² fails on all-zero column)
    mask = (table.sum(axis=0) > 0)
    table = table[:, mask]
    if table.shape[1] < 2:
        return 0.0
    try:
        _chi2, p_value, _dof, _exp = chi2_contingency(table)
    except ValueError:
        return 0.0
    return float(p_value)


def compute_popular_times_emd(
    sim_visits: dict[str, list[list[int]]],
    popular_times: dict[str, list[list[int]]],
) -> dict[str, float]:
    """
    Earth Mover's Distance per POI between sim visits and Popular Times.

    Each value is a 7×24 matrix (day-of-week × hour). EMD is computed on
    flattened 168-bin distributions, normalized to sum=1.

    Returns dict {poi_id: emd}; missing POIs are skipped.
    """
    out: dict[str, float] = {}
    for poi_id, sim_grid in sim_visits.items():
        pop_grid = popular_times.get(poi_id)
        if pop_grid is None:
            continue
        sim_arr = np.array(sim_grid, dtype=float).flatten()
        pop_arr = np.array(pop_grid, dtype=float).flatten()
        if sim_arr.shape != pop_arr.shape:
            continue
        if sim_arr.sum() == 0 or pop_arr.sum() == 0:
            continue
        sim_norm = sim_arr / sim_arr.sum()
        pop_norm = pop_arr / pop_arr.sum()
        # 1D wasserstein on bin index
        bins = np.arange(len(sim_norm), dtype=float)
        emd = wasserstein_distance(bins, bins, sim_norm, pop_norm)
        # Normalize EMD to [0, 1] by dividing by max possible distance (n-1)
        out[poi_id] = float(emd / max(1, len(sim_norm) - 1))
    return out


def assess_behavioral_calibration(
    od_p_value: float,
    poi_emds: dict[str, float],
    *,
    strict_od_p: float = 0.10,
    strict_emd_threshold: float = 0.20,
    strict_emd_pct: float = 0.80,
    best_effort_od_p: float = 0.05,
    best_effort_emd_threshold: float = 0.25,
    best_effort_emd_pct: float = 0.70,
) -> CalibrationStatus:
    """Decide behavioral acceptance level."""
    n_pois = len(poi_emds)
    if n_pois == 0:
        return CalibrationStatus(
            passed=False, acceptance_level="failing",
            details={"reason": "no POIs evaluated"},
        )

    pct_under_strict = sum(1 for v in poi_emds.values() if v < strict_emd_threshold) / n_pois
    pct_under_best = sum(1 for v in poi_emds.values() if v < best_effort_emd_threshold) / n_pois

    strict_pass = (od_p_value > strict_od_p and pct_under_strict >= strict_emd_pct)
    best_pass = (od_p_value > best_effort_od_p and pct_under_best >= best_effort_emd_pct)

    if strict_pass:
        level: AcceptanceLevel = "strict"
        passed = True
    elif best_pass:
        level = "best-effort"
        passed = True
    else:
        level = "failing"
        passed = False

    failing: list[str] = []
    if od_p_value <= best_effort_od_p:
        failing.append("od_p")
    if pct_under_best < best_effort_emd_pct:
        failing.append("emd_coverage")

    return CalibrationStatus(
        passed=passed,
        acceptance_level=level,
        details={
            "od_p_value": od_p_value,
            "n_pois": n_pois,
            "pct_emd_under_strict": pct_under_strict,
            "pct_emd_under_best_effort": pct_under_best,
        },
        failed_dimensions=failing,
    )


__all__ = [
    "CalibrationStatus",
    "AcceptanceLevel",
    "compute_population_distance",
    "assess_population_calibration",
    "compute_od_chi_squared",
    "compute_popular_times_emd",
    "assess_behavioral_calibration",
]
