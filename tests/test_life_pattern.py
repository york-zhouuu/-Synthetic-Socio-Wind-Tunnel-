"""Tests for LifePattern + sampling (agent-realistic-routine)."""

from __future__ import annotations

from collections import Counter

from synthetic_socio_wind_tunnel.agent import (
    LANE_COVE_PROFILE,
    LifePattern,
    sample_population,
)


_DESTS = tuple(f"loc_{i}" for i in range(20))


class TestLifePatternModel:

    def test_default_minutes_in_range(self):
        lp = LifePattern()
        assert 0 <= lp.morning_commute_minute <= 59
        assert 0 <= lp.evening_return_minute <= 59

    def test_default_destinations_none(self):
        lp = LifePattern()
        assert lp.preferred_cafe is None
        assert lp.weekend_outing_destination is None

    def test_frozen(self):
        lp = LifePattern(preferred_cafe="cafe_a")
        try:
            lp.preferred_cafe = "cafe_b"  # type: ignore
            assert False, "should be frozen"
        except (AttributeError, ValueError, TypeError):
            pass


class TestSamplePopulationLifePattern:

    def test_every_agent_gets_life_pattern(self):
        agents = sample_population(LANE_COVE_PROFILE, seed=42, home_locations=_DESTS)
        assert all(a.life_pattern is not None for a in agents)

    def test_seed_reproducibility(self):
        a = sample_population(LANE_COVE_PROFILE, seed=42, home_locations=_DESTS)
        b = sample_population(LANE_COVE_PROFILE, seed=42, home_locations=_DESTS)
        for x, y in zip(a, b):
            assert x.life_pattern.preferred_cafe == y.life_pattern.preferred_cafe
            assert x.life_pattern.morning_commute_minute == y.life_pattern.morning_commute_minute

    def test_different_seed_diverges(self):
        a = sample_population(LANE_COVE_PROFILE, seed=42, home_locations=_DESTS)
        b = sample_population(LANE_COVE_PROFILE, seed=99, home_locations=_DESTS)
        cafes_a = [agent.life_pattern.preferred_cafe for agent in a]
        cafes_b = [agent.life_pattern.preferred_cafe for agent in b]
        assert cafes_a != cafes_b  # very high prob of difference at n=1000

    def test_morning_commute_distribution_centered(self):
        agents = sample_population(LANE_COVE_PROFILE, seed=42, home_locations=_DESTS)
        minutes = [a.life_pattern.morning_commute_minute for a in agents]
        avg = sum(minutes) / len(minutes)
        # Gaussian mean=30, std=12; sample mean should land near 30
        assert 22 < avg < 38, f"avg morning_commute_minute {avg} far from 30"

    def test_preferred_destinations_in_pool(self):
        agents = sample_population(LANE_COVE_PROFILE, seed=42, home_locations=_DESTS)
        for a in agents[:20]:
            lp = a.life_pattern
            for field in ("preferred_cafe", "preferred_leisure_park",
                          "preferred_errand_destination", "weekend_outing_destination"):
                v = getattr(lp, field)
                if v is not None:
                    assert v in _DESTS, f"{field}={v} not in destinations pool"

    def test_no_destinations_yields_none_fields(self):
        agents = sample_population(LANE_COVE_PROFILE, seed=42)  # no home_locations
        for a in agents[:5]:
            lp = a.life_pattern
            assert lp is not None
            # Without pool, time fields populate; destinations stay None
            assert lp.preferred_cafe is None
            assert lp.weekend_outing_destination is None
            assert 0 <= lp.morning_commute_minute <= 59


class TestLifePatternBackwardCompat:

    def test_old_profile_construction_still_works(self):
        from synthetic_socio_wind_tunnel.agent import AgentProfile
        profile = AgentProfile(
            agent_id="x", name="X", age=30, occupation="x",
            household="single", home_location="home",
        )
        assert profile.life_pattern is None  # default
