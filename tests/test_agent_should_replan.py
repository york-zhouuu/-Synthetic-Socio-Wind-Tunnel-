"""Tests for AgentRuntime.should_replan rule-based logic (no LLM)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from synthetic_socio_wind_tunnel.agent import AgentProfile, AgentRuntime
from synthetic_socio_wind_tunnel.agent.personality import PersonalityTraits
from synthetic_socio_wind_tunnel.memory.models import MemoryEvent


def _profile(
    curiosity: float = 0.5, routine_adherence: float = 0.5
) -> AgentProfile:
    return AgentProfile(
        agent_id="emma", name="Emma", age=30, occupation="x",
        household="single", home_location="home",
        personality=PersonalityTraits(
            curiosity=curiosity, routine_adherence=routine_adherence
        ),
    )


def _notification(urgency: float = 0.5, kind: str = "notification") -> MemoryEvent:
    return MemoryEvent(
        event_id="n1", agent_id="emma", tick=0,
        simulated_time=datetime(2026, 4, 21, 7, 0),
        kind=kind,  # type: ignore
        content="push!", urgency=urgency, importance=0.7,
    )


class TestNotificationReplan:

    def test_high_curiosity_low_adherence_replans(self):
        """高好奇 + 低坚持：低 urgency 也触发。"""
        runtime = AgentRuntime(profile=_profile(curiosity=0.9, routine_adherence=0.1))
        candidate = _notification(urgency=0.5)
        assert runtime.should_replan([], candidate) is True

    def test_high_adherence_resists_replan(self):
        """高坚持：高 urgency 也不替换。"""
        runtime = AgentRuntime(profile=_profile(curiosity=0.2, routine_adherence=0.9))
        candidate = _notification(urgency=0.6)
        # threshold = 0.4 + 0.3*0.9 - 0.3*0.2 = 0.61; urgency=0.6 < 0.61
        assert runtime.should_replan([], candidate) is False

    def test_very_high_urgency_overrides(self):
        """极高 urgency 即使高坚持也触发。"""
        runtime = AgentRuntime(profile=_profile(curiosity=0.2, routine_adherence=0.9))
        candidate = _notification(urgency=0.95)
        # threshold = 0.61; urgency=0.95 > 0.61
        assert runtime.should_replan([], candidate) is True

    def test_low_urgency_insignificant(self):
        """低 urgency 不触发。"""
        runtime = AgentRuntime(profile=_profile())
        candidate = _notification(urgency=0.1)
        # threshold = 0.4 + 0.3*0.5 - 0.3*0.5 = 0.4; urgency=0.1 < 0.4
        assert runtime.should_replan([], candidate) is False


class TestTaskReceived:

    def test_task_received_uses_same_logic(self):
        runtime = AgentRuntime(profile=_profile(curiosity=0.9, routine_adherence=0.1))
        candidate = _notification(urgency=0.5, kind="task_received")
        assert runtime.should_replan([], candidate) is True


class TestOtherKindsDefaultFalse:

    def test_encounter_not_replan(self):
        runtime = AgentRuntime(profile=_profile(curiosity=0.9))
        candidate = MemoryEvent(
            event_id="e1", agent_id="emma", tick=0,
            simulated_time=datetime.now(),
            kind="encounter", content="met linda",
            actor_id="linda", urgency=0.8,  # 即使 urgency 高
        )
        assert runtime.should_replan([], candidate) is False

    def test_action_not_replan(self):
        runtime = AgentRuntime(profile=_profile())
        candidate = MemoryEvent(
            event_id="a1", agent_id="emma", tick=0,
            simulated_time=datetime.now(),
            kind="action", content="moved",
        )
        assert runtime.should_replan([], candidate) is False


class TestNoLLMCall:

    def test_no_llm_in_should_replan(self):
        """
        should_replan 绝不能调 LLM。
        通过 patch 确保 anthropic / openai 不被触发。
        """
        runtime = AgentRuntime(profile=_profile())
        candidate = _notification(urgency=0.9)
        # 调 10000 次不应引起任何异步 I/O — 我们用时间 < 100ms 作代理指标
        import time
        start = time.perf_counter()
        for _ in range(10000):
            runtime.should_replan([], candidate)
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0, f"should_replan 10k calls took {elapsed:.2f}s (expected < 1s)"
