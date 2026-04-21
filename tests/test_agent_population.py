"""Tests for agent.population — deterministic sampling, coverage, protagonists."""

from __future__ import annotations

import pytest

from synthetic_socio_wind_tunnel.agent import (
    LANE_COVE_PROFILE,
    AgentProfile,
    PopulationProfile,
    sample_population,
)


class TestDeterminism:

    def test_same_seed_same_output(self):
        a = sample_population(LANE_COVE_PROFILE, seed=42)
        b = sample_population(LANE_COVE_PROFILE, seed=42)
        assert len(a) == len(b) == LANE_COVE_PROFILE.size
        for pa, pb in zip(a, b):
            assert pa.model_dump() == pb.model_dump()

    def test_different_seed_different_output(self):
        a = sample_population(LANE_COVE_PROFILE, seed=1)
        b = sample_population(LANE_COVE_PROFILE, seed=2)
        # Extremely unlikely to produce identical lists
        assert any(pa.model_dump() != pb.model_dump() for pa, pb in zip(a, b))

    def test_agent_id_format(self):
        sample = sample_population(LANE_COVE_PROFILE, seed=7)
        assert sample[0].agent_id == "a_7_0000"
        assert sample[999].agent_id == "a_7_0999"


class TestDimensionCoverage:

    def test_structural_dims_all_present(self):
        sample = sample_population(LANE_COVE_PROFILE, seed=1)
        assert all(p.ethnicity_group for p in sample)
        assert all(p.housing_tenure for p in sample)
        assert all(p.income_tier for p in sample)
        assert all(p.work_mode for p in sample)

    def test_every_distribution_value_appears(self):
        sample = sample_population(LANE_COVE_PROFILE, seed=1)
        ethnicities = {p.ethnicity_group for p in sample}
        assert ethnicities == set(LANE_COVE_PROFILE.ethnicity_distribution.keys())
        housings = {p.housing_tenure for p in sample}
        assert housings == set(LANE_COVE_PROFILE.housing_distribution.keys())
        incomes = {p.income_tier for p in sample}
        assert incomes == set(LANE_COVE_PROFILE.income_distribution.keys())
        work_modes = {p.work_mode for p in sample}
        assert work_modes == set(LANE_COVE_PROFILE.work_mode_distribution.keys())

    def test_digital_screen_hours_varies(self):
        sample = sample_population(LANE_COVE_PROFILE, seed=1)
        screens = [p.digital.daily_screen_hours for p in sample]
        mean = sum(screens) / len(screens)
        variance = sum((s - mean) ** 2 for s in screens) / len(screens)
        std = variance ** 0.5
        assert std >= 1.0, f"screen_hours std too low: {std:.2f}"


class TestProtagonists:

    def test_count_matches(self):
        sample = sample_population(LANE_COVE_PROFILE, seed=1, num_protagonists=10)
        protagonists = [p for p in sample if p.is_protagonist]
        assert len(protagonists) == 10

    def test_protagonist_base_model_upgraded(self):
        sample = sample_population(LANE_COVE_PROFILE, seed=1, num_protagonists=5)
        for p in sample:
            if p.is_protagonist:
                assert p.base_model == LANE_COVE_PROFILE.sonnet_model
            else:
                assert p.base_model == LANE_COVE_PROFILE.haiku_model

    def test_too_many_protagonists_rejected(self):
        small = PopulationProfile(
            **{**LANE_COVE_PROFILE.model_dump(), "size": 3, "name": "tiny"}
        )
        with pytest.raises(ValueError):
            sample_population(small, seed=1, num_protagonists=5)


class TestDistributionValidation:

    def test_non_normalized_rejected(self):
        bad = {
            **LANE_COVE_PROFILE.model_dump(),
            "name": "bad",
            "ethnicity_distribution": {"AU-born": 0.5, "AU-migrant-1gen-asia": 0.3},
        }
        with pytest.raises(Exception):  # pydantic validation error
            PopulationProfile(**bad)


class TestPresets:

    def test_lane_cove_preset_valid(self):
        sample = sample_population(LANE_COVE_PROFILE, seed=1)
        assert len(sample) == 1000
        assert all(isinstance(p, AgentProfile) for p in sample)


class TestHomeLocationsPool:

    def test_uses_provided_pool(self):
        small = PopulationProfile(
            **{**LANE_COVE_PROFILE.model_dump(), "size": 10, "name": "small"}
        )
        sample = sample_population(
            small,
            seed=1,
            home_locations=("apt_a", "apt_b", "apt_c"),
        )
        assert all(p.home_location in {"apt_a", "apt_b", "apt_c"} for p in sample)

    def test_defaults_to_generated_home_ids(self):
        small = PopulationProfile(
            **{**LANE_COVE_PROFILE.model_dump(), "size": 5, "name": "small"}
        )
        sample = sample_population(small, seed=1)
        assert sample[0].home_location == "home_0000"
