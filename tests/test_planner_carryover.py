"""Tests for Planner.generate_daily_plan carryover parameter."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from synthetic_socio_wind_tunnel.agent import AgentProfile, Planner
from synthetic_socio_wind_tunnel.memory import CarryoverContext, MemoryEvent
from synthetic_socio_wind_tunnel.memory.models import DailySummary


class CapturingLLM:
    """Captures prompt passed to generate(); returns simple JSON response."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def generate(self, prompt: str, *, model: str = "", **kwargs) -> str:
        self.prompts.append(prompt)
        return '[{"time":"8:00","action":"stay","destination":null,"activity":"x","duration_minutes":30,"reason":"","social_intent":"alone"}]'


@pytest.fixture
def profile() -> AgentProfile:
    return AgentProfile(
        agent_id="emma", name="Emma", age=30, occupation="x",
        household="single", home_location="home",
    )


class TestGenerateDailyPlanCarryover:
    def test_without_carryover_backward_compat(self, profile):
        """carryover=None → prompt 不含任何 carryover section。"""
        llm = CapturingLLM()
        planner = Planner(llm)
        plan = asyncio.run(planner.generate_daily_plan(
            profile, date="2026-04-22",
        ))
        assert len(llm.prompts) == 1
        p = llm.prompts[0]
        assert "昨日经历摘要" not in p
        assert "近 3 日反思" not in p
        assert "未完成任务锚点" not in p
        assert len(plan.steps) == 1

    def test_with_carryover_adds_sections(self, profile):
        """carryover 非空时 prompt 包含三段。"""
        llm = CapturingLLM()
        planner = Planner(llm)

        yesterday = DailySummary(
            agent_id="emma", date="2026-04-21",
            summary_text="emma went to cafe and met a stranger",
        )
        reflections = (
            DailySummary(agent_id="emma", date="2026-04-19",
                         summary_text="walked the dog"),
            DailySummary(agent_id="emma", date="2026-04-20",
                         summary_text="stayed home"),
        )
        tasks = (
            MemoryEvent(
                event_id="t1", agent_id="emma", tick=10,
                simulated_time=datetime(2026, 4, 21, 9, 0, 0),
                kind="task_received", content="find the lost cat",
                importance=0.8, day_index=1,
            ),
        )

        ctx = CarryoverContext(
            yesterday_summary=yesterday,
            recent_reflections=reflections,
            pending_task_anchors=tasks,
        )
        asyncio.run(planner.generate_daily_plan(
            profile, date="2026-04-22", carryover=ctx,
        ))
        p = llm.prompts[0]
        assert "昨日经历摘要" in p
        assert "近 3 日反思" in p
        assert "未完成任务锚点" in p
        assert "met a stranger" in p
        assert "find the lost cat" in p

    def test_carryover_truncation_at_long_summary(self, profile):
        """yesterday summary 过长 → prompt 被截断到 300 字符。"""
        llm = CapturingLLM()
        planner = Planner(llm)

        # Create a summary_text longer than 1500 chars to trigger truncation
        long_text = "很多事" * 1000  # 3000 chars
        yesterday = DailySummary(
            agent_id="emma", date="2026-04-21", summary_text=long_text,
        )
        ctx = CarryoverContext(yesterday_summary=yesterday)

        asyncio.run(planner.generate_daily_plan(
            profile, date="2026-04-22", carryover=ctx,
        ))
        p = llm.prompts[0]
        # prompt 应包含截断标记
        assert "…" in p
        # 而且整体 carryover 段应远小于 1500 chars
        # （不是精确测量，而是 sanity check）
        # 找到 "昨日经历摘要" 到 "请生成你今天的日程计划" 之间的子串
        start = p.find("【昨日经历摘要】")
        end = p.find("请生成你今天的日程计划")
        assert start >= 0 and end > start
        carryover_block = p[start:end]
        assert len(carryover_block) < 2000, f"carryover block too long: {len(carryover_block)}"

    def test_empty_carryover_yields_no_sections(self, profile):
        """CarryoverContext() 全空 → prompt 不含任何 carryover section。"""
        llm = CapturingLLM()
        planner = Planner(llm)
        ctx = CarryoverContext()
        asyncio.run(planner.generate_daily_plan(
            profile, date="2026-04-22", carryover=ctx,
        ))
        p = llm.prompts[0]
        assert "昨日经历摘要" not in p
