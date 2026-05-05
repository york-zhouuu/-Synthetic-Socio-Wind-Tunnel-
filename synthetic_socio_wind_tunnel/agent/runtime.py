"""AgentRuntime — 单个 agent 的运行时封装。

管理一个 agent 在模拟中的状态：当前计划、移动队列、感知上下文。
Orchestrator 通过 AgentRuntime 来驱动 agent 行为。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from .intent import Intent, MoveIntent, WaitIntent
from .planner import DailyPlan, PlanStep

if TYPE_CHECKING:
    from typing import Sequence

    from synthetic_socio_wind_tunnel.attention import AttentionService
    from synthetic_socio_wind_tunnel.engine.navigation import NavigationResult
    from synthetic_socio_wind_tunnel.memory.models import MemoryEvent
    from synthetic_socio_wind_tunnel.orchestrator.models import TickContext
    from .profile import AgentProfile


# ---------------------------------------------------------------------------
# Replan 决策记录（realism-attention-rebalance）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplanDecisionRecord:
    """单次 should_replan 调用的可追溯快照（入参 + 阈值各项 + 决策结果）。

    仅在 `AgentRuntime.enable_replan_log = True` 时累积。Inspector payload
    导出时把它写入 JSON，便于解释每个 True / False 决策为什么这么走。
    """

    agent_id: str
    tick: int
    simulated_time: datetime
    candidate_kind: str
    candidate_urgency: float
    threshold_computed: float
    base_components: dict[str, float]
    context_modifier: float
    replan_count_today: int
    rng_roll: float
    decision: bool


@dataclass(frozen=True)
class NearbyAgent:
    """Replan prompt 中"周围"信号的最小记录单元。

    不暴露具体 agent_id（避免 prompt 反向影响 LLM 通过 id 串去推断身份）；
    只承载 LLM 决策需要的 familiar / stranger 标签。
    """

    is_familiar: bool


@dataclass
class AgentRuntime:
    """单个 agent 的运行时状态。"""

    profile: AgentProfile
    plan: DailyPlan | None = None
    current_location: str = ""

    # Optional digital attention channel integration (realign-to-social-thesis).
    # When set, build_observer_context() composes AttentionState into
    # ObserverContext.digital_state. When None, behavior matches Phase 1.
    attention_service: "AttentionService | None" = None

    # 逐步移动队列: agent 正在沿路径移动时，这里存放剩余的 location 序列
    _movement_queue: list[str] = field(default_factory=list)

    # 当前正在执行的 plan step (可能因移动中而跨多个 tick)
    _moving: bool = False

    # ---- realism-attention-rebalance ----
    # 决策日志：默认关，dev/inspector 路径打开。
    # publishable suite 30 seed × 14 day 跑动期间保持 False，避免内存膨胀。
    enable_replan_log: bool = False
    replan_decision_log: list[ReplanDecisionRecord] = field(default_factory=list)

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

    # --- Intent (orchestrator 驱动入口) ---

    def step(self, tick_ctx: "TickContext") -> Intent:
        """
        orchestrator 每 tick 调一次，返回当前 agent 本 tick 的 Intent。

        职责：
        - 自动 advance plan（时间窗过期时）
        - 按 plan.current().action 映射到 Intent（本 change 只产 Move/Wait）
        - 不写 Ledger、不调 LLM、不 mutate observer_context

        见 openspec/specs/agent/spec.md "AgentRuntime.step 产出本 tick 的 Intent"
        """
        if self.plan is None:
            return WaitIntent(reason="no_plan")

        # 1. 自动 advance — 循环处理（若多个 step 同时过期一次性跳过）
        while self._current_step_expired(tick_ctx.simulated_time):
            advanced = self.plan.advance()
            if advanced is None:
                return WaitIntent(reason="plan_exhausted")

        current = self.plan.current()
        if current is None:
            return WaitIntent(reason="plan_exhausted")

        # 2. 到达 destination 但 step 时间窗未过 → 等
        if current.action == "move":
            if current.destination and self.current_location == current.destination:
                return WaitIntent(reason="at_destination")
            if current.destination:
                return MoveIntent(to_location=current.destination)
            # move 但没指定 destination：当 wait
            return WaitIntent(reason="move_no_destination")

        # 3. 其它 action → WaitIntent（本 change 不产 Examine/Pickup/...）
        return WaitIntent(reason=current.activity or current.action or "unspecified")

    def _current_step_expired(self, simulated_time: datetime) -> bool:
        """检查 plan.current() 的时间窗是否已过。plan 耗尽时返回 False。"""
        if self.plan is None:
            return False
        step = self.plan.current()
        if step is None:
            return False
        step_start = self._parse_step_time(step.time, simulated_time)
        if step_start is None:
            return False  # 不可解析则不 advance（保守）
        step_end = step_start + timedelta(minutes=step.duration_minutes)
        return simulated_time >= step_end

    @staticmethod
    def _parse_step_time(time_str: str, reference: datetime) -> datetime | None:
        """把 "7:00" / "07:00" 等 step.time 解析为 reference 当天的 datetime。"""
        if not time_str:
            return None
        try:
            hour_str, minute_str = time_str.split(":", 1)
            hour = int(hour_str)
            minute = int(minute_str)
        except (ValueError, AttributeError):
            return None
        if not (0 <= hour < 24 and 0 <= minute < 60):
            return None
        return reference.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # --- 当前 step 计时 (realism-attention-rebalance) ---

    def current_step_elapsed_min(self, simulated_time: datetime) -> float:
        """当前 step 已执行多少分钟（基于 step.time + duration_minutes 的逻辑窗口）。

        - 计算方式：simulated_time - parse_step_time(step.time, simulated_time)
        - step 不可解析 / plan 为空 → 返回 0.0
        - 负值（agent 还未到达 step 的逻辑开始时刻）截到 0.0
        """
        if self.plan is None:
            return 0.0
        step = self.plan.current()
        if step is None or not step.time:
            return 0.0
        step_start = self._parse_step_time(step.time, simulated_time)
        if step_start is None:
            return 0.0
        delta = (simulated_time - step_start).total_seconds() / 60.0
        return max(0.0, delta)

    # --- Replan 决策 (memory change + realism-attention-rebalance) ---

    def should_replan(
        self,
        memory_view: "Sequence[MemoryEvent]",
        candidate: "MemoryEvent",
        *,
        current_step: PlanStep | None = None,
        current_step_elapsed_min: float = 0.0,
        replan_count_today: int = 0,
        rng: random.Random | None = None,
        tick: int | None = None,
        simulated_time: datetime | None = None,
    ) -> bool:
        """决定是否对 `candidate` 事件触发 replan。

        **纯代码规则**，MUST NOT 调 LLM。

        realism-attention-rebalance 重写：
        - 综合 6 维 personality（routine_adherence / curiosity / openness /
          conscientiousness / risk_tolerance / extraversion）
        - context modifier：当前 step 已投入超过 30% duration 时阈值升高
        - 疲劳衰减：当日 replan 次数累加，阈值升高
        - 概率门：rng.random() + (urgency - threshold) > 0，避免硬阈值导致
          "全 0 / 全 1"
        - 决策日志：enable_replan_log=True 时追加 ReplanDecisionRecord

        规则适用 kind ∈ {"notification", "task_received"}；其它 kind 仍 False。
        """
        # 仅 notification 类事件参与 replan 判定
        if candidate.kind not in ("notification", "task_received"):
            return False

        p = self.profile.personality
        # 6 维 personality 各项贡献。base + 系数由 design D2 拍定，并通过
        # tests/test_agent_should_replan.py + e2e goldilocks band 校准：
        # 中性 personality + urgency=0.6 → 触发率约 12%（落入 [5%, 15%]）。
        components = {
            "base": 1.55,
            "routine_adherence": +0.30 * p.routine_adherence,
            "curiosity": -0.30 * p.curiosity,
            "openness": -0.15 * p.openness,
            "conscientiousness": +0.15 * p.conscientiousness,
            "risk_tolerance": -0.10 * p.risk_tolerance,
            "extraversion": -0.05 * p.extraversion,
        }
        # context modifier：已投入活动者更难被拉走
        context_modifier = 0.0
        if current_step is not None and current_step.duration_minutes > 0:
            elapsed_ratio = current_step_elapsed_min / max(
                1.0, float(current_step.duration_minutes)
            )
            if elapsed_ratio > 0.3:
                context_modifier = 0.15

        # 疲劳衰减：今日累计 replan 次数
        fatigue = 0.10 * replan_count_today

        threshold = sum(components.values()) + context_modifier + fatigue
        # 阈值 clamp 到 [0, 3.0]
        threshold = max(0.0, min(3.0, threshold))

        rng_obj = rng if rng is not None else random
        rng_roll = rng_obj.random()
        decision = (rng_roll + (candidate.urgency - threshold)) > 0

        if self.enable_replan_log:
            self.replan_decision_log.append(ReplanDecisionRecord(
                agent_id=self.profile.agent_id,
                tick=tick if tick is not None else -1,
                simulated_time=simulated_time or datetime.min,
                candidate_kind=candidate.kind,
                candidate_urgency=candidate.urgency,
                threshold_computed=threshold,
                base_components=dict(components),
                context_modifier=context_modifier + fatigue,
                replan_count_today=replan_count_today,
                rng_roll=rng_roll,
                decision=decision,
            ))

        return decision

    # --- 感知上下文构建 ---

    def build_observer_context(self) -> dict:
        """构建用于 PerceptionPipeline.render() 的 ObserverContext 参数。

        返回 dict 形式，调用方用 ObserverContext(**ctx) 构造。

        若注入了 attention_service：把 pending_for(agent_id) 与 profile.digital
        合成为 AttentionState，写入 digital_state 键。未注入时 digital_state 缺省
        为 None，行为与 Phase 1 一致。
        """
        from .personality import EmotionalState, Skills

        # 把 profile.personality（稳定人格）投射为 Skills / EmotionalState
        # （当下感知 / 情绪）。Skills.perception 直接承接稳定维度；
        # EmotionalState.curiosity 初值取 trait 的一半（当下感受 < 稳定倾向）。
        ctx: dict = {
            "entity_id": self.profile.agent_id,
            "location_id": self.current_location,
            "skills": Skills(
                perception=self.profile.personality.openness,
                investigation=self.profile.personality.curiosity,
            ),
            "emotional_state": EmotionalState(
                curiosity=self.profile.personality.curiosity * 0.5,
                anxiety=self.profile.personality.neuroticism * 0.5,
            ),
        }
        if self.attention_service is not None:
            from synthetic_socio_wind_tunnel.attention.models import AttentionState

            pending = self.attention_service.pending_for(self.profile.agent_id)
            ctx["digital_state"] = AttentionState(
                attention_target="physical_world",
                screen_time_hours_today=self.profile.digital.daily_screen_hours,
                pending_notifications=pending,
                notification_responsiveness=self.profile.digital.notification_responsiveness,
            )
        return ctx
