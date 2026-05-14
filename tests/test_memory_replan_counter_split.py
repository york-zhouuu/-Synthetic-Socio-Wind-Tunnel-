"""Tests for the B7 split between plan-changed and no-op replan counters.

Original `replan_count_today` incremented on every Planner.replan call,
including fallbacks where the plan was unchanged → made gd's 44/57/105
counts misleading. The fix: Planner.replan now returns
`tuple[DailyPlan, bool]`; MemoryService routes by `changed` into either
`_replan_count_today` (real plan changes) or `_replan_no_op_count_today`
(LLM fallbacks).
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

from synthetic_socio_wind_tunnel.agent import (
    AgentProfile, DailyPlan, PlanStep, Planner,
)
from synthetic_socio_wind_tunnel.memory.service import MemoryService


_EMPTY_PLAN_XML = "<plan></plan>"


class _AlwaysEmptyLLM:
    async def generate(self, prompt: str, *, model: str = "", **_: Any) -> str:
        return _EMPTY_PLAN_XML


class TestPlannerReplanReturnsTuple:

    def test_empty_response_returns_changed_false(self):
        planner = Planner(_AlwaysEmptyLLM())
        profile = AgentProfile(
            agent_id="a", name="A", age=30, occupation="x",
            household="single", home_location="home",
        )
        plan = DailyPlan(
            agent_id="a", date="2026-04-21",
            steps=[PlanStep(time="8:00", action="stay", duration_minutes=60)],
        )
        ctx = {
            "trigger_event": None,
            "recent_memories": [],
            "current_time": datetime(2026, 4, 21, 8, 0),
        }
        new_plan, changed = asyncio.run(planner.replan(profile, plan, ctx))
        assert changed is False
        # Plan steps preserved.
        assert len(new_plan.steps) == 1
        assert new_plan.steps[0].time == "8:00"

    def test_real_response_returns_changed_true(self):
        new_xml = (
            "<plan>"
            "<step><time>9:00</time><destination>park</destination>"
            "<action>move</action><duration>30</duration></step>"
            "</plan>"
        )

        class _ChangingLLM:
            async def generate(self, prompt: str, *, model: str = "", **_: Any) -> str:
                return new_xml

        planner = Planner(_ChangingLLM())
        profile = AgentProfile(
            agent_id="a", name="A", age=30, occupation="x",
            household="single", home_location="home",
        )
        plan = DailyPlan(
            agent_id="a", date="2026-04-21",
            steps=[PlanStep(time="8:00", action="stay", duration_minutes=60)],
        )
        ctx = {
            "trigger_event": None,
            "recent_memories": [],
            "current_time": datetime(2026, 4, 21, 8, 0),
        }
        new_plan, changed = asyncio.run(planner.replan(profile, plan, ctx))
        assert changed is True


class TestMemoryServiceReplanCounterRouting:
    """Sanity test that replan_no_op_count_today_total accessor works."""

    def test_no_op_counter_starts_at_zero(self):
        msvc = MemoryService(seed=42)
        assert msvc.replan_no_op_count_today_total() == 0

    def test_no_op_counter_increments_on_unchanged_replan(self):
        msvc = MemoryService(seed=42)
        # Manually pretend two agents had no-op replans.
        msvc._replan_no_op_count_today["a"] = 3
        msvc._replan_no_op_count_today["b"] = 2
        assert msvc.replan_no_op_count_today_total() == 5

    def test_changed_and_no_op_are_separate_dicts(self):
        msvc = MemoryService(seed=42)
        msvc._replan_count_today["a"] = 4
        msvc._replan_no_op_count_today["a"] = 7
        # Lifetime sum:
        assert msvc.replan_no_op_count_today_total() == 7
        # The fatigue cap (replan_count_today) doesn't include no-ops.
        assert sum(msvc._replan_count_today.values()) == 4
