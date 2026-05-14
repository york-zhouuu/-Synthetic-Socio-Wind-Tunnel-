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

    def test_uses_provided_pool_emits_deprecation(self):
        import warnings

        small = PopulationProfile(
            **{**LANE_COVE_PROFILE.model_dump(), "size": 10, "name": "small"}
        )
        with warnings.catch_warnings(record=True) as warned:
            warnings.simplefilter("always")
            sample = sample_population(
                small,
                seed=1,
                home_locations=("apt_a", "apt_b", "apt_c"),
            )
        assert all(p.home_location in {"apt_a", "apt_b", "apt_c"} for p in sample)
        deprecation = [w for w in warned if issubclass(w.category, DeprecationWarning)]
        assert deprecation, "home_locations path must emit DeprecationWarning"

    def test_defaults_to_generated_home_ids(self):
        small = PopulationProfile(
            **{**LANE_COVE_PROFILE.model_dump(), "size": 5, "name": "small"}
        )
        sample = sample_population(small, seed=1)
        assert sample[0].home_location == "home_0000"


class TestPoolsPath:

    def _get_atlas(self):
        import os
        from synthetic_socio_wind_tunnel import Atlas
        path = "data/lanecove_atlas.json"
        if not os.path.exists(path):
            import pytest
            pytest.skip("Lane Cove atlas fixture not available")
        return Atlas.from_json(path)

    def _get_pools(self, atlas, seed: int = 42):
        import random
        from synthetic_socio_wind_tunnel import build_location_pools
        return build_location_pools(
            atlas, home_count=40, work_count=20, poi_count=30,
            rng=random.Random(seed),
        )

    def test_pools_homes_all_residential(self):
        atlas = self._get_atlas()
        pools = self._get_pools(atlas)
        small = PopulationProfile(
            **{**LANE_COVE_PROFILE.model_dump(), "size": 30, "name": "small"}
        )
        sample = sample_population(small, seed=1, pools=pools)
        for p in sample:
            b = atlas.get_building(p.home_location)
            assert b is not None, f"home {p.home_location} not a building"
            assert b.building_type == "residential", (
                f"home {p.home_location} is {b.building_type}, expected residential"
            )

    def test_pools_workplace_matches_work_mode(self):
        atlas = self._get_atlas()
        pools = self._get_pools(atlas)
        small = PopulationProfile(
            **{**LANE_COVE_PROFILE.model_dump(), "size": 50, "name": "small"}
        )
        sample = sample_population(small, seed=1, pools=pools)
        for p in sample:
            if p.work_mode in ("commute", "remote", "shift"):
                assert p.workplace is not None, (
                    f"working agent {p.agent_id} ({p.work_mode}) has no workplace"
                )
                assert p.workplace in pools.work_pool
            else:
                assert p.workplace is None, (
                    f"non-working agent {p.agent_id} ({p.work_mode}) "
                    f"unexpectedly has workplace={p.workplace}"
                )

    def test_pools_path_deterministic(self):
        atlas = self._get_atlas()
        pools = self._get_pools(atlas)
        small = PopulationProfile(
            **{**LANE_COVE_PROFILE.model_dump(), "size": 20, "name": "small"}
        )
        a = sample_population(small, seed=99, pools=pools)
        b = sample_population(small, seed=99, pools=pools)
        assert [p.home_location for p in a] == [p.home_location for p in b]
        assert [p.workplace for p in a] == [p.workplace for p in b]

    def test_validate_against_atlas_accepts_residential(self):
        from synthetic_socio_wind_tunnel.agent.profile import validate_against_atlas
        atlas = self._get_atlas()
        pools = self._get_pools(atlas)
        small = PopulationProfile(
            **{**LANE_COVE_PROFILE.model_dump(), "size": 20, "name": "small"}
        )
        sample = sample_population(small, seed=1, pools=pools)
        for p in sample:
            validate_against_atlas(p, atlas)

    def test_validate_against_atlas_rejects_street_home(self):
        import pytest
        from synthetic_socio_wind_tunnel.agent.profile import (
            AgentProfile, validate_against_atlas,
        )
        atlas = self._get_atlas()
        bad = AgentProfile(
            agent_id="x", name="x", age=30, occupation="x",
            household="single",
            home_location="kenneth_street_seg_1",
        )
        with pytest.raises(ValueError, match="home_location"):
            validate_against_atlas(bad, atlas)
