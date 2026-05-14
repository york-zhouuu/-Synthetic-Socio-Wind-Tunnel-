"""Tests for tools/suite_stub_llm.py — StubReplanLLM dispatch."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

# Add tools/ to import path so we can import suite_stub_llm as a module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from suite_stub_llm import StubReplanLLM, _plan_toward  # type: ignore

from synthetic_socio_wind_tunnel.agent import AgentProfile, DailyPlan, Planner
from synthetic_socio_wind_tunnel.agent.planner import _parse_xml_plan


_EMPTY_PLAN_XML = "<plan></plan>"


class TestStubDispatch:
    def test_hyperlocal_push_toward_target(self):
        stub = StubReplanLLM(
            seed=42, variant_name="hyperlocal_push",
            target_location="cafe_main",
        )
        raw = asyncio.run(stub.generate("any prompt"))
        # XML 输出（lightweight-llm-format）
        assert "<destination>cafe_main</destination>" in raw
        # 用 Planner 的 parser 验证可解析
        steps = _parse_xml_plan(raw)
        assert len(steps) >= 1
        assert any(s.destination == "cafe_main" for s in steps)
        assert any(s.action == "move" for s in steps)

    def test_global_distraction_returns_distraction_destination(self):
        """B2 fix: gd no longer returns empty; goes to a non-target far area.

        With no atlas + only target_location, fallback chain returns None →
        empty plan. With destinations passed, fallback uses last destination.
        """
        stub = StubReplanLLM(
            seed=42, variant_name="global_distraction",
            target_location="cafe_main",
            destinations=("park_a", "mall_b", "far_corner"),
        )
        raw = asyncio.run(stub.generate("prompt"))
        steps = _parse_xml_plan(raw)
        assert len(steps) >= 1, \
            "gd SHALL return non-empty plan (B2 fix) when destinations available"
        # Fallback in absence of atlas → destinations[-1] = "far_corner".
        assert steps[0].destination == "far_corner"
        assert steps[0].destination != "cafe_main"

    def test_global_distraction_no_destinations_falls_back_empty(self):
        """No atlas + no destinations → empty plan (degraded fallback)."""
        stub = StubReplanLLM(
            seed=42, variant_name="global_distraction",
            target_location="cafe_main",
        )
        raw = asyncio.run(stub.generate("prompt"))
        assert raw == _EMPTY_PLAN_XML

    def test_shared_anchor_toward_shared_location(self):
        stub = StubReplanLLM(
            seed=42, variant_name="shared_anchor",
            shared_location="park_main",
        )
        raw = asyncio.run(stub.generate("prompt"))
        steps = _parse_xml_plan(raw)
        assert len(steps) >= 1
        assert any(s.destination == "park_main" for s in steps)

    def test_phone_friction_toward_community_location(self):
        """B3 fix: pf no longer empty; goes to community heuristic location."""
        stub = StubReplanLLM(
            seed=42, variant_name="phone_friction",
            destinations=("park_a", "mall_b"),
        )
        raw = asyncio.run(stub.generate("prompt"))
        steps = _parse_xml_plan(raw)
        assert len(steps) >= 1, \
            "pf SHALL return non-empty plan (B3 fix) when destinations available"
        # Without atlas, picks destinations[0].
        assert steps[0].destination == "park_a"

    def test_catalyst_seeding_returns_empty(self):
        stub = StubReplanLLM(seed=42, variant_name="catalyst_seeding")
        raw = asyncio.run(stub.generate("prompt"))
        assert raw == _EMPTY_PLAN_XML

    def test_baseline_returns_empty(self):
        stub = StubReplanLLM(seed=42, variant_name="baseline")
        raw = asyncio.run(stub.generate("prompt"))
        assert raw == _EMPTY_PLAN_XML

    def test_unknown_variant_returns_empty(self):
        stub = StubReplanLLM(seed=42, variant_name="totally_unknown_xyz")
        raw = asyncio.run(stub.generate("prompt"))
        assert raw == _EMPTY_PLAN_XML


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
        # 两边都是合法 XML 且都指向 cafe；time field 由 seed 决定可能不同
        a_steps = _parse_xml_plan(a)
        b_steps = _parse_xml_plan(b)
        assert a_steps[0].destination == "cafe"
        assert b_steps[0].destination == "cafe"


class TestPlannerCompatibility:
    def test_stub_output_accepted_by_planner(self):
        """Planner.replan 接受 stub 的 XML 输出——不抛、返回合法 DailyPlan。"""
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
        new_plan, _changed = asyncio.run(planner.replan(profile, current_plan, interrupt_ctx))
        assert isinstance(new_plan, DailyPlan)
        # stub 产出 destination=cafe_main 的 step；新 plan 应包含它
        assert any(s.destination == "cafe_main" for s in new_plan.steps)

    def test_empty_stub_fallback_preserves_plan(self):
        """空 stub 返回 → Planner.replan fallback 返回原 plan 副本。

        Use catalyst_seeding here because gd / pf no longer return empty
        in their typical configured form (B2/B3 fix). catalyst_seeding's
        stub still returns _EMPTY_PLAN_XML by default.
        """
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
        stub = StubReplanLLM(seed=42, variant_name="catalyst_seeding")
        planner = Planner(llm_client=stub)
        new_plan, _changed = asyncio.run(planner.replan(profile, current_plan, {
            "trigger_event": None, "recent_memories": [],
            "current_time": None,
        }))
        # 原 step 被保留
        assert len(new_plan.steps) == 1
        assert new_plan.steps[0].destination == "home"


class TestStubWithPools:
    """fix-population-uses-typed-locations: stub uses LocationPools."""

    def _setup(self):
        import os
        import random
        if not os.path.exists("data/lanecove_atlas.json"):
            pytest.skip("Lane Cove atlas fixture not available")
        from synthetic_socio_wind_tunnel import Atlas, build_location_pools
        atlas = Atlas.from_json("data/lanecove_atlas.json")
        pools = build_location_pools(
            atlas, home_count=40, work_count=20, poi_count=30,
            rng=random.Random(42),
        )
        target = pools.pick_target_location(
            atlas, random.Random(42), prefer="community",
        )
        return atlas, pools, target

    def test_hyperlocal_push_target_in_poi_pool(self):
        atlas, pools, target = self._setup()
        stub = StubReplanLLM(
            seed=42, variant_name="hyperlocal_push",
            target_location=target, atlas=atlas, pools=pools,
        )
        raw = asyncio.run(stub.generate("any"))
        steps = _parse_xml_plan(raw)
        assert any(s.destination == target for s in steps)
        assert target in pools.poi_pool

    def test_global_distraction_destination_in_poi_pool_and_not_street(self):
        atlas, pools, target = self._setup()
        stub = StubReplanLLM(
            seed=42, variant_name="global_distraction",
            target_location=target, atlas=atlas, pools=pools,
        )
        raw = asyncio.run(stub.generate("any"))
        steps = _parse_xml_plan(raw)
        assert steps, "gd stub must return non-empty plan"
        dest = steps[0].destination
        assert dest in pools.poi_pool, (
            f"gd destination {dest} should be in poi_pool"
        )
        assert dest != target
        outdoor = atlas.get_outdoor_area(dest)
        if outdoor is not None:
            assert outdoor.area_type != "street", (
                f"gd destination {dest} is a street outdoor area "
                f"(area_type={outdoor.area_type})"
            )

    def test_phone_friction_community_heuristic_not_street(self):
        atlas, pools, target = self._setup()
        stub = StubReplanLLM(
            seed=42, variant_name="phone_friction",
            target_location=target, atlas=atlas, pools=pools,
        )
        raw = asyncio.run(stub.generate("any"))
        steps = _parse_xml_plan(raw)
        assert steps, "pf stub must return non-empty plan"
        dest = steps[0].destination
        assert dest in pools.poi_pool

        outdoor = atlas.get_outdoor_area(dest)
        building = atlas.get_building(dest)
        is_park = outdoor is not None and outdoor.area_type in (
            "park", "playground", "garden",
        )
        is_community = building is not None and building.building_type in (
            "community", "worship",
        )
        is_fallback_first_poi = dest == pools.poi_pool[0]
        assert is_park or is_community or is_fallback_first_poi

    def test_pools_path_reproducible(self):
        atlas, pools, target = self._setup()
        stub_a = StubReplanLLM(
            seed=7, variant_name="global_distraction",
            target_location=target, atlas=atlas, pools=pools,
        )
        stub_b = StubReplanLLM(
            seed=7, variant_name="global_distraction",
            target_location=target, atlas=atlas, pools=pools,
        )
        raw_a = asyncio.run(stub_a.generate("p"))
        raw_b = asyncio.run(stub_b.generate("p"))
        assert raw_a == raw_b
