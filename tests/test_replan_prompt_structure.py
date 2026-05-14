"""Replan prompt 对称性测试（realism-attention-rebalance）。

断言 _build_replan_prompt 装配的 prompt 满足：
- push 不被语言学特殊化为"打断者"
- 6 个 context block 用统一标记（数据完整时）
- 空数据 block 整块省略
"""

from __future__ import annotations

from datetime import datetime

from synthetic_socio_wind_tunnel.agent import (
    AgentProfile, NearbyAgent,
)
from synthetic_socio_wind_tunnel.agent.personality import PersonalityTraits
from synthetic_socio_wind_tunnel.agent.planner import (
    DailyPlan, PlanStep, _build_replan_prompt,
)
from synthetic_socio_wind_tunnel.memory.models import MemoryEvent


def _profile() -> AgentProfile:
    return AgentProfile(
        agent_id="emma", name="Emma", age=30, occupation="x",
        household="single", home_location="home",
        personality=PersonalityTraits(),
    )


def _plan() -> DailyPlan:
    return DailyPlan(
        agent_id="emma", date="2026-04-29",
        steps=[
            PlanStep(time="7:00", action="move", destination="cafe",
                     duration_minutes=30, activity="get coffee",
                     social_intent="alone"),
            PlanStep(time="7:30", action="move", destination="office",
                     duration_minutes=480, activity="work",
                     social_intent="alone"),
        ],
    )


def _push(content: str = "本街正在举办市集") -> MemoryEvent:
    return MemoryEvent(
        event_id="n1", agent_id="emma", tick=10,
        simulated_time=datetime(2026, 4, 29, 8, 0),
        kind="notification", content=content, urgency=0.6, importance=0.5,
    )


# ---------------------------------------------------------------------------
# 1. 措辞层：push 不被特殊化为"打断者"
# ---------------------------------------------------------------------------


_BANNED_WORDS = ["打断", "interrupt", "interrupting", "中断", "紧急"]


class TestNoInterruptLanguage:

    def test_no_banned_words_full_ctx(self):
        prompt = _build_replan_prompt(
            profile=_profile(),
            current_plan=_plan(),
            trigger_event=_push(),
            recent_memories=[],
            current_time=datetime(2026, 4, 29, 8, 0),
            current_step=_plan().steps[0],
            current_location_kind="cafe",
            nearby_agents=[NearbyAgent(is_familiar=True)],
        )
        for word in _BANNED_WORDS:
            assert word not in prompt, f"banned word found: {word!r}"

    def test_no_banned_words_minimal_ctx(self):
        """旧 caller schema（只有 trigger / memories / time）也不能含禁用词。"""
        prompt = _build_replan_prompt(
            profile=_profile(),
            current_plan=_plan(),
            trigger_event=_push(),
            recent_memories=[],
            current_time=datetime(2026, 4, 29, 8, 0),
        )
        for word in _BANNED_WORDS:
            assert word not in prompt, f"banned word found: {word!r}"


# ---------------------------------------------------------------------------
# 2. 结构层：六个 block 标记（数据完整时同时出现）
# ---------------------------------------------------------------------------


_REQUIRED_BLOCKS = ["【现在】", "【正在做】", "【周围】", "【最近发生】",
                    "【手机】", "【接下来计划】"]


class TestSymmetricBlocks:

    def test_all_six_blocks_when_complete(self):
        prompt = _build_replan_prompt(
            profile=_profile(),
            current_plan=_plan(),
            trigger_event=_push(),
            recent_memories=[
                MemoryEvent(
                    event_id="m1", agent_id="emma", tick=8,
                    simulated_time=datetime(2026, 4, 29, 7, 50),
                    kind="action", content="walked past library",
                ),
            ],
            current_time=datetime(2026, 4, 29, 8, 0),
            current_step=_plan().steps[0],
            current_location_kind="cafe",
            nearby_agents=[NearbyAgent(is_familiar=True),
                           NearbyAgent(is_familiar=False)],
        )
        for block in _REQUIRED_BLOCKS:
            assert block in prompt, f"missing block marker: {block!r}"

    def test_push_in_phone_block_only(self):
        """推送内容只出现在 【手机】 block，不在其它位置重复。"""
        push_content = "唯一标识_test_marker_2026"
        prompt = _build_replan_prompt(
            profile=_profile(),
            current_plan=_plan(),
            trigger_event=_push(content=push_content),
            recent_memories=[],
            current_time=datetime(2026, 4, 29, 8, 0),
            current_step=_plan().steps[0],
            current_location_kind="cafe",
            nearby_agents=[],
        )
        # 推送内容只出现 1 次（在 【手机】 block）
        assert prompt.count(push_content) == 1


# ---------------------------------------------------------------------------
# 3. 空 block 整块省略
# ---------------------------------------------------------------------------


class TestEmptyBlockOmission:

    def test_empty_nearby_omitted(self):
        prompt = _build_replan_prompt(
            profile=_profile(),
            current_plan=_plan(),
            trigger_event=_push(),
            recent_memories=[],
            current_time=datetime(2026, 4, 29, 8, 0),
            current_step=_plan().steps[0],
            current_location_kind="cafe",
            nearby_agents=[],
        )
        assert "【周围】" not in prompt
        # 不应有"无 / 空 / 没有人"占位
        assert "周围：无" not in prompt
        assert "周围：空" not in prompt

    def test_empty_memories_omitted(self):
        prompt = _build_replan_prompt(
            profile=_profile(),
            current_plan=_plan(),
            trigger_event=_push(),
            recent_memories=[],
            current_time=datetime(2026, 4, 29, 8, 0),
            current_step=_plan().steps[0],
            current_location_kind="cafe",
            nearby_agents=[NearbyAgent(is_familiar=True)],
        )
        assert "【最近发生】" not in prompt

    def test_no_current_step_omitted(self):
        prompt = _build_replan_prompt(
            profile=_profile(),
            current_plan=_plan(),
            trigger_event=_push(),
            recent_memories=[],
            current_time=datetime(2026, 4, 29, 8, 0),
            current_step=None,
            current_location_kind="home",
            nearby_agents=[],
        )
        assert "【正在做】" not in prompt

    def test_no_push_content_omits_phone_block(self):
        prompt = _build_replan_prompt(
            profile=_profile(),
            current_plan=_plan(),
            trigger_event=None,
            recent_memories=[],
            current_time=datetime(2026, 4, 29, 8, 0),
            current_step=None,
            current_location_kind=None,
            nearby_agents=None,
        )
        assert "【手机】" not in prompt


# ---------------------------------------------------------------------------
# 4. Planner.replan 接受新 schema 与旧 schema 都可用
# ---------------------------------------------------------------------------


import asyncio
from synthetic_socio_wind_tunnel.agent.planner import Planner


class _CapturePlanner:
    """记录 prompt 内容的最简 LLMClient。"""
    def __init__(self) -> None:
        self.last_prompt: str = ""

    async def generate(self, prompt: str, *, model: str = "") -> str:
        self.last_prompt = prompt
        return """<plan>
  <step>
    <time>9:00</time>
    <destination>park</destination>
    <action>walk</action>
    <duration>30</duration>
    <social>alone</social>
  </step>
</plan>"""


class TestPlannerReplanCompat:

    def test_new_schema_full(self):
        client = _CapturePlanner()
        planner = Planner(client)
        recent = [MemoryEvent(
            event_id="m1", agent_id="emma", tick=8,
            simulated_time=datetime(2026, 4, 29, 7, 50),
            kind="action", content="walked past library",
        )]
        new_plan, _changed = asyncio.run(planner.replan(
            _profile(), _plan(),
            interrupt_ctx={
                "trigger_event": _push(),
                "recent_memories": recent,
                "current_time": datetime(2026, 4, 29, 8, 0),
                "current_step": _plan().steps[0],
                "current_location_kind": "cafe",
                "nearby_agents": [NearbyAgent(is_familiar=True)],
            },
        ))
        assert new_plan is not None
        for block in _REQUIRED_BLOCKS:
            assert block in client.last_prompt

    def test_old_schema_no_new_keys(self):
        client = _CapturePlanner()
        planner = Planner(client)
        new_plan, _changed = asyncio.run(planner.replan(
            _profile(), _plan(),
            interrupt_ctx={
                "trigger_event": _push(),
                "recent_memories": [],
                "current_time": datetime(2026, 4, 29, 8, 0),
            },
        ))
        assert new_plan is not None
        # 缺新 key 的情况下：current_step / 周围 等 block 整块省略
        assert "【正在做】" not in client.last_prompt
        assert "【周围】" not in client.last_prompt
        # 但禁用词仍不许出现
        for word in _BANNED_WORDS:
            assert word not in client.last_prompt
