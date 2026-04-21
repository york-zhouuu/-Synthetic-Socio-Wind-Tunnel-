"""Tests for AgentProfile typed personality access."""

from __future__ import annotations

import pytest

from synthetic_socio_wind_tunnel.agent import AgentProfile
from synthetic_socio_wind_tunnel.agent.personality import PersonalityTraits


class TestTypedPersonality:

    def test_default_personality(self):
        profile = AgentProfile(
            agent_id="x", name="X", age=30, occupation="y",
            household="single", home_location="home",
        )
        assert profile.personality.curiosity == 0.5
        assert profile.personality.routine_adherence == 0.5

    def test_construct_with_traits(self):
        traits = PersonalityTraits(curiosity=0.9, routine_adherence=0.1)
        profile = AgentProfile(
            agent_id="x", name="X", age=30, occupation="y",
            household="single", home_location="home",
            personality=traits,
        )
        assert profile.personality.curiosity == 0.9

    def test_trait_method_removed(self):
        profile = AgentProfile(
            agent_id="x", name="X", age=30, occupation="y",
            household="single", home_location="home",
        )
        with pytest.raises(AttributeError):
            profile.trait("curiosity")  # type: ignore[attr-defined]

    def test_personality_traits_field_removed(self):
        # Old `personality_traits=` kwarg should be rejected (Pydantic strict)
        with pytest.raises(Exception):  # ValidationError
            AgentProfile(
                agent_id="x", name="X", age=30, occupation="y",
                household="single", home_location="home",
                personality_traits={"curiosity": 0.9},  # type: ignore
            )


class TestHouseholdLiteral:

    def test_valid_household(self):
        for h in ("single", "couple", "family_with_kids"):
            profile = AgentProfile(
                agent_id="x", name="X", age=30, occupation="y",
                household=h, home_location="h",
            )
            assert profile.household == h

    def test_invalid_household_rejected(self):
        with pytest.raises(Exception):
            AgentProfile(
                agent_id="x", name="X", age=30, occupation="y",
                household="tribe",  # type: ignore
                home_location="h",
            )
