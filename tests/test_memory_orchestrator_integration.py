"""Integration tests: MemoryService subscribes orchestrator TickResult."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from synthetic_socio_wind_tunnel.agent import (
    AgentProfile,
    AgentRuntime,
    DailyPlan,
    Planner,
    PlanStep,
)
from synthetic_socio_wind_tunnel.agent.personality import PersonalityTraits
from synthetic_socio_wind_tunnel.atlas import Atlas
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.attention import AttentionService, FeedItem
from synthetic_socio_wind_tunnel.cartography.builder import RegionBuilder
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.memory import MemoryService
from synthetic_socio_wind_tunnel.orchestrator import Orchestrator


class MockLLM:
    def __init__(self, response: str = "[]"):
        self.response = response
        self.calls = 0

    async def generate(self, prompt: str, *, model: str = "", **kwargs) -> str:
        self.calls += 1
        return self.response


def _linear_atlas() -> Atlas:
    """4-node linear so agents moving opposite directions cross mid-way."""
    region = (
        RegionBuilder("r", "r")
        .add_outdoor("a", "a", area_type="street")
        .polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        .end_outdoor()
        .add_outdoor("b", "b", area_type="street")
        .polygon([(15, 0), (25, 0), (25, 10), (15, 10)])
        .end_outdoor()
        .add_outdoor("c", "c", area_type="street")
        .polygon([(30, 0), (40, 0), (40, 10), (30, 10)])
        .end_outdoor()
        .add_outdoor("d", "d", area_type="street")
        .polygon([(45, 0), (55, 0), (55, 10), (45, 10)])
        .end_outdoor()
        .connect("a", "b", path_type="road", distance=5.0)
        .connect("b", "c", path_type="road", distance=5.0)
        .connect("c", "d", path_type="road", distance=5.0)
        .build()
    )
    return Atlas(region)


def _agent(aid: str, home: str, plan_steps: list[PlanStep] | None = None,
           curiosity: float = 0.5, routine_adherence: float = 0.5) -> AgentRuntime:
    profile = AgentProfile(
        agent_id=aid, name=aid, age=30, occupation="x",
        household="single", home_location=home,
        personality=PersonalityTraits(
            curiosity=curiosity, routine_adherence=routine_adherence,
        ),
    )
    plan = (
        DailyPlan(agent_id=aid, date="2026-04-21", steps=plan_steps)
        if plan_steps is not None else None
    )
    return AgentRuntime(profile=profile, plan=plan, current_location=home)


def _ledger_with(*agents: AgentRuntime) -> Ledger:
    ledger = Ledger()
    ledger.current_time = datetime(2026, 4, 21, 7, 0, 0)
    for a in agents:
        ledger.set_entity(EntityState(
            entity_id=a.profile.agent_id, location_id=a.current_location,
            position=Coord(x=0, y=0),
        ))
    return ledger


class TestMemoryWrites:

    def test_action_events_recorded(self):
        atlas = _linear_atlas()
        alpha = _agent("alpha", "a",
                       plan_steps=[PlanStep(time="7:00", action="move",
                                             destination="b",
                                             duration_minutes=60)])
        ledger = _ledger_with(alpha)
        memory = MemoryService()

        orch = Orchestrator(atlas, ledger, [alpha], tick_minutes=60)
        agents = {alpha.profile.agent_id: alpha}
        orch.register_on_tick_end(
            lambda tr: memory.process_tick(tr, agents, None)
        )
        orch.run()

        all_evts = memory.all_for("alpha")
        action_evts = [e for e in all_evts if e.kind == "action"]
        # 24 ticks → 24 action events (每 tick 一个 MoveIntent / WaitIntent)
        assert len(action_evts) == 24

    def test_encounter_recorded_bilaterally(self):
        atlas = _linear_atlas()
        alpha = _agent("alpha", "a",
                       plan_steps=[PlanStep(time="7:00", action="move",
                                             destination="d",
                                             duration_minutes=60)])
        beta = _agent("beta", "d",
                       plan_steps=[PlanStep(time="7:00", action="move",
                                             destination="a",
                                             duration_minutes=60)])
        ledger = _ledger_with(alpha, beta)
        memory = MemoryService()

        orch = Orchestrator(atlas, ledger, [alpha, beta], tick_minutes=60)
        agents = {"alpha": alpha, "beta": beta}
        orch.register_on_tick_end(
            lambda tr: memory.process_tick(tr, agents, None)
        )
        orch.run()

        alpha_encounters = [e for e in memory.all_for("alpha")
                            if e.kind == "encounter"]
        beta_encounters = [e for e in memory.all_for("beta")
                           if e.kind == "encounter"]
        assert len(alpha_encounters) >= 1
        assert len(beta_encounters) >= 1
        # 彼此 actor_id 互指
        assert alpha_encounters[0].actor_id == "beta"
        assert beta_encounters[0].actor_id == "alpha"


class TestNotificationIngest:

    def test_notifications_recorded(self):
        atlas = _linear_atlas()
        alpha = _agent("alpha", "a")
        ledger = _ledger_with(alpha)
        attention = AttentionService(ledger, seed=0)
        memory = MemoryService(attention_service=attention)

        # 在 tick 开始前注入一条推送
        item = FeedItem(
            feed_item_id="f1", content="event tonight!",
            source="commercial_push", urgency=0.7,
            created_at=ledger.current_time,
        )
        attention.inject_feed_item(item, ["alpha"])

        orch = Orchestrator(atlas, ledger, [alpha],
                             attention_service=attention, tick_minutes=60)
        agents = {"alpha": alpha}
        orch.register_on_tick_end(
            lambda tr: memory.process_tick(tr, agents, None)
        )
        orch.run()

        notifs = [e for e in memory.all_for("alpha") if e.kind == "notification"]
        assert len(notifs) >= 1
        assert notifs[0].urgency == 0.7


class TestReplanTrigger:

    def test_replan_happens_once_per_tick(self):
        atlas = _linear_atlas()
        # 高好奇 agent 会对 urgency=0.9 的推送触发 replan
        alpha = _agent("alpha", "a", curiosity=0.9, routine_adherence=0.1,
                       plan_steps=[PlanStep(time="7:00", action="stay",
                                             duration_minutes=60)])
        ledger = _ledger_with(alpha)
        attention = AttentionService(ledger, seed=0)
        memory = MemoryService(attention_service=attention)

        # 3 条同 tick 到达的推送 —— replan 应只发生一次
        for i in range(3):
            item = FeedItem(
                feed_item_id=f"f{i}", content=f"urgent {i}",
                source="commercial_push", urgency=0.9,
                created_at=ledger.current_time,
            )
            attention.inject_feed_item(item, ["alpha"])

        mock_llm = MockLLM(response="[]")  # replan 返回空 → fallback 原 plan
        planner = Planner(mock_llm)

        orch = Orchestrator(atlas, ledger, [alpha],
                             attention_service=attention, tick_minutes=60)
        agents = {"alpha": alpha}
        orch.register_on_tick_end(
            lambda tr: memory.process_tick(tr, agents, planner)
        )
        orch.run()

        # 24 tick × 最多 1 replan/tick = 24；但触发条件只对第一个 tick 成立
        # （推送都在第一个 tick 被 ingest 并 replan；之后 notifications 不再触发）
        assert mock_llm.calls <= 24
        assert mock_llm.calls >= 1


class TestDailySummary:

    def test_daily_summary_one_call_per_agent(self):
        alpha = _agent("alpha", "a")
        beta = _agent("beta", "a")
        memory = MemoryService()

        # 每个 agent 写几条 events
        from synthetic_socio_wind_tunnel.memory import MemoryEvent
        for agent_id in ("alpha", "beta"):
            for i in range(3):
                memory.record(agent_id, MemoryEvent(
                    event_id=f"{agent_id}_{i}", agent_id=agent_id, tick=i,
                    simulated_time=datetime(2026, 4, 21, 7 + i, 0),
                    kind="action", content=f"did {i}",
                ))

        mock = MockLLM(response="Had a pleasant day.")
        agents = {"alpha": alpha, "beta": beta}
        summaries = asyncio.run(memory.run_daily_summary(agents, mock))

        assert mock.calls == 2  # one per agent
        assert summaries["alpha"].summary_text == "Had a pleasant day."
        assert summaries["beta"].summary_text == "Had a pleasant day."

    def test_daily_summary_llm_failure_fallback(self):
        alpha = _agent("alpha", "a")
        memory = MemoryService()
        from synthetic_socio_wind_tunnel.memory import MemoryEvent
        memory.record("alpha", MemoryEvent(
            event_id="1", agent_id="alpha", tick=0,
            simulated_time=datetime.now(), kind="action", content="x",
        ))

        class FailingLLM:
            async def generate(self, *a, **kw):
                raise RuntimeError("LLM down")

        summaries = asyncio.run(memory.run_daily_summary(
            {"alpha": alpha}, FailingLLM()
        ))
        assert summaries["alpha"].summary_text == "(unavailable)"
