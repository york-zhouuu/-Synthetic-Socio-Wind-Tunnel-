"""Tests for AgentProfile structural-dimension extension (realign-to-social-thesis)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from synthetic_socio_wind_tunnel.agent import AgentProfile
from synthetic_socio_wind_tunnel.attention import DigitalProfile


def _base_kwargs() -> dict:
    return dict(
        agent_id="emma",
        name="Emma",
        age=30,
        occupation="writer",
        household="single",
        home_location="apt_a_3_b",
    )


class TestBackwardCompatibility:

    def test_old_construct_works(self):
        profile = AgentProfile(**_base_kwargs())
        assert profile.ethnicity_group is None
        assert profile.housing_tenure is None
        assert profile.income_tier is None
        assert profile.work_mode is None
        assert profile.migration_tenure_years is None
        # digital defaults to empty DigitalProfile, not None
        assert isinstance(profile.digital, DigitalProfile)
        assert profile.digital.feed_bias == "global"

    def test_frozen_still_enforced(self):
        profile = AgentProfile(**_base_kwargs())
        with pytest.raises(ValidationError):
            profile.age = 50


class TestStructuralFields:

    def test_all_fields_assignable(self):
        profile = AgentProfile(
            **_base_kwargs(),
            ethnicity_group="AU-migrant-1gen-asia",
            migration_tenure_years=4.5,
            housing_tenure="renter",
            income_tier="mid",
            work_mode="remote",
            digital=DigitalProfile(
                daily_screen_hours=5.0,
                feed_bias="mixed",
                notification_responsiveness=0.8,
            ),
        )
        assert profile.ethnicity_group == "AU-migrant-1gen-asia"
        assert profile.migration_tenure_years == 4.5
        assert profile.housing_tenure == "renter"
        assert profile.income_tier == "mid"
        assert profile.work_mode == "remote"
        assert profile.digital.daily_screen_hours == 5.0

    def test_negative_tenure_rejected(self):
        with pytest.raises(ValidationError):
            AgentProfile(**_base_kwargs(), migration_tenure_years=-2.0)

    def test_invalid_housing_rejected(self):
        with pytest.raises(ValidationError):
            AgentProfile(**_base_kwargs(), housing_tenure="squatter")

    def test_invalid_income_rejected(self):
        with pytest.raises(ValidationError):
            AgentProfile(**_base_kwargs(), income_tier="astronomical")

    def test_invalid_work_mode_rejected(self):
        with pytest.raises(ValidationError):
            AgentProfile(**_base_kwargs(), work_mode="freelance")

    def test_ethnicity_is_free_string(self):
        """ethnicity_group uses region codes but model itself doesn't enforce."""
        profile = AgentProfile(**_base_kwargs(), ethnicity_group="AU-born")
        assert profile.ethnicity_group == "AU-born"


class TestDigitalIntegration:

    def test_digital_defaults_are_empty_profile(self):
        profile = AgentProfile(**_base_kwargs())
        assert profile.digital == DigitalProfile()

    def test_digital_nested_frozen(self):
        profile = AgentProfile(
            **_base_kwargs(),
            digital=DigitalProfile(daily_screen_hours=6.0),
        )
        assert profile.digital.daily_screen_hours == 6.0
        with pytest.raises(ValidationError):
            profile.digital.daily_screen_hours = 1.0
