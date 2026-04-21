"""Tests for PersonalityTraits sampling in sample_population."""

from __future__ import annotations

import statistics

import pytest

from synthetic_socio_wind_tunnel.agent import (
    LANE_COVE_PROFILE,
    PopulationProfile,
    sample_population,
)
from synthetic_socio_wind_tunnel.agent.population import PersonalityParams


class TestPersonalityHeterogeneity:

    def test_1000_sample_curiosity_std(self):
        """Default params (0.5, 0.2) should produce std >= 0.15."""
        sample = sample_population(LANE_COVE_PROFILE, seed=42)
        curiosities = [p.personality.curiosity for p in sample]
        std = statistics.stdev(curiosities)
        assert std >= 0.15, f"curiosity std {std:.3f} too low"

    def test_all_8_dimensions_vary(self):
        sample = sample_population(LANE_COVE_PROFILE, seed=42)
        dims = ["openness", "conscientiousness", "extraversion", "agreeableness",
                "neuroticism", "curiosity", "routine_adherence", "risk_tolerance"]
        for dim in dims:
            values = [getattr(p.personality, dim) for p in sample]
            std = statistics.stdev(values)
            assert std >= 0.10, f"{dim} std {std:.3f} too low"

    def test_all_values_in_range(self):
        sample = sample_population(LANE_COVE_PROFILE, seed=42)
        for p in sample:
            for dim_name in PersonalityParams.__dataclass_fields__:
                v = getattr(p.personality, dim_name)
                assert 0.0 <= v <= 1.0, f"{dim_name} out of range: {v}"


class TestSeedReproducibility:

    def test_same_seed_same_personality(self):
        a = sample_population(LANE_COVE_PROFILE, seed=7)
        b = sample_population(LANE_COVE_PROFILE, seed=7)
        for pa, pb in zip(a, b):
            assert pa.personality == pb.personality

    def test_different_seed_different_personality(self):
        a = sample_population(LANE_COVE_PROFILE, seed=1)
        b = sample_population(LANE_COVE_PROFILE, seed=2)
        # Should differ at least somewhere
        assert any(pa.personality != pb.personality for pa, pb in zip(a, b))


class TestNarrowDistribution:

    def test_zero_std_produces_constant(self):
        """std=0 → all agents get the mean value."""
        # Build a variant with narrow personality params
        small = PopulationProfile(
            **{
                **LANE_COVE_PROFILE.model_dump(),
                "size": 20,
                "name": "narrow",
                "personality_params": PersonalityParams(
                    curiosity=(0.8, 0.0),  # all agents get 0.8
                ),
            }
        )
        sample = sample_population(small, seed=1)
        assert all(p.personality.curiosity == 0.8 for p in sample)
