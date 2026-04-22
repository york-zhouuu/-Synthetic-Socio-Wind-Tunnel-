"""Tests for CatalystSeedingVariant (D — H_structure)."""

from __future__ import annotations

from random import Random

from synthetic_socio_wind_tunnel.agent import AgentProfile
from synthetic_socio_wind_tunnel.agent.personality import PersonalityTraits
from synthetic_socio_wind_tunnel.policy_hack import CatalystSeedingVariant


def _profile(agent_id: str, extraversion: float = 0.5) -> AgentProfile:
    return AgentProfile(
        agent_id=agent_id, name=agent_id, age=30, occupation="x",
        household="single", home_location="a",
        personality=PersonalityTraits(extraversion=extraversion),
    )


class TestCatalystSeeding:
    def test_default_5_percent_of_100(self):
        v = CatalystSeedingVariant()
        profiles = [_profile(f"a{i:03d}") for i in range(100)]
        new = v.apply_population(profiles, Random(0))
        catalyst_count = sum(
            1 for p in new
            if p.personality.extraversion == v.catalyst_personality.extraversion
        )
        assert catalyst_count == 5

    def test_ceil_for_50_agents(self):
        v = CatalystSeedingVariant(catalyst_ratio=0.05)
        profiles = [_profile(f"a{i:02d}") for i in range(50)]
        new = v.apply_population(profiles, Random(0))
        catalyst_count = sum(
            1 for p in new
            if p.personality.extraversion == v.catalyst_personality.extraversion
        )
        # ceil(50 * 0.05) = ceil(2.5) = 3
        assert catalyst_count == 3

    def test_other_fields_unchanged(self):
        v = CatalystSeedingVariant(catalyst_ratio=0.50)
        profiles = [
            _profile(f"a{i}") for i in range(4)
        ]
        # Assign distinct homes to verify preservation
        profiles = [
            p.model_copy(update={"home_location": f"home_{i}", "age": 20 + i})
            for i, p in enumerate(profiles)
        ]
        new = v.apply_population(profiles, Random(0))
        # Homes and ages preserved regardless of catalyst status
        for orig, transformed in zip(profiles, new):
            assert transformed.agent_id == orig.agent_id
            assert transformed.home_location == orig.home_location
            assert transformed.age == orig.age

    def test_determinism_same_seed(self):
        v = CatalystSeedingVariant(catalyst_ratio=0.20)
        profiles = [_profile(f"a{i:02d}") for i in range(20)]
        new1 = v.apply_population(profiles, Random(42))
        new2 = v.apply_population(profiles, Random(42))
        idx1 = [i for i, p in enumerate(new1)
                if p.personality.extraversion == v.catalyst_personality.extraversion]
        idx2 = [i for i, p in enumerate(new2)
                if p.personality.extraversion == v.catalyst_personality.extraversion]
        assert idx1 == idx2

    def test_empty_profiles(self):
        v = CatalystSeedingVariant()
        out = v.apply_population([], Random(0))
        assert out == []

    def test_apply_day_start_noop(self):
        v = CatalystSeedingVariant()
        # Should not raise even with fabricated minimal ctx
        from datetime import date
        from synthetic_socio_wind_tunnel.ledger import Ledger
        from synthetic_socio_wind_tunnel.policy_hack import VariantContext
        ledger = Ledger()
        from datetime import datetime
        ledger.current_time = datetime(2026, 4, 22)
        ctx = VariantContext(
            day_index=4, simulated_date=date(2026, 4, 22),
            phase="intervention", ledger=ledger,
            attention_service=None, runtimes=(), rng=Random(0), seed=0,
        )
        v.apply_day_start(ctx)  # no-op
