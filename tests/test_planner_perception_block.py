"""Tests for Planner.replan accepting perceptual_context kwarg + 【环境】 block.

A1 / realism-perception-loop. Verifies:
- Backwards compat: no perceptual_context → no 【环境】 block
- Provided non-empty view → 【环境】 block appears with view content
- Empty view → block omitted (don't pollute prompt with placeholder text)
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from synthetic_socio_wind_tunnel.agent import (
    AgentProfile, DailyPlan, PlanStep, Planner,
)
from synthetic_socio_wind_tunnel.perception.models import (
    EntitySnapshot,
    ItemSnapshot,
    SubjectiveView,
)


_EMPTY_PLAN_XML = "<plan></plan>"


class _CapturingMockLLM:
    def __init__(self, response: str = _EMPTY_PLAN_XML) -> None:
        self.response = response
        self.last_prompt: str | None = None

    async def generate(self, prompt: str, *, model: str = "", **_: Any) -> str:
        self.last_prompt = prompt
        return self.response


def _profile() -> AgentProfile:
    return AgentProfile(
        agent_id="emma", name="Emma", age=30, occupation="writer",
        household="single", home_location="home",
    )


def _plan() -> DailyPlan:
    return DailyPlan(
        agent_id="emma", date="2026-04-21", current_step_index=1,
        steps=[
            PlanStep(time="7:00", action="move", destination="cafe_a", duration_minutes=30),
            PlanStep(time="7:30", action="stay", duration_minutes=60),
        ],
    )


def _ctx() -> dict:
    return {
        "trigger_event": None,
        "recent_memories": [],
        "current_time": datetime(2026, 4, 21, 8, 0),
    }


def _view_with_5_agents() -> SubjectiveView:
    return SubjectiveView(
        observer_id="emma",
        location_id="cafe_a",
        location_name="Cafe A",
        entity_snapshots=[
            EntitySnapshot(entity_id=f"a_{i}", location_id="cafe_a")
            for i in range(5)
        ],
        item_snapshots=[
            ItemSnapshot(item_id="poster_1", name="社区跑步活动海报"),
        ],
        ambient_sounds=["人声嘈杂"],
    )


def _empty_view() -> SubjectiveView:
    return SubjectiveView(
        observer_id="emma",
        location_id="cafe_a",
        location_name="Cafe A",
    )


class TestBackwardsCompat:

    def test_no_perceptual_context_no_huan_jing_block(self):
        mock = _CapturingMockLLM()
        planner = Planner(mock)
        asyncio.run(planner.replan(_profile(), _plan(), _ctx()))
        assert mock.last_prompt is not None
        assert "【环境】" not in mock.last_prompt, \
            f"未传 perceptual_context 时不该有【环境】block; prompt={mock.last_prompt[:500]!r}"

    def test_existing_blocks_intact(self):
        """B7 + 之前的 prompt 测试不破坏。"""
        mock = _CapturingMockLLM()
        planner = Planner(mock)
        asyncio.run(planner.replan(_profile(), _plan(), _ctx()))
        # 至少【现在】+【接下来计划】总在
        assert "【现在】" in mock.last_prompt
        assert "【接下来计划】" in mock.last_prompt


class TestPerceptualContextProvided:

    def test_view_with_5_agents_appears_in_prompt(self):
        mock = _CapturingMockLLM()
        planner = Planner(mock)
        view = _view_with_5_agents()
        asyncio.run(planner.replan(
            _profile(), _plan(), _ctx(),
            perceptual_context=view,
        ))
        assert "【环境】" in mock.last_prompt
        # 数字 5 出现在【环境】block 里
        env_idx = mock.last_prompt.index("【环境】")
        env_block = mock.last_prompt[env_idx:env_idx + 200]
        assert "5" in env_block
        assert "人" in env_block

    def test_item_content_appears_in_block(self):
        mock = _CapturingMockLLM()
        planner = Planner(mock)
        asyncio.run(planner.replan(
            _profile(), _plan(), _ctx(),
            perceptual_context=_view_with_5_agents(),
        ))
        env_idx = mock.last_prompt.index("【环境】")
        env_block = mock.last_prompt[env_idx:]
        assert "社区跑步活动海报" in env_block

    def test_audible_sounds_appear(self):
        mock = _CapturingMockLLM()
        planner = Planner(mock)
        asyncio.run(planner.replan(
            _profile(), _plan(), _ctx(),
            perceptual_context=_view_with_5_agents(),
        ))
        env_idx = mock.last_prompt.index("【环境】")
        env_block = mock.last_prompt[env_idx:]
        assert "人声嘈杂" in env_block


class TestEmptyView:

    def test_empty_view_omits_block(self):
        """空 view → prose 返空 → 整块省略，不该有【环境】出现。"""
        mock = _CapturingMockLLM()
        planner = Planner(mock)
        asyncio.run(planner.replan(
            _profile(), _plan(), _ctx(),
            perceptual_context=_empty_view(),
        ))
        assert "【环境】" not in mock.last_prompt
