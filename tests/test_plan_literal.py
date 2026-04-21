"""Tests for PlanStep action / social_intent Literal typing."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from synthetic_socio_wind_tunnel.agent import PlanStep


class TestActionLiteral:

    def test_valid_actions(self):
        for a in ("move", "stay", "interact", "explore"):
            step = PlanStep(time="7:00", action=a)
            assert step.action == a

    def test_invalid_action_rejected(self):
        with pytest.raises(ValidationError):
            PlanStep(time="7:00", action="walk")  # type: ignore[arg-type]

    def test_typo_rejected(self):
        # LLM 常见的 typo — "moves" 是最容易出的错
        with pytest.raises(ValidationError):
            PlanStep(time="7:00", action="moves")  # type: ignore[arg-type]

    def test_chinese_rejected(self):
        with pytest.raises(ValidationError):
            PlanStep(time="7:00", action="移动")  # type: ignore[arg-type]


class TestSocialIntentLiteral:

    def test_valid_intents(self):
        for s in ("alone", "open_to_chat", "seeking_company"):
            step = PlanStep(time="7:00", action="move", social_intent=s)
            assert step.social_intent == s

    def test_invalid_intent_rejected(self):
        with pytest.raises(ValidationError):
            PlanStep(time="7:00", action="move",
                     social_intent="social")  # type: ignore[arg-type]


class TestPlannerParseCatchesLiteral:
    """Simulate Planner's _parse_plan fallback when LLM emits invalid action."""

    def test_parse_plan_returns_empty_on_invalid_action(self):
        from synthetic_socio_wind_tunnel.agent.planner import Planner

        # LLM 吐出无效 action
        bad_json = '[{"time": "7:00", "action": "walk", "duration_minutes": 30}]'
        steps = Planner._parse_plan(bad_json)
        # Phase 1 behavior: on any parse error, return empty list (fallback)
        assert steps == []
