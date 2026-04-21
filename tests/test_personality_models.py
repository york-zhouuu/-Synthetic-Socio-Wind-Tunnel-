"""Tests for typed PersonalityTraits / Skills / EmotionalState."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from synthetic_socio_wind_tunnel.agent.personality import (
    EmotionalState,
    PersonalityTraits,
    Skills,
)


class TestPersonalityTraits:

    def test_defaults_half(self):
        t = PersonalityTraits()
        assert t.openness == 0.5
        assert t.conscientiousness == 0.5
        assert t.extraversion == 0.5
        assert t.agreeableness == 0.5
        assert t.neuroticism == 0.5
        assert t.curiosity == 0.5
        assert t.routine_adherence == 0.5
        assert t.risk_tolerance == 0.5

    def test_construct_with_values(self):
        t = PersonalityTraits(curiosity=0.9, routine_adherence=0.2)
        assert t.curiosity == 0.9
        assert t.routine_adherence == 0.2
        assert t.openness == 0.5  # default

    def test_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            PersonalityTraits(curiosity=1.5)
        with pytest.raises(ValidationError):
            PersonalityTraits(openness=-0.1)

    def test_frozen(self):
        t = PersonalityTraits()
        with pytest.raises(ValidationError):
            t.curiosity = 0.9

    def test_hashable(self):
        a = PersonalityTraits(curiosity=0.7)
        b = PersonalityTraits(curiosity=0.7)
        assert hash(a) == hash(b)
        assert {a, b} == {a}


class TestSkills:

    def test_defaults_half(self):
        s = Skills()
        assert s.perception == 0.5
        assert s.investigation == 0.5
        assert s.stealth == 0.5

    def test_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            Skills(investigation=2.0)

    def test_frozen(self):
        s = Skills()
        with pytest.raises(ValidationError):
            s.perception = 0.9


class TestEmotionalState:

    def test_defaults_zero(self):
        e = EmotionalState()
        assert e.guilt == 0.0
        assert e.anxiety == 0.0
        assert e.curiosity == 0.0
        assert e.fear == 0.0

    def test_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            EmotionalState(guilt=1.2)

    def test_frozen(self):
        e = EmotionalState(guilt=0.5)
        with pytest.raises(ValidationError):
            e.guilt = 0.8

    def test_curiosity_distinct_from_personality(self):
        """EmotionalState.curiosity (state) vs PersonalityTraits.curiosity (trait)"""
        t = PersonalityTraits(curiosity=0.9)
        e = EmotionalState(curiosity=0.1)
        # Both coexist; they represent different concepts
        assert t.curiosity == 0.9
        assert e.curiosity == 0.1
