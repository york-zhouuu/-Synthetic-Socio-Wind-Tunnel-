"""Tests verifying D.1 (notification dedup) and D.2 (replan time rewrite) fixes."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

import pytest

from synthetic_socio_wind_tunnel.agent import (
    AgentProfile,
    AgentRuntime,
    DailyPlan,
    Planner,
    PlanStep,
)
from synthetic_socio_wind_tunnel.agent.personality import PersonalityTraits
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.attention import AttentionService, FeedItem
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.memory import MemoryService, MemoryEvent


class MockLLM:
    def __init__(self, response: str = "[]"):
        self.response = response
        self.calls = 0

    async def generate(self, prompt: str, *, model: str = "", **kwargs) -> str:
        self.calls += 1
        return self.response


# ============================================================================
# D.1: notification 去重基于 feed_item_id（不是 timestamp）
# ============================================================================

class TestD1NotificationDedup:

    def _setup(self):
        ledger = Ledger()
        ledger.current_time = datetime(2026, 4, 21, 8, 0, 0)
        ledger.set_entity(EntityState(
            entity_id="emma", location_id="cafe_a", position=Coord(x=0, y=0),
        ))
        attention = AttentionService(ledger, seed=0)
        memory = MemoryService(attention_service=attention)
        return ledger, attention, memory

    def test_same_notification_ingested_once_across_ticks(self):
        ledger, attention, memory = self._setup()
        # 注入一条推送
        item = FeedItem(
            feed_item_id="f_001", content="hello",
            source="commercial_push", urgency=0.7,
            created_at=ledger.current_time,
        )
        attention.inject_feed_item(item, ["emma"])

        # 模拟多次 tick 调用 _ingest_notifications
        for tick in range(1, 6):
            memory._ingest_notifications("emma", tick=tick,
                                          sim_time=ledger.current_time)
            ledger.current_time += timedelta(minutes=5)

        notif_events = [e for e in memory.all_for("emma") if e.kind == "notification"]
        assert len(notif_events) == 1, \
            f"expected 1 notification event, got {len(notif_events)}"
        # 首次 ingest 的 tick 应该是 1
        assert notif_events[0].tick == 1

    def test_new_notification_still_ingested(self):
        """后续注入的新 feed item 应当被 ingest。"""
        ledger, attention, memory = self._setup()
        item1 = FeedItem(
            feed_item_id="f_001", content="first",
            source="commercial_push", urgency=0.5,
            created_at=ledger.current_time,
        )
        attention.inject_feed_item(item1, ["emma"])
        memory._ingest_notifications("emma", tick=1, sim_time=ledger.current_time)

        # 推进时间后注入第二条
        ledger.current_time += timedelta(hours=1)
        item2 = FeedItem(
            feed_item_id="f_002", content="second",
            source="commercial_push", urgency=0.8,
            created_at=ledger.current_time,
        )
        attention.inject_feed_item(item2, ["emma"])
        memory._ingest_notifications("emma", tick=12, sim_time=ledger.current_time)

        notifs = [e for e in memory.all_for("emma") if e.kind == "notification"]
        assert len(notifs) == 2
        assert {n.content for n in notifs} == {"first", "second"}

    def test_per_agent_consumption_isolated(self):
        ledger, attention, memory = self._setup()
        ledger.set_entity(EntityState(
            entity_id="bob", location_id="cafe_a", position=Coord(x=0, y=0),
        ))
        item = FeedItem(
            feed_item_id="f_shared", content="broadcast",
            source="commercial_push", urgency=0.5,
            created_at=ledger.current_time,
        )
        attention.inject_feed_item(item, ["emma", "bob"])

        # Emma 消费
        memory._ingest_notifications("emma", tick=1,
                                      sim_time=ledger.current_time)
        # Bob 尚未消费——再次 ingest 为 bob 时仍应得到 event
        memory._ingest_notifications("bob", tick=1,
                                      sim_time=ledger.current_time)

        assert len([e for e in memory.all_for("emma") if e.kind == "notification"]) == 1
        assert len([e for e in memory.all_for("bob") if e.kind == "notification"]) == 1

        # 再调 bob 的 ingest 不应重复
        memory._ingest_notifications("bob", tick=2,
                                      sim_time=ledger.current_time)
        assert len([e for e in memory.all_for("bob") if e.kind == "notification"]) == 1


# ============================================================================
# D.2: Planner.replan 把过期 step.time 重写为 current_time + 1min
# ============================================================================

class TestD2ReplanTimeRewrite:

    def _profile(self):
        return AgentProfile(
            agent_id="emma", name="Emma", age=30, occupation="x",
            household="single", home_location="home",
        )

    def _plan(self, current_step_index: int = 2):
        return DailyPlan(
            agent_id="emma", date="2026-04-21",
            current_step_index=current_step_index,
            steps=[
                PlanStep(time="7:00", action="move", destination="a",
                         duration_minutes=30),
                PlanStep(time="7:30", action="move", destination="b",
                         duration_minutes=30),
                PlanStep(time="8:00", action="move", destination="c",
                         duration_minutes=30),
            ],
        )

    def _trigger_event(self):
        return MemoryEvent(
            event_id="n1", agent_id="emma", tick=10,
            simulated_time=datetime(2026, 4, 21, 15, 0),
            kind="notification", content="afternoon push",
            urgency=0.9,
        )

    def test_stale_step_time_is_rewritten(self):
        """LLM 返回 time='8:15'，但 current_time=15:00 → 改写为 15:01。"""
        llm = MockLLM(response=json.dumps([
            {"time": "8:15", "action": "move", "destination": "target",
             "duration_minutes": 60, "activity": "x", "reason": "y",
             "social_intent": "alone"},
        ]))
        planner = Planner(llm)
        ctx = {
            "trigger_event": self._trigger_event(),
            "recent_memories": [],
            "current_time": datetime(2026, 4, 21, 15, 0),
        }
        new_plan = asyncio.run(planner.replan(self._profile(), self._plan(), ctx))

        # 新 future step 应在 index 2 位置
        rewritten = new_plan.steps[2]
        # 原 LLM 吐出 "8:15"，应被改写为 "15:01"（current_time + 1min）
        assert rewritten.time == "15:01"

    def test_future_step_time_preserved(self):
        """如果 LLM 返回的 time 已经在未来，不动。"""
        llm = MockLLM(response=json.dumps([
            {"time": "15:30", "action": "move", "destination": "target",
             "duration_minutes": 60, "activity": "x", "reason": "y",
             "social_intent": "alone"},
        ]))
        planner = Planner(llm)
        ctx = {
            "trigger_event": self._trigger_event(),
            "recent_memories": [],
            "current_time": datetime(2026, 4, 21, 15, 0),
        }
        new_plan = asyncio.run(planner.replan(self._profile(), self._plan(), ctx))
        rewritten = new_plan.steps[2]
        assert rewritten.time == "15:30"

    def test_invalid_time_rewritten(self):
        llm = MockLLM(response=json.dumps([
            {"time": "garbage", "action": "move", "destination": "target",
             "duration_minutes": 60, "activity": "x", "reason": "y",
             "social_intent": "alone"},
        ]))
        planner = Planner(llm)
        ctx = {
            "trigger_event": self._trigger_event(),
            "recent_memories": [],
            "current_time": datetime(2026, 4, 21, 15, 0),
        }
        # MockLLM 会让 _parse_plan 失败或 rewrite。先看是否被 parse 拒掉。
        # PlanStep 的 time 是 str，所以 "garbage" 能构造出 PlanStep，然后
        # _ensure_future_step_time 把它 rewrite 为 15:01
        new_plan = asyncio.run(planner.replan(self._profile(), self._plan(), ctx))
        rewritten = new_plan.steps[2]
        assert rewritten.time == "15:01"

    def test_prompt_contains_time_constraint(self):
        llm = MockLLM(response="[]")
        planner = Planner(llm)
        ctx = {
            "trigger_event": self._trigger_event(),
            "recent_memories": [],
            "current_time": datetime(2026, 4, 21, 15, 0),
        }
        asyncio.run(planner.replan(self._profile(), self._plan(), ctx))
        # prompt 应该包含 "必须 >= 当前时刻"
        prompt = llm.calls and "15:00" or ""
        # Actually calls is an int; look at the response storage another way
        # Mock records calls differently — let's check by calling again with
        # a specific fake mock
        class CapturingMock:
            def __init__(self):
                self.prompts = []
            async def generate(self, p, *, model="", **kw):
                self.prompts.append(p)
                return "[]"
        cap = CapturingMock()
        planner2 = Planner(cap)
        asyncio.run(planner2.replan(self._profile(), self._plan(), ctx))
        assert "必须" in cap.prompts[0] or "must" in cap.prompts[0].lower()


# ============================================================================
# D.1 + D.2 集成：一个 stale-time LLM 加上无去重的 service 会产生无限 replan
# ============================================================================

class TestCombinedIntegration:

    def test_no_infinite_replan_under_stub_llm(self):
        """
        回放 smoke demo 的场景但只有 5 tick：
        - 推送一次
        - process_tick 多次
        - LLM 调用次数应 = 1（被 ingest 一次后不再触发 replan）
        """
        ledger = Ledger()
        ledger.current_time = datetime(2026, 4, 21, 15, 0, 0)
        ledger.set_entity(EntityState(
            entity_id="emma", location_id="home", position=Coord(x=0, y=0),
        ))
        attention = AttentionService(ledger, seed=0)
        memory = MemoryService(attention_service=attention)

        # StubLLM 返回合理（未来）的 step time
        stub_llm = MockLLM(response=json.dumps([
            {"time": "15:30", "action": "move", "destination": "target",
             "duration_minutes": 60, "activity": "x", "reason": "y",
             "social_intent": "alone"},
        ]))
        planner = Planner(stub_llm)

        profile = AgentProfile(
            agent_id="emma", name="Emma", age=30, occupation="x",
            household="single", home_location="home",
            personality=PersonalityTraits(curiosity=0.9, routine_adherence=0.1),
        )
        plan = DailyPlan(agent_id="emma", date="2026-04-21", steps=[
            PlanStep(time="7:00", action="move", destination="home",
                     duration_minutes=30),
        ])
        runtime = AgentRuntime(profile=profile, plan=plan, current_location="home")

        # 注入一条推送
        item = FeedItem(
            feed_item_id="f_push", content="come over",
            source="commercial_push", urgency=0.9,
            created_at=ledger.current_time,
        )
        attention.inject_feed_item(item, ["emma"])

        # 模拟 5 tick 的 process_tick（空 TickResult，触发 ingest 即可）
        from synthetic_socio_wind_tunnel.orchestrator.models import TickResult

        agents_by_id = {"emma": runtime}
        for tick in range(5):
            tr = TickResult(
                tick_index=tick,
                simulated_time=ledger.current_time,
                commits=(),
                encounter_candidates=(),
            )
            memory.process_tick(tr, agents_by_id, planner)
            ledger.current_time += timedelta(minutes=5)

        # D.1 + D.2 一起生效后：只有 1 次 replan LLM 调用
        assert stub_llm.calls == 1, \
            f"expected 1 LLM call, got {stub_llm.calls} (D.1 dedup might be broken)"
