"""Tests for Planner.replan (async)."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from synthetic_socio_wind_tunnel.agent import (
    AgentProfile,
    DailyPlan,
    Planner,
    PlanStep,
)
from synthetic_socio_wind_tunnel.memory.models import MemoryEvent


_EMPTY_PLAN_XML = "<plan></plan>"


class MockLLM:
    """Configurable mock LLM client."""

    def __init__(
        self,
        response: str = _EMPTY_PLAN_XML,
        raise_exc: Exception | None = None,
    ):
        self.response = response
        self.raise_exc = raise_exc
        self.calls: list[tuple[str, str]] = []

    async def generate(self, prompt: str, *, model: str = "", **kwargs) -> str:
        self.calls.append((prompt, model))
        if self.raise_exc:
            raise self.raise_exc
        return self.response


def _profile() -> AgentProfile:
    return AgentProfile(
        agent_id="emma", name="Emma", age=30, occupation="writer",
        household="single", home_location="home_a",
    )


def _plan() -> DailyPlan:
    return DailyPlan(
        agent_id="emma", date="2026-04-21", current_step_index=2,
        steps=[
            PlanStep(time="7:00", action="move", destination="cafe_a",
                     duration_minutes=30),
            PlanStep(time="7:30", action="stay", activity="coffee",
                     duration_minutes=60),
            PlanStep(time="8:30", action="move", destination="office",
                     duration_minutes=60),
            PlanStep(time="9:30", action="stay", activity="work",
                     duration_minutes=180),
        ],
    )


def _trigger() -> MemoryEvent:
    return MemoryEvent(
        event_id="n1", agent_id="emma", tick=5,
        simulated_time=datetime(2026, 4, 21, 8, 30),
        kind="notification", content="Sunset Bar tasting now!",
        urgency=0.9,
    )


class TestReplanSuccess:

    def test_returns_new_future_steps(self):
        new_steps_xml = (
            "<plan>"
            "<step><time>8:30</time><destination>sunset_bar</destination>"
            "<action>visit sunset bar</action><duration>60</duration>"
            "<activity>tasting</activity><social>open_to_chat</social></step>"
            "<step><time>9:30</time><action>back_to_work</action>"
            "<duration>180</duration><activity>back_to_work</activity>"
            "<social>alone</social></step>"
            "</plan>"
        )
        planner = Planner(MockLLM(response=new_steps_xml))
        ctx = {
            "trigger_event": _trigger(),
            "recent_memories": [],
            "current_time": datetime(2026, 4, 21, 8, 30),
        }
        new_plan, _changed = asyncio.run(planner.replan(_profile(), _plan(), ctx))

        # 保留前 2 个 step (current_step_index)，替换后 2 个
        assert len(new_plan.steps) == 4
        assert new_plan.steps[0].destination == "cafe_a"  # 保留
        assert new_plan.steps[2].destination == "sunset_bar"  # 替换
        # visit → move（同义词映射）
        assert new_plan.steps[2].action == "move"

    def test_d2_step_time_before_current_time_rewritten(self):
        """D.2 修复仍 work：XML step.time 早于 current_time → 重写。"""
        # 8:00 早于 current=8:30 → 应被改为 8:31
        xml = (
            "<plan>"
            "<step><time>8:00</time><destination>sunset_bar</destination>"
            "<action>move</action><duration>60</duration></step>"
            "</plan>"
        )
        planner = Planner(MockLLM(response=xml))
        ctx = {
            "trigger_event": _trigger(),
            "recent_memories": [],
            "current_time": datetime(2026, 4, 21, 8, 30),
        }
        new_plan, _changed = asyncio.run(planner.replan(_profile(), _plan(), ctx))
        # current_step_index=2 保留前 2 + 1 个新 step = 3
        assert len(new_plan.steps) == 3
        assert new_plan.steps[2].time == "8:31"

    def test_1_llm_call(self):
        mock = MockLLM(response=_EMPTY_PLAN_XML)
        planner = Planner(mock)
        ctx = {
            "trigger_event": _trigger(),
            "recent_memories": [],
            "current_time": datetime.now(),
        }
        asyncio.run(planner.replan(_profile(), _plan(), ctx))  # tuple discarded
        # LLM returned empty plan → fallback; call count 仍为 1
        assert len(mock.calls) == 1


class TestReplanFallback:

    def test_llm_exception_returns_original(self):
        planner = Planner(MockLLM(raise_exc=RuntimeError("LLM down")))
        original = _plan()
        ctx = {
            "trigger_event": _trigger(),
            "recent_memories": [],
            "current_time": datetime.now(),
        }
        new_plan, _changed = asyncio.run(planner.replan(_profile(), original, ctx))
        assert len(new_plan.steps) == len(original.steps)

    def test_empty_llm_response_returns_original(self):
        planner = Planner(MockLLM(response="not xml"))
        original = _plan()
        ctx = {
            "trigger_event": _trigger(),
            "recent_memories": [],
            "current_time": datetime.now(),
        }
        new_plan, _changed = asyncio.run(planner.replan(_profile(), original, ctx))
        assert new_plan.steps == original.steps


class TestReplanPrompt:

    def test_prompt_contains_trigger_event(self):
        # realism-attention-rebalance：push 进 【手机】 block。kind 标签
        # 不再放入 prompt（避免暗示"事件类型 = 必须响应"）。
        mock = MockLLM(response=_EMPTY_PLAN_XML)
        planner = Planner(mock)
        trigger = _trigger()
        ctx = {
            "trigger_event": trigger,
            "recent_memories": [],
            "current_time": datetime.now(),
        }
        asyncio.run(planner.replan(_profile(), _plan(), ctx))  # tuple discarded
        prompt = mock.calls[0][0]
        assert trigger.content in prompt
        assert "【手机】" in prompt

    def test_prompt_contains_recent_memories(self):
        mock = MockLLM(response=_EMPTY_PLAN_XML)
        planner = Planner(mock)
        memories = [
            MemoryEvent(
                event_id="m1", agent_id="emma", tick=3,
                simulated_time=datetime.now(),
                kind="action", content="had coffee at cafe_a",
            ),
        ]
        ctx = {
            "trigger_event": _trigger(),
            "recent_memories": memories,
            "current_time": datetime.now(),
        }
        asyncio.run(planner.replan(_profile(), _plan(), ctx))  # tuple discarded
        prompt = mock.calls[0][0]
        assert "coffee" in prompt

    def test_prompt_asks_for_xml(self):
        mock = MockLLM(response=_EMPTY_PLAN_XML)
        planner = Planner(mock)
        ctx = {
            "trigger_event": _trigger(),
            "recent_memories": [],
            "current_time": datetime.now(),
        }
        asyncio.run(planner.replan(_profile(), _plan(), ctx))  # tuple discarded
        prompt = mock.calls[0][0]
        assert "<plan>" in prompt
        assert "<step>" in prompt


class TestReplanNoPlan:

    def test_no_current_plan_returns_empty(self):
        planner = Planner(MockLLM(response=_EMPTY_PLAN_XML))
        ctx = {"trigger_event": _trigger(), "recent_memories": [],
               "current_time": datetime.now()}
        new_plan, _changed = asyncio.run(planner.replan(_profile(), None, ctx))
        assert new_plan.steps == []
