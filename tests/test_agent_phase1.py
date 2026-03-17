"""Phase 1 端到端验证：1 个 agent 按 LLM 计划在地图上逐步移动。"""

import asyncio

import pytest

from synthetic_socio_wind_tunnel.atlas.models import (
    Building,
    Connection,
    Coord,
    Material,
    OutdoorArea,
    Polygon,
    Region,
)
from synthetic_socio_wind_tunnel.atlas.service import Atlas
from synthetic_socio_wind_tunnel.engine.navigation import NavigationService
from synthetic_socio_wind_tunnel.engine.simulation import SimulationService
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.ledger.service import Ledger

from synthetic_socio_wind_tunnel.agent import AgentProfile, AgentRuntime, DailyPlan, PlanStep, Planner


# ---------------------------------------------------------------------------
# 测试地图: 一个小社区
# ---------------------------------------------------------------------------
#
#  maple_apartments ── street_seg_1 ── street_seg_2 ── sunrise_cafe
#                                          |
#                                      central_park

def _make_poly(x: float, y: float, w: float = 10, h: float = 10) -> Polygon:
    return Polygon(vertices=(
        Coord(x=x, y=y),
        Coord(x=x + w, y=y),
        Coord(x=x + w, y=y + h),
        Coord(x=x, y=y + h),
    ))


@pytest.fixture
def community_region() -> Region:
    buildings = {
        "maple_apartments": Building(
            id="maple_apartments",
            name="Maple Apartments",
            polygon=_make_poly(0, 0),
            exterior_material=Material.BRICK,
        ),
        "sunrise_cafe": Building(
            id="sunrise_cafe",
            name="Sunrise Café",
            polygon=_make_poly(60, 0),
            exterior_material=Material.WOOD,
        ),
    }
    outdoor_areas = {
        "street_seg_1": OutdoorArea(
            id="street_seg_1",
            name="Main Street Seg 1",
            polygon=_make_poly(15, 0, 15, 5),
            surface="asphalt",
        ),
        "street_seg_2": OutdoorArea(
            id="street_seg_2",
            name="Main Street Seg 2",
            polygon=_make_poly(35, 0, 15, 5),
            surface="asphalt",
        ),
        "central_park": OutdoorArea(
            id="central_park",
            name="Central Park",
            polygon=_make_poly(30, 15, 20, 20),
            surface="grass",
        ),
    }
    connections = (
        Connection(from_id="maple_apartments", to_id="street_seg_1", distance=5.0, path_type="entrance"),
        Connection(from_id="street_seg_1", to_id="street_seg_2", distance=20.0, path_type="road"),
        Connection(from_id="street_seg_2", to_id="sunrise_cafe", distance=5.0, path_type="entrance"),
        Connection(from_id="street_seg_2", to_id="central_park", distance=10.0, path_type="path"),
    )
    return Region(
        id="test_community",
        name="Test Community",
        bounds_min=Coord(x=0, y=0),
        bounds_max=Coord(x=80, y=40),
        buildings=buildings,
        outdoor_areas=outdoor_areas,
        connections=connections,
    )


@pytest.fixture
def community_atlas(community_region):
    return Atlas(community_region)


@pytest.fixture
def community_ledger():
    return Ledger()


@pytest.fixture
def community_sim(community_atlas, community_ledger):
    return SimulationService(community_atlas, community_ledger)


@pytest.fixture
def community_nav(community_atlas, community_ledger):
    return NavigationService(community_atlas, community_ledger)


@pytest.fixture
def emma_profile() -> AgentProfile:
    return AgentProfile(
        agent_id="emma",
        name="Emma Chen",
        age=28,
        occupation="software_engineer",
        household="single",
        home_location="maple_apartments",
        personality_traits={"extroversion": 0.3, "curiosity": 0.8},
        personality_description="你性格偏内向但好奇心强，喜欢观察周围环境。",
        preferred_social_size=2,
        interests=["coffee", "reading", "walking"],
        languages=["mandarin", "english"],
        wake_time="7:00",
        sleep_time="23:00",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAgentProfile:
    def test_create_profile(self, emma_profile: AgentProfile):
        assert emma_profile.agent_id == "emma"
        assert emma_profile.name == "Emma Chen"
        assert emma_profile.home_location == "maple_apartments"

    def test_trait_access(self, emma_profile: AgentProfile):
        assert emma_profile.trait("curiosity") == 0.8
        assert emma_profile.trait("nonexistent") == 0.5  # default
        assert emma_profile.trait("nonexistent", 0.0) == 0.0

    def test_frozen(self, emma_profile: AgentProfile):
        with pytest.raises(Exception):
            emma_profile.name = "Other"  # type: ignore[misc]


class TestPlanStep:
    def test_basic(self):
        step = PlanStep(
            time="7:00", action="move", destination="sunrise_cafe",
            activity="commuting", duration_minutes=30,
        )
        assert step.destination == "sunrise_cafe"
        assert step.social_intent == "alone"  # default


class TestDailyPlan:
    def test_advance(self):
        plan = DailyPlan(
            agent_id="emma",
            date="2025-01-01",
            steps=[
                PlanStep(time="7:00", action="move", destination="street_seg_1"),
                PlanStep(time="8:00", action="stay", destination="sunrise_cafe"),
            ],
        )
        assert plan.current() is not None
        assert plan.current().time == "7:00"
        plan.advance()
        assert plan.current().time == "8:00"
        plan.advance()
        assert plan.current() is None

    def test_insert_interrupt(self):
        plan = DailyPlan(
            agent_id="emma",
            date="2025-01-01",
            steps=[
                PlanStep(time="7:00", action="move", destination="a"),
                PlanStep(time="9:00", action="stay", destination="c"),
            ],
        )
        plan.insert_interrupt(PlanStep(time="8:00", action="stay", destination="b"))
        assert len(plan.steps) == 3
        assert plan.steps[1].destination == "b"


class TestPlannerParsing:
    def test_parse_valid_json(self):
        raw = '[{"time": "7:00", "action": "move", "destination": "cafe", "activity": "walking", "duration_minutes": 30, "reason": "morning coffee", "social_intent": "alone"}]'
        steps = Planner._parse_plan(raw)
        assert len(steps) == 1
        assert steps[0].destination == "cafe"

    def test_parse_markdown_wrapped(self):
        raw = '```json\n[{"time": "7:00", "action": "move", "destination": "park"}]\n```'
        steps = Planner._parse_plan(raw)
        assert len(steps) == 1

    def test_parse_garbage(self):
        steps = Planner._parse_plan("this is not json at all")
        assert steps == []


class TestAgentRuntime:
    def test_init_defaults_to_home(self, emma_profile: AgentProfile):
        rt = AgentRuntime(profile=emma_profile)
        assert rt.current_location == "maple_apartments"
        assert not rt.is_moving

    def test_movement_queue(self, emma_profile, community_nav, community_ledger):
        # 先在 ledger 中注册 entity
        community_ledger.set_entity(EntityState(
            entity_id="emma", location_id="maple_apartments", position=Coord(x=5, y=5),
        ))

        route = community_nav.find_route("maple_apartments", "sunrise_cafe")
        assert route.success, f"Routing failed: {route.error}"

        rt = AgentRuntime(profile=emma_profile)
        rt.start_moving(route)
        assert rt.is_moving

        visited = []
        while rt.is_moving:
            loc = rt.next_move_location()
            if loc:
                visited.append(loc)
                rt.current_location = loc

        assert not rt.is_moving
        assert rt.current_location == "sunrise_cafe"
        # 路径应该经过街道段
        assert "street_seg_1" in visited
        assert "street_seg_2" in visited


class TestEndToEnd:
    """端到端测试：agent 按预设计划在地图上逐步移动。"""

    def test_agent_moves_along_plan(
        self, emma_profile, community_sim, community_nav, community_ledger
    ):
        # 1. 在 ledger 中注册 entity
        community_ledger.set_entity(EntityState(
            entity_id="emma", location_id="maple_apartments", position=Coord(x=5, y=5),
        ))

        # 2. 创建 runtime
        rt = AgentRuntime(profile=emma_profile)

        # 3. 用预设计划 (跳过 LLM 调用)
        plan = DailyPlan(
            agent_id="emma",
            date="2025-01-01",
            steps=[
                PlanStep(time="7:00", action="move", destination="sunrise_cafe",
                         activity="going for coffee", duration_minutes=15),
                PlanStep(time="7:30", action="stay", destination="sunrise_cafe",
                         activity="having coffee", duration_minutes=60),
                PlanStep(time="8:30", action="move", destination="central_park",
                         activity="morning walk", duration_minutes=30),
            ],
        )
        rt.set_plan(plan)

        # 4. 模拟 tick 循环
        trajectory: list[dict] = []
        tick = 0
        max_ticks = 50

        while tick < max_ticks:
            step = rt.current_step()
            if step is None:
                break

            if step.action == "move" and not rt.is_moving:
                # 开始移动到目的地
                route = community_nav.find_route(rt.current_location, step.destination)
                if route.success:
                    rt.start_moving(route)
                else:
                    rt.advance_plan()
                    continue

            if rt.is_moving:
                loc = rt.next_move_location()
                if loc:
                    result = community_sim.move_entity("emma", to_location=loc)
                    rt.current_location = loc
                    trajectory.append({"tick": tick, "location": loc, "action": "moving"})
                else:
                    # 到达目的地，推进计划
                    rt.advance_plan()
            else:
                # stay: 在当前位置停留
                trajectory.append({"tick": tick, "location": rt.current_location, "action": step.activity})
                # 简化：stay 步骤只消耗 1 tick 然后推进
                rt.advance_plan()

            tick += 1

        # 验证
        assert len(trajectory) > 0
        locations_visited = [t["location"] for t in trajectory]

        # 应该经过街道段到达 sunrise_cafe
        assert "street_seg_1" in locations_visited
        assert "street_seg_2" in locations_visited
        assert "sunrise_cafe" in locations_visited

        # 最终应该到达 central_park (最后一个 move 目标)
        assert "central_park" in locations_visited
