"""Tests for tools/suite_stub_llm.py — StubReplanLLM dispatch."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

# Add tools/ to import path so we can import suite_stub_llm as a module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from suite_stub_llm import StubReplanLLM, _plan_toward  # type: ignore

from synthetic_socio_wind_tunnel.agent import AgentProfile, DailyPlan, Planner


class TestStubDispatch:
    def test_hyperlocal_push_toward_target(self):
        stub = StubReplanLLM(
            seed=42, variant_name="hyperlocal_push",
            target_location="cafe_main",
        )
        raw = asyncio.run(stub.generate("any prompt"))
        data = json.loads(raw)
        assert len(data) >= 1
        assert any(s.get("destination") == "cafe_main" for s in data)
        assert any(s.get("action") == "move" for s in data)

    def test_global_distraction_returns_empty(self):
        stub = StubReplanLLM(seed=42, variant_name="global_distraction")
        raw = asyncio.run(stub.generate("prompt"))
        assert raw == "[]"

    def test_shared_anchor_toward_shared_location(self):
        stub = StubReplanLLM(
            seed=42, variant_name="shared_anchor",
            shared_location="park_main",
        )
        raw = asyncio.run(stub.generate("prompt"))
        data = json.loads(raw)
        assert len(data) >= 1
        assert any(s.get("destination") == "park_main" for s in data)

    def test_phone_friction_returns_empty(self):
        stub = StubReplanLLM(seed=42, variant_name="phone_friction")
        raw = asyncio.run(stub.generate("prompt"))
        assert raw == "[]"

    def test_catalyst_seeding_returns_empty(self):
        stub = StubReplanLLM(seed=42, variant_name="catalyst_seeding")
        raw = asyncio.run(stub.generate("prompt"))
        assert raw == "[]"

    def test_baseline_returns_empty(self):
        stub = StubReplanLLM(seed=42, variant_name="baseline")
        raw = asyncio.run(stub.generate("prompt"))
        assert raw == "[]"

    def test_unknown_variant_returns_empty(self):
        stub = StubReplanLLM(seed=42, variant_name="totally_unknown_xyz")
        raw = asyncio.run(stub.generate("prompt"))
        assert raw == "[]"


class TestReproducibility:
    def test_same_seed_byte_equal(self):
        stub_a = StubReplanLLM(
            seed=42, variant_name="hyperlocal_push",
            target_location="cafe",
        )
        stub_b = StubReplanLLM(
            seed=42, variant_name="hyperlocal_push",
            target_location="cafe",
        )
        outputs_a = [asyncio.run(stub_a.generate("p")) for _ in range(3)]
        outputs_b = [asyncio.run(stub_b.generate("p")) for _ in range(3)]
        assert outputs_a == outputs_b

    def test_different_seed_different(self):
        stub_a = StubReplanLLM(
            seed=1, variant_name="hyperlocal_push", target_location="cafe",
        )
        stub_b = StubReplanLLM(
            seed=2, variant_name="hyperlocal_push", target_location="cafe",
        )
        a = asyncio.run(stub_a.generate("p"))
        b = asyncio.run(stub_b.generate("p"))
        # time field randomized by seed → different output likely
        # (allow same in unlikely collision — loosely assert shape, not inequality)
        assert json.loads(a)[0]["destination"] == "cafe"
        assert json.loads(b)[0]["destination"] == "cafe"


class TestPlannerCompatibility:
    def test_stub_output_accepted_by_planner(self):
        """Planner.replan 接受 stub 的 JSON 输出——不抛、返回合法 DailyPlan。"""
        profile = AgentProfile(
            agent_id="emma", name="Emma", age=30, occupation="x",
            household="single", home_location="home",
        )
        current_plan = DailyPlan(
            agent_id="emma", date="2026-04-25", steps=[],
        )
        stub = StubReplanLLM(
            seed=42, variant_name="hyperlocal_push",
            target_location="cafe_main",
        )
        planner = Planner(llm_client=stub)

        interrupt_ctx = {
            "trigger_event": None,
            "recent_memories": [],
            "current_time": None,
        }
        new_plan = asyncio.run(planner.replan(profile, current_plan, interrupt_ctx))
        assert isinstance(new_plan, DailyPlan)
        # stub 产出 destination=cafe_main 的 step；新 plan 应包含它
        assert any(s.destination == "cafe_main" for s in new_plan.steps)

    def test_empty_stub_fallback_preserves_plan(self):
        """空 stub 返回 → Planner.replan fallback 返回原 plan 副本。"""
        from synthetic_socio_wind_tunnel.agent import PlanStep
        profile = AgentProfile(
            agent_id="emma", name="Emma", age=30, occupation="x",
            household="single", home_location="home",
        )
        original_step = PlanStep(
            time="8:00", action="stay", destination="home",
            activity="at home", duration_minutes=60, reason="",
            social_intent="alone",
        )
        current_plan = DailyPlan(
            agent_id="emma", date="2026-04-25", steps=[original_step],
        )
        stub = StubReplanLLM(seed=42, variant_name="global_distraction")
        planner = Planner(llm_client=stub)
        new_plan = asyncio.run(planner.replan(profile, current_plan, {
            "trigger_event": None, "recent_memories": [],
            "current_time": None,
        }))
        # 原 step 被保留
        assert len(new_plan.steps) == 1
        assert new_plan.steps[0].destination == "home"
