"""AgentRuntime — 单个 agent 的运行时封装。

管理一个 agent 在模拟中的状态：当前计划、移动队列、感知上下文。
Orchestrator 通过 AgentRuntime 来驱动 agent 行为。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .planner import DailyPlan, PlanStep

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.engine.navigation import NavigationResult
    from .profile import AgentProfile


@dataclass
class AgentRuntime:
    """单个 agent 的运行时状态。"""

    profile: AgentProfile
    plan: DailyPlan | None = None
    current_location: str = ""

    # 逐步移动队列: agent 正在沿路径移动时，这里存放剩余的 location 序列
    _movement_queue: list[str] = field(default_factory=list)

    # 当前正在执行的 plan step (可能因移动中而跨多个 tick)
    _moving: bool = False

    def __post_init__(self) -> None:
        if not self.current_location:
            self.current_location = self.profile.home_location

    # --- 移动 ---

    @property
    def is_moving(self) -> bool:
        """agent 是否正在沿路径移动中。"""
        return len(self._movement_queue) > 0

    def start_moving(self, route: NavigationResult) -> None:
        """开始沿导航路径逐步移动。

        route.path 返回完整的 location ID 序列 (含起点)。
        我们只需要起点之后的部分。
        """
        path = route.path
        if len(path) > 1:
            self._movement_queue = list(path[1:])  # 去掉起点
        self._moving = True

    def next_move_location(self) -> str | None:
        """取出移动队列中的下一个 location。

        每个 tick 调一次，返回 agent 应该移动到的 location_id。
        队列为空时返回 None（到达目的地）。
        """
        if not self._movement_queue:
            self._moving = False
            return None
        return self._movement_queue.pop(0)

    def cancel_movement(self) -> None:
        """取消当前移动（例如重规划时）。"""
        self._movement_queue.clear()
        self._moving = False

    # --- 计划 ---

    def set_plan(self, plan: DailyPlan) -> None:
        self.plan = plan

    def current_step(self) -> PlanStep | None:
        if self.plan is None:
            return None
        return self.plan.current()

    def advance_plan(self) -> PlanStep | None:
        """推进到计划的下一步。"""
        if self.plan is None:
            return None
        return self.plan.advance()

    # --- 感知上下文构建 ---

    def build_observer_context(self) -> dict:
        """构建用于 PerceptionPipeline.render() 的 ObserverContext 参数。

        返回 dict 形式，调用方用 ObserverContext(**ctx) 构造。
        """
        return {
            "entity_id": self.profile.agent_id,
            "location_id": self.current_location,
            "skills": {
                "perception": self.profile.trait("perception", 0.5),
            },
            "emotional_state": {
                "curiosity": self.profile.trait("curiosity", 0.5),
            },
        }
