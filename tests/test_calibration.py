"""Unit tests for synthetic_socio_wind_tunnel.agent.calibration."""

from __future__ import annotations

from collections import Counter

import numpy as np
import pytest

from synthetic_socio_wind_tunnel.agent import LANE_COVE_PROFILE, sample_population
from synthetic_socio_wind_tunnel.agent.calibration import (
    CalibrationStatus,
    assess_behavioral_calibration,
    assess_population_calibration,
    compute_od_chi_squared,
    compute_popular_times_emd,
    compute_population_distance,
)


class TestAssessPopulationCalibration:

    def test_strict_when_all_pass(self):
        p_values = {"age": 0.5, "gender": 0.4, "housing_tenure": 0.3,
                    "income_tier": 0.2, "ethnicity_group": 0.15, "work_mode": 0.11}
        status = assess_population_calibration(p_values)
        assert status.passed is True
        assert status.acceptance_level == "strict"
        assert status.failed_dimensions == []

    def test_best_effort_when_4_of_6_pass(self):
        p_values = {"age": 0.5, "gender": 0.4, "housing_tenure": 0.3,
                    "income_tier": 0.2, "ethnicity_group": 0.05, "work_mode": 0.01}
        status = assess_population_calibration(p_values)
        assert status.passed is True
        assert status.acceptance_level == "best-effort"
        assert set(status.failed_dimensions) == {"ethnicity_group", "work_mode"}

    def test_failing_when_only_3_pass(self):
        p_values = {"age": 0.5, "gender": 0.4, "housing_tenure": 0.3,
                    "income_tier": 0.05, "ethnicity_group": 0.04, "work_mode": 0.01}
        status = assess_population_calibration(p_values)
        assert status.passed is False
        assert status.acceptance_level == "failing"
        assert len(status.failed_dimensions) == 3

    def test_empty_p_values_returns_failing(self):
        status = assess_population_calibration({})
        assert status.passed is False
        assert status.acceptance_level == "failing"

    def test_threshold_boundary(self):
        # Exactly at threshold (0.10) should fail (strictly greater required)
        p_values = {"age": 0.10, "gender": 0.10, "housing_tenure": 0.10,
                    "income_tier": 0.10, "ethnicity_group": 0.10, "work_mode": 0.10}
        status = assess_population_calibration(p_values)
        assert status.acceptance_level == "failing"


class TestComputePopulationDistance:

    def test_identical_distribution_high_p_value(self):
        # Sample matches ABS exactly → should not reject null hypothesis
        agents = sample_population(LANE_COVE_PROFILE, seed=42)
        # Build "ABS data" from the same distribution
        gender_counts = Counter(a.gender for a in agents)
        n = len(agents)
        abs_data = {
            "distributions": {
                "gender": {k: v / n for k, v in gender_counts.items()},
            }
        }
        p_values = compute_population_distance(agents, abs_data)
        assert "gender" in p_values
        # Self-comparison should yield very high p (close to 1.0)
        assert p_values["gender"] > 0.9

    def test_skewed_distribution_low_p_value(self):
        # Sample is balanced; ABS claims 99/1 split → should reject
        agents = sample_population(LANE_COVE_PROFILE, seed=42)
        abs_data = {
            "distributions": {
                "gender": {"male": 0.99, "female": 0.005, "non_binary": 0.005},
            }
        }
        p_values = compute_population_distance(agents, abs_data)
        assert p_values["gender"] < 0.10

    def test_missing_dimension_skipped(self):
        agents = sample_population(LANE_COVE_PROFILE, seed=42)
        abs_data = {"distributions": {"age": {"30-34": 0.5, "35-39": 0.5}}}
        p_values = compute_population_distance(agents, abs_data)
        # Only age evaluated; other 5 dims absent from abs_data → skipped
        assert "age" in p_values
        assert "gender" not in p_values


class TestComputeODChiSquared:

    def test_identical_OD_high_p(self):
        od = np.array([[100, 50], [25, 75]])
        p = compute_od_chi_squared(od.copy(), od.copy())
        assert p > 0.9

    def test_completely_different_OD_low_p(self):
        sim = np.array([[100, 0], [0, 0]])
        abs_od = np.array([[0, 100], [0, 0]])
        p = compute_od_chi_squared(sim, abs_od)
        assert p < 0.05

    def test_shape_mismatch_raises(self):
        with pytest.raises(ValueError):
            compute_od_chi_squared(np.array([[1, 2]]), np.array([[1], [2]]))

    def test_all_zero_returns_zero(self):
        z = np.zeros((2, 2), dtype=int)
        assert compute_od_chi_squared(z, z) == 0.0


class TestComputePopularTimesEMD:

    def test_identical_grids_zero_emd(self):
        grid = [[10] * 24 for _ in range(7)]
        emds = compute_popular_times_emd({"poi_a": grid}, {"poi_a": grid})
        assert emds["poi_a"] < 0.001

    def test_disjoint_peaks_high_emd(self):
        # sim: morning peak; popular_times: evening peak
        sim_grid = [[100 if h == 8 else 0 for h in range(24)] for _ in range(7)]
        pop_grid = [[100 if h == 20 else 0 for h in range(24)] for _ in range(7)]
        emds = compute_popular_times_emd({"poi_a": sim_grid}, {"poi_a": pop_grid})
        # Peak shift of 12 hours in 168-bin space → EMD significantly nonzero
        assert emds["poi_a"] > 0.05

    def test_missing_poi_skipped(self):
        emds = compute_popular_times_emd(
            {"poi_a": [[1] * 24] * 7}, {"poi_b": [[1] * 24] * 7},
        )
        assert emds == {}

    def test_zero_visits_skipped(self):
        zero_grid = [[0] * 24 for _ in range(7)]
        nonzero = [[5] * 24 for _ in range(7)]
        emds = compute_popular_times_emd({"poi": zero_grid}, {"poi": nonzero})
        assert emds == {}


class TestAssessBehavioralCalibration:

    def test_strict_pass(self):
        emds = {f"poi_{i}": 0.05 for i in range(20)}
        status = assess_behavioral_calibration(od_p_value=0.5, poi_emds=emds)
        assert status.acceptance_level == "strict"
        assert status.passed is True

    def test_best_effort_pass(self):
        # 70% under 0.25 but only 60% under 0.20 → best-effort only
        emds = {f"poi_{i}": (0.18 if i < 12 else 0.23) for i in range(20)}
        status = assess_behavioral_calibration(od_p_value=0.07, poi_emds=emds)
        assert status.acceptance_level == "best-effort"

    def test_failing_when_emd_coverage_low(self):
        emds = {f"poi_{i}": 0.50 for i in range(20)}
        status = assess_behavioral_calibration(od_p_value=0.5, poi_emds=emds)
        assert status.acceptance_level == "failing"
        assert "emd_coverage" in status.failed_dimensions

    def test_failing_when_od_p_low(self):
        emds = {f"poi_{i}": 0.05 for i in range(20)}
        status = assess_behavioral_calibration(od_p_value=0.01, poi_emds=emds)
        assert status.acceptance_level == "failing"
        assert "od_p" in status.failed_dimensions

    def test_no_pois_failing(self):
        status = assess_behavioral_calibration(od_p_value=0.5, poi_emds={})
        assert status.acceptance_level == "failing"


class TestPopulationProfileGenderField:
    """Verifies gender plumbing wires through PopulationProfile + sample."""

    def test_gender_assigned_to_all_agents(self):
        agents = sample_population(LANE_COVE_PROFILE, seed=42)
        assert all(a.gender is not None for a in agents)
        assert all(a.gender in ("male", "female", "non_binary") for a in agents)

    def test_gender_distribution_roughly_matches_profile(self):
        agents = sample_population(LANE_COVE_PROFILE, seed=42)
        n = len(agents)
        counts = Counter(a.gender for a in agents)
        male_pct = counts["male"] / n
        # Default profile: 0.487 male; 1000-sample should be within ±0.05
        assert abs(male_pct - 0.487) < 0.05

    def test_seed_reproducibility(self):
        a = sample_population(LANE_COVE_PROFILE, seed=42)
        b = sample_population(LANE_COVE_PROFILE, seed=42)
        assert [x.gender for x in a] == [x.gender for x in b]
