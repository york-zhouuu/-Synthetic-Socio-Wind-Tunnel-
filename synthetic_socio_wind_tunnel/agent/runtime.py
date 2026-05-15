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

    from synthetic_socio_wind_tunnel.agent.operations.models import (
        OperationResult,
        PendingOp,
    )
    from synthetic_socio_wind_tunnel.agent.operations.pool import OperationPool
    from synthetic_socio_wind_tunnel.attention import AttentionService
    from synthetic_socio_wind_tunnel.conversation.dialogue_service import (
        DialogueService,
    )
    from synthetic_socio_wind_tunnel.engine.navigation import NavigationResult
    from synthetic_socio_wind_tunnel.memory.models import MemoryEvent
    from synthetic_socio_wind_tunnel.memory.service import MemoryService
    from synthetic_socio_wind_tunnel.orchestrator.models import TickContext
    from synthetic_socio_wind_tunnel.social_graph import SocialGraphService
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

    # social-graph-capability: optional reference to the shared graph; when
    # set, `familiar_with()` returns a strength-thresholded answer. When None,
    # `familiar_with()` returns False (no fallback to memory — that's
    # MemoryService's responsibility).
    social_graph: "SocialGraphService | None" = None

    # 逐步移动队列: agent 正在沿路径移动时，这里存放剩余的 location 序列
    _movement_queue: list[str] = field(default_factory=list)

    # 当前正在执行的 plan step (可能因移动中而跨多个 tick)
    _moving: bool = False

    # ---- realism-attention-rebalance ----
    # 决策日志：默认关，dev/inspector 路径打开。
    # publishable suite 30 seed × 14 day 跑动期间保持 False，避免内存膨胀。
    enable_replan_log: bool = False
    replan_decision_log: list[ReplanDecisionRecord] = field(default_factory=list)

    # ---- ai-town port (agent-stack-aitown-port) ----
    # Mirror ai-town's Agent state (convex/aiTown/agent.ts).
    #   inProgressOperation → pending_operation     (in-flight LLM op)
    #   inConversation       → current_dialogue_id  (active dialogue)
    #   toRemember           → to_remember          (dialogue_id awaiting summary)
    #   lastConversation     → last_dialogue_ended_tick (tick the last dialogue ended,
    #                                                    used by decision tree cooldown)
    # last_op_kind is a bookkeeping field used by metrics / inspector to attribute
    # the most-recent op cost to its kind without re-walking the OperationPool.
    # All mutations go through the dedicated set_/clear_ methods below — never via
    # `agent.pending_operation = ...` — so debug tooling can hook a single point.
    pending_operation: "PendingOp | None" = None
    current_dialogue_id: str | None = None
    to_remember: str | None = None
    last_dialogue_ended_tick: int | None = None
    last_op_kind: str | None = None

    # Feature flag: when True (typically only for protagonist agents),
    # AgentRuntime.step uses the ai-town decision tree (after task 18).
    # Default False so existing test fixtures and scripted agents stay
    # on the legacy plan-driven path. Population.sample_population sets
    # True for protagonists when use_aitown=True at sample time.
    use_aitown_decision_tree: bool = False

    # ai-town decision-tree injectables. None when not running the aitown
    # path; populated by orchestrator wiring for protagonists.
    dialogue_service: "DialogueService | None" = None
    operation_pool: "OperationPool | None" = None
    memory_service: "MemoryService | None" = None

    # ai-town port: per-agent RNG for invite accept/reject decisions
    # (1:1 with `Math.random() < INVITE_ACCEPT_PROBABILITY`). Seeded
    # deterministically from agent_id via __post_init__ so the same
    # agent in the same dialogue makes the same choice across replays.
    _invite_rng: random.Random | None = None

    # ai-town port: INVITE_ACCEPT_PROBABILITY constant (1:1 from constants.ts)
    invite_accept_probability: float = 0.8

    # OperationResults waiting to be drained at the next step(). The
    # orchestrator's on_tick_end_async hook (Phase E) calls
    # `consume_op_result(result)` once per agent per result. Drained at
    # the top of `_aitown_step`.
    _tick_inputs: list["OperationResult"] = field(default_factory=list)

    # Counter for stable per-agent op_id generation.
    _op_id_counter: int = 0

    # Hint feed that orchestrator may set between ticks; used when
    # building op args for `do_something`. Kept simple (mutable lists).
    nearby_hint: list[dict] = field(default_factory=list)
    candidate_destinations_hint: list[str] = field(default_factory=list)
    recent_memory_hint: list[str] = field(default_factory=list)

    # Buffer holding the most-recent do_something action that step()
    # decided to execute this tick. step() returns the corresponding
    # Intent and clears it.
    _pending_action: dict | None = None

    # add-walking-speed-budget: in-flight multi-tick walking state.
    # When orchestrator's _dispatch_move can't complete a long route in one
    # tick's distance budget (default 400m @ 80 m/min × 5 min), remaining
    # NavigationSteps are cached here so the next tick resumes from where
    # this tick stopped — agent keeps walking instead of teleporting.
    # Cleared when route exhausted or agent's plan target changes.
    _in_flight_route_remaining: list = field(default_factory=list)
    _in_flight_target: str | None = None

    def __post_init__(self) -> None:
        if not self.current_location:
            self.current_location = self.profile.home_location
        # ai-town port: deterministic per-agent RNG for invite gates
        if self._invite_rng is None:
            self._invite_rng = random.Random(
                hash(("invite", self.profile.agent_id)) & 0xFFFFFFFF
            )

    # ---- Snapshot (tick-level-resume 2026-05-16) ----

    def to_snapshot_state(self) -> dict:
        """Serialize all mutable runtime state to a JSON-safe dict.

        Excludes: `profile` (immutable identity, reconstructed from atlas),
        service references (`attention_service` / `memory_service` /
        `dialogue_service` / `operation_pool` / `social_graph` — reattached
        on resume by caller), and `_tick_inputs` (in-flight LLM results;
        abandoned per design D6).

        Includes: plan / current_location / movement / mood / ai-town
        per-agent state / hint feeds / per-agent RNG state.
        """
        from synthetic_socio_wind_tunnel.run_resilience.state_snapshot import (
            _rng_state_to_json,
        )
        rng_state: list | None = None
        if self._invite_rng is not None:
            rng_state = _rng_state_to_json(self._invite_rng.getstate())

        plan_dump: dict | None = None
        if self.plan is not None:
            plan_dump = self.plan.model_dump(mode="json") if hasattr(
                self.plan, "model_dump",
            ) else None

        pending_op = None
        if self.pending_operation is not None and hasattr(
            self.pending_operation, "model_dump",
        ):
            pending_op = self.pending_operation.model_dump(mode="json")

        return {
            "agent_id": self.profile.agent_id,
            "current_location": self.current_location,
            "plan": plan_dump,
            "movement": {
                "queue": list(self._movement_queue),
                "moving": self._moving,
                "in_flight_route_remaining": [
                    s.model_dump(mode="json") if hasattr(s, "model_dump") else s
                    for s in self._in_flight_route_remaining
                ],
                "in_flight_target": self._in_flight_target,
            },
            "ai_town": {
                "pending_operation": pending_op,
                "current_dialogue_id": self.current_dialogue_id,
                "to_remember": self.to_remember,
                "last_dialogue_ended_tick": self.last_dialogue_ended_tick,
                "last_op_kind": self.last_op_kind,
                "use_aitown_decision_tree": self.use_aitown_decision_tree,
                "invite_accept_probability": self.invite_accept_probability,
                "op_id_counter": self._op_id_counter,
            },
            "hints": {
                "nearby_hint": list(self.nearby_hint),
                "candidate_destinations_hint": list(self.candidate_destinations_hint),
                "recent_memory_hint": list(self.recent_memory_hint),
            },
            "enable_replan_log": self.enable_replan_log,
            "invite_rng_state": rng_state,
        }

    def from_snapshot_state(self, state: dict) -> None:
        """Restore mutable runtime state from a snapshot dict.

        Existing in-memory state is replaced (not merged). Service
        references (attention_service, memory_service, etc.) are NOT
        touched — caller reattaches them. `_tick_inputs` is cleared
        (in-flight ops abandoned per design D6).
        """
        from synthetic_socio_wind_tunnel.run_resilience.state_snapshot import (
            _rng_state_from_json,
        )
        if not isinstance(state, dict):
            raise ValueError(
                f"AgentRuntime.from_snapshot_state expects dict, "
                f"got {type(state).__name__}",
            )
        sid = state.get("agent_id")
        if sid is not None and sid != self.profile.agent_id:
            raise ValueError(
                f"AgentRuntime.from_snapshot_state: agent_id mismatch "
                f"(snapshot={sid!r}, profile={self.profile.agent_id!r})",
            )
        self.current_location = state.get("current_location", "") or self.profile.home_location
        # Plan
        plan_dump = state.get("plan")
        if plan_dump is None:
            self.plan = None
        else:
            self.plan = DailyPlan.model_validate(plan_dump)

        # Movement
        mv = state.get("movement", {}) or {}
        self._movement_queue = list(mv.get("queue", []) or [])
        self._moving = bool(mv.get("moving", False))
        self._in_flight_route_remaining = list(
            mv.get("in_flight_route_remaining", []) or []
        )
        self._in_flight_target = mv.get("in_flight_target")

        # ai-town
        at = state.get("ai_town", {}) or {}
        # pending_operation: rehydrate to PendingOp if SDK type is available
        pending = at.get("pending_operation")
        if pending is None:
            self.pending_operation = None
        else:
            try:
                from synthetic_socio_wind_tunnel.agent.operations.models import (
                    PendingOp,
                )
                self.pending_operation = PendingOp.model_validate(pending)
            except Exception:
                # If model can't be rehydrated (SDK type drift), abandon —
                # agent will re-trigger via normal path
                self.pending_operation = None
        self.current_dialogue_id = at.get("current_dialogue_id")
        self.to_remember = at.get("to_remember")
        self.last_dialogue_ended_tick = at.get("last_dialogue_ended_tick")
        self.last_op_kind = at.get("last_op_kind")
        self.use_aitown_decision_tree = bool(at.get("use_aitown_decision_tree", False))
        self.invite_accept_probability = float(at.get("invite_accept_probability", 0.8))
        self._op_id_counter = int(at.get("op_id_counter", 0))

        # Hints
        h = state.get("hints", {}) or {}
        self.nearby_hint = list(h.get("nearby_hint", []) or [])
        self.candidate_destinations_hint = list(h.get("candidate_destinations_hint", []) or [])
        self.recent_memory_hint = list(h.get("recent_memory_hint", []) or [])

        # Misc
        self.enable_replan_log = bool(state.get("enable_replan_log", False))

        # Per-agent invite RNG state
        rng_state = state.get("invite_rng_state")
        if rng_state is not None:
            if self._invite_rng is None:
                self._invite_rng = random.Random()
            try:
                self._invite_rng.setstate(_rng_state_from_json(rng_state))
            except Exception:
                # Drop snapshot RNG state silently — re-seed from agent_id
                self._invite_rng = random.Random(
                    hash(("invite", self.profile.agent_id)) & 0xFFFFFFFF,
                )

        # Drop in-flight LLM results (D6 abandon-and-retry)
        self._tick_inputs = []
        self._pending_action = None

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

        ai-town port (agent-stack-aitown-port Phase D task 18):
        if `use_aitown_decision_tree=True` and the agent is a protagonist,
        routes through `_aitown_step` (consumes tick_inputs, manages
        dialogue lifecycle + LLM op scheduling). Otherwise the legacy
        plan-driven step.
        """
        if self.use_aitown_decision_tree and self.profile.is_protagonist:
            return self._aitown_step(tick_ctx)
        return self._legacy_step(tick_ctx)

    def _legacy_step(self, tick_ctx: "TickContext") -> Intent:
        """Plan-driven step (pre-aitown behavior). All scripted agents
        and protagonists with `use_aitown_decision_tree=False` use this."""
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

    # --- ai-town decision tree (Phase D task 18) -----------------------

    def consume_op_result(self, result: "OperationResult") -> None:
        """Push an OperationResult into this agent's tick_inputs queue.

        The orchestrator's `on_tick_end_async` hook (Phase E) drains
        OperationPool.process_pending and calls this for every result that
        belongs to a given agent. The result is applied at the top of the
        next `_aitown_step` invocation.
        """
        self._tick_inputs.append(result)

    def _drain_tick_inputs(self) -> None:
        """Apply effects from any OperationResults received since last step.

        - generate_message → append message to current dialogue
        - remember_conversation → bridge_to_memory_and_propagation, clear to_remember
        - do_something → store action in `_pending_action` for this tick to translate
        - reflect → no-op here (MemoryService.maybe_reflect already wrote events)
        - score_importance → no-op here (importance written into memory event)

        After applying any result, clears `pending_operation` if the
        result matches the in-flight op id — agent is then free to
        schedule the next op next tick. Without this clear, agent waits
        for op `timeout_tick` (~24 ticks) before progressing → makes
        dialogue messaging painfully slow.
        """
        if not self._tick_inputs:
            return
        for result in self._tick_inputs:
            if not result.success:
                # Even failed ops should release the pending slot
                if (self.pending_operation is not None
                        and self.pending_operation.op_id == result.op_id):
                    self.clear_pending_op()
                continue
            if result.kind == "generate_message":
                self._apply_generate_message_result(result)
            elif result.kind == "remember_conversation":
                self._apply_remember_conversation_result(result)
            elif result.kind == "do_something":
                # Store the action; the decision tree will translate it
                # into an Intent this same tick.
                self._pending_action = dict(result.payload)
            # reflect / score_importance: no-op (handled inside MemoryService)

            # Release the pending slot now that the result is consumed.
            if (self.pending_operation is not None
                    and self.pending_operation.op_id == result.op_id):
                self.clear_pending_op()
        self._tick_inputs.clear()

    def _apply_generate_message_result(self, result: "OperationResult") -> None:
        """Append generated message into the agent's current dialogue.

        ai-town port: when `phase == "leave"`, also `dialogue_service.end()`
        the conversation (matches `agentSendMessage(leaveConversation: true)`
        in agent.ts:307-334) and stamp `to_remember` so the next tick
        triggers a remember_conversation op.
        """
        if self.dialogue_service is None:
            return
        d_id = result.payload.get("dialogue_id")
        speaker_id = result.payload.get("speaker_id", self.profile.agent_id)
        content = result.payload.get("content", "")
        phase = result.payload.get("phase", "continue")
        if not d_id or not content:
            import logging as _l
            _l.getLogger(__name__).warning(
                "[apply_msg] %s skipped (d_id=%r, content_len=%d)",
                speaker_id, d_id, len(content),
            )
            return
        d = self.dialogue_service.get(d_id)
        if d is None or d.ended_tick is not None:
            return
        if d.status != "participating":
            import logging as _l
            _l.getLogger(__name__).warning(
                "[apply_msg] %s skipped d=%s status=%s",
                speaker_id, d_id, d.status,
            )
            return
        # Append the message — this might auto-end the dialogue if
        # message_count crosses _max_messages, which is OK as a last-resort
        # fallback (ai-town has no such fallback; we keep it for safety).
        next_tick = d.last_message_tick + 1
        sim_time = d.started_at or datetime.min
        try:
            self.dialogue_service.append_message(
                d_id, speaker_id, content,
                tick=next_tick,
                simulated_time=sim_time,
            )
        except Exception:
            # If append fails (e.g. dialogue ended between scheduling and
            # arrival), drop the message silently — it's a stale result.
            return

        if phase == "leave":
            # ai-town leave path: explicitly end + queue remember.
            d_after = self.dialogue_service.get(d_id)
            if d_after is not None and d_after.ended_tick is None:
                try:
                    self.dialogue_service.end(
                        d_id, "leave",
                        tick=next_tick, simulated_time=sim_time,
                    )
                except Exception:
                    pass
            # Stamp to_remember so next step's branch 3 schedules it.
            if self.to_remember is None:
                self.mark_to_remember(d_id)
            # Clear current_dialogue_id so we don't re-enter dialogue branch.
            self.clear_dialogue_id(ended_tick=next_tick)

    def _apply_remember_conversation_result(self, result: "OperationResult") -> None:
        """Run bridge_to_memory_and_propagation now that summary is ready."""
        d_id = result.payload.get("dialogue_id")
        summary = result.payload.get("summary", "")
        if not d_id:
            return
        if self.dialogue_service is None or self.memory_service is None:
            return
        try:
            self.dialogue_service.bridge_to_memory_and_propagation(
                d_id,
                memory_service=self.memory_service,
                conversation_service=getattr(
                    self.memory_service, "_conversation", None,
                ),
                social_graph=getattr(
                    self.memory_service, "_social_graph", None,
                ),
                simulated_time=datetime.min,  # caller can override
                summary=summary,
            )
        except Exception:
            pass
        # Clear the to_remember marker — handled.
        if self.to_remember == d_id:
            self.clear_to_remember()

    def _aitown_step(self, tick_ctx: "TickContext") -> Intent:
        """ai-town's Agent.tick decision tree, ported.

        The 6 numbered branches mirror the spec (specs/agent/spec.md
        Requirement 'AgentRuntime.step 决策树'):
            1. consume tick_inputs
            2. pending op gate
            3. to_remember gate
            4. dialogue lifecycle
            5. plan-driven path (legacy)
            6. else schedule do_something
        """
        # 1. Consume any op results delivered between ticks.
        self._drain_tick_inputs()

        # If do_something result is pending, translate it to an Intent
        # and consume it in this tick.
        if self._pending_action is not None:
            action = self._pending_action
            self._pending_action = None
            intent = self._translate_action_to_intent(action, tick_ctx)
            if intent is not None:
                return intent
            # Falls through to other branches if translation didn't yield.

        tick = tick_ctx.tick_index

        # 2. Pending op gate — wait while LLM op is in flight (and not
        # timed out). When timed out, clear silently and continue.
        if self.pending_operation is not None:
            if tick < self.pending_operation.timeout_tick:
                return WaitIntent(reason="awaiting_op")
            # timed out; drop it
            self.clear_pending_op()

        # 3. to_remember — schedule remember_conversation op.
        if self.to_remember is not None:
            if self._schedule_remember_op(tick_ctx):
                return WaitIntent(reason="will_remember")
            # If we couldn't schedule (no pool / no dialogue), clear and continue.
            self.clear_to_remember()

        # 4. Dialogue lifecycle (1:1 ai-town Agent.tick conversation branch).
        if self.current_dialogue_id is not None and self.dialogue_service is not None:
            d = self.dialogue_service.get(self.current_dialogue_id)
            if d is not None:
                # Per-AGENT status (not derived dialogue status) — matches
                # ai-town's `member.status.kind` semantics where each
                # participant has independent state.
                my_status = d.member_status.get(self.profile.agent_id, "ended")

                # 4a. invited → ai-town: Math.random() < INVITE_ACCEPT_PROBABILITY
                #     auto-decide accept or reject (1:1 port of agent.ts:111-126).
                if my_status == "invited":
                    if self._invite_rng.random() < self.invite_accept_probability:
                        try:
                            self.dialogue_service.accept_invite(
                                self.current_dialogue_id,
                                self.profile.agent_id,
                            )
                        except Exception:
                            pass
                        return WaitIntent(reason="invite_accepted")
                    # Reject path
                    try:
                        self.dialogue_service.reject_invite(
                            self.current_dialogue_id,
                            self.profile.agent_id,
                            reason="random_decline",
                            tick=tick,
                            simulated_time=tick_ctx.simulated_time,
                        )
                    except Exception:
                        pass
                    self.clear_dialogue_id(ended_tick=tick)
                    return WaitIntent(reason="invite_rejected")

                # 4b. walking_over → MoveIntent toward partner location.
                if my_status == "walking_over":
                    if d.target_location_id:
                        return MoveIntent(to_location=d.target_location_id)
                    return WaitIntent(reason="walking_over")

                # 4c. participating → either compose / leave / listen.
                if my_status == "participating":
                    last_speaker = (
                        d.messages[-1].speaker_id if d.messages else None
                    )
                    is_my_turn = (
                        last_speaker != self.profile.agent_id
                        and not (
                            last_speaker is None
                            and self.profile.agent_id != d.initiator_id
                        )
                    )

                    # 4c-i. ai-town: too long / too many messages → schedule
                    # generate_message phase="leave" (1:1 agent.ts:191-207).
                    # We trigger one message EARLIER than the absolute cap so
                    # the leave message itself fits inside the cap.
                    msg_max = getattr(
                        self.dialogue_service, "_max_messages", 8,
                    )
                    dur_max = getattr(
                        self.dialogue_service, "_max_duration_minutes", 30,
                    )
                    over_msg = d.message_count() >= msg_max - 1
                    over_dur = (
                        d.started_at is not None
                        and (
                            tick_ctx.simulated_time - d.started_at
                        ).total_seconds() / 60.0 > dur_max - 5
                    )
                    if (over_msg or over_dur) and is_my_turn:
                        if self._schedule_generate_message_op(
                            d, tick_ctx, phase="leave",
                        ):
                            return WaitIntent(reason="composing_leave")
                        return WaitIntent(reason="composing_no_pool")

                    # 4c-ii. Normal turn dispatch.
                    if is_my_turn:
                        if self._schedule_generate_message_op(d, tick_ctx):
                            return WaitIntent(reason="composing")
                        return WaitIntent(reason="composing_no_pool")
                    return WaitIntent(reason="listening")

                # 4d. ended → mark to_remember, clear dialogue, fall through.
                if my_status == "ended" and d.ended_tick is not None:
                    if self.to_remember is None:
                        self.mark_to_remember(self.current_dialogue_id)
                    self.clear_dialogue_id(ended_tick=d.ended_tick or tick)

        # 5. Plan-driven step.
        intent = self._legacy_step(tick_ctx)

        # 6. If plan has no useful action and we have an op pool, ask LLM
        # to decide via do_something (avoid scheduling if a real plan step
        # is being executed).
        if (
            isinstance(intent, WaitIntent)
            and intent.reason in (
                "no_plan", "plan_exhausted", "move_no_destination",
            )
            and self.operation_pool is not None
        ):
            if self._schedule_do_something_op(tick_ctx):
                return WaitIntent(reason="reconsidering")
        return intent

    # --- Op scheduling helpers ----------------------------------------

    def _next_op_id(self, kind: str, tick: int) -> str:
        self._op_id_counter += 1
        return f"op_{self.profile.agent_id}_{kind}_{tick}_{self._op_id_counter}"

    def _schedule_op_safe(
        self, op: "PendingOp", *, handler_kwargs: dict | None = None,
    ) -> bool:
        """Schedule via OperationPool + mark pending. False if pool is busy."""
        if self.operation_pool is None:
            return False
        if self.pending_operation is not None:
            return False
        try:
            self.operation_pool.schedule(op, handler_kwargs=handler_kwargs)
        except Exception:
            return False
        self.set_pending_op(op)
        return True

    def _schedule_do_something_op(self, tick_ctx: "TickContext") -> bool:
        """Build args for do_something and schedule via OperationPool."""
        from synthetic_socio_wind_tunnel.agent.operations.models import PendingOp

        tick = tick_ctx.tick_index
        op = PendingOp(
            op_id=self._next_op_id("do_something", tick),
            agent_id=self.profile.agent_id,
            kind="do_something",
            created_tick=tick,
            timeout_tick=tick + 24,
            args={
                "agent_id": self.profile.agent_id,
                "agent_name": self.profile.name,
                "agent_identity": self.profile.identity_text,
                "agent_plan": self.profile.plan_text,
                "current_location_id": self.current_location,
                "current_time": tick_ctx.simulated_time.strftime("%H:%M"),
                "recent_memories": list(self.recent_memory_hint),
                "nearby_agents": list(self.nearby_hint),
                "candidate_destinations": list(self.candidate_destinations_hint),
                "model": self.profile.base_model,
            },
        )
        return self._schedule_op_safe(op)

    def _schedule_generate_message_op(
        self,
        dialogue,
        tick_ctx: "TickContext",
        *,
        phase: str | None = None,
    ) -> bool:
        """Build args for generate_message and schedule.

        Phase resolution (1:1 ai-town):
        - explicit `phase` arg wins (e.g. "leave" forced by tooLong gate)
        - else: "start" if dialogue has no messages else "continue"
        """
        from synthetic_socio_wind_tunnel.agent.operations.models import PendingOp

        speaker_id = self.profile.agent_id
        other_id = dialogue.other_participant(speaker_id)
        if phase is None:
            phase = "start" if not dialogue.messages else "continue"

        recent_msgs = [
            (msg.speaker_id, msg.content) for msg in dialogue.messages[-6:]
        ]
        tick = tick_ctx.tick_index
        op = PendingOp(
            op_id=self._next_op_id("generate_message", tick),
            agent_id=speaker_id,
            kind="generate_message",
            created_tick=tick,
            timeout_tick=tick + 24,
            args={
                "dialogue_id": dialogue.dialogue_id,
                "speaker_id": speaker_id,
                "other_agent_id": other_id,
                "speaker_name": self.profile.name,
                "other_name": other_id,  # caller may patch with real name
                "speaker_identity": self.profile.identity_text or "",
                "speaker_plan": self.profile.plan_text or "",
                "other_identity": None,
                "recent_messages": recent_msgs,
                "relevant_memories": list(self.recent_memory_hint),
                "phase": phase,
                "model": self.profile.base_model,
            },
        )
        return self._schedule_op_safe(op)

    def _schedule_remember_op(self, tick_ctx: "TickContext") -> bool:
        """Build args for remember_conversation and schedule."""
        from synthetic_socio_wind_tunnel.agent.operations.models import PendingOp

        d_id = self.to_remember
        if d_id is None or self.dialogue_service is None:
            return False
        d = self.dialogue_service.get(d_id)
        if d is None:
            return False
        speaker_id = self.profile.agent_id
        other_id = d.other_participant(speaker_id)
        messages = [(m.speaker_id, m.content) for m in d.messages]
        tick = tick_ctx.tick_index
        op = PendingOp(
            op_id=self._next_op_id("remember_conversation", tick),
            agent_id=speaker_id,
            kind="remember_conversation",
            created_tick=tick,
            timeout_tick=tick + 24,
            args={
                "dialogue_id": d_id,
                "speaker_id": speaker_id,
                "speaker_name": self.profile.name,
                "other_name": other_id,
                "messages": messages,
                "model": self.profile.base_model,
            },
        )
        return self._schedule_op_safe(op)

    def _translate_action_to_intent(
        self, action: dict, tick_ctx: "TickContext",
    ) -> Intent | None:
        """Convert a do_something result payload into a concrete Intent.

        Returns None if the action implies no immediate Intent change
        (e.g. invite_dialogue actually schedules a dialogue invite + waits).
        """
        kind = action.get("action")
        if kind == "go_to":
            dest = action.get("destination_id")
            if dest:
                return MoveIntent(to_location=dest)
        elif kind == "invite_dialogue":
            target = action.get("target_agent_id")
            if (
                target
                and self.dialogue_service is not None
                and self.current_dialogue_id is None
            ):
                try:
                    d = self.dialogue_service.schedule_invite(
                        self.profile.agent_id, target,
                        self.current_location,
                        tick=tick_ctx.tick_index,
                        simulated_time=tick_ctx.simulated_time,
                    )
                    self.set_dialogue_id(d.dialogue_id)
                except Exception:
                    pass
            return WaitIntent(reason="invited_dialogue")
        elif kind == "activity":
            return WaitIntent(
                reason=str(action.get("activity") or "activity"),
            )
        elif kind == "wait":
            return WaitIntent(reason="aitown_wait")
        return None

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

    # --- ai-town state mutators (agent-stack-aitown-port) ---
    #
    # Always mutate via these methods; never `agent.pending_operation = x`.
    # Single-point invariant enforcement (e.g. set_pending_op refuses to
    # overwrite an in-flight op without explicit force; debug log hookable).

    def set_pending_op(self, op: "PendingOp", *, force: bool = False) -> None:
        """Mark `op` as the agent's in-flight LLM operation.

        ai-town parallel: Agent.startOperation. Per-agent there is at most
        ONE pending op at a time — running another while one is in-flight
        is a logic error caught here.

        Raises RuntimeError if a pending op already exists and `force=False`.
        """
        if self.pending_operation is not None and not force:
            raise RuntimeError(
                f"agent {self.profile.agent_id!r} already has pending op "
                f"{self.pending_operation.op_id!r} (kind={self.pending_operation.kind!r}); "
                f"clear it before scheduling another, or pass force=True"
            )
        self.pending_operation = op
        self.last_op_kind = op.kind

    def clear_pending_op(self) -> "PendingOp | None":
        """Clear the in-flight op (after handler returns). Returns the
        cleared op (for caller introspection) or None if there was none."""
        op = self.pending_operation
        self.pending_operation = None
        return op

    def set_dialogue_id(self, dialogue_id: str) -> None:
        """Mark agent as in this active dialogue (after invite accepted)."""
        if self.current_dialogue_id is not None and self.current_dialogue_id != dialogue_id:
            raise RuntimeError(
                f"agent {self.profile.agent_id!r} already in dialogue "
                f"{self.current_dialogue_id!r}; cannot enter {dialogue_id!r}"
            )
        self.current_dialogue_id = dialogue_id

    def clear_dialogue_id(self, *, ended_tick: int | None = None) -> str | None:
        """Clear current dialogue. If `ended_tick` provided, also stamps
        last_dialogue_ended_tick (used by decision-tree cooldown gating).
        Returns the cleared id."""
        d_id = self.current_dialogue_id
        self.current_dialogue_id = None
        if ended_tick is not None:
            self.last_dialogue_ended_tick = ended_tick
        return d_id

    def mark_to_remember(self, dialogue_id: str) -> None:
        """Queue a dialogue_id for next-tick remember_conversation op.

        ai-town: Agent.toRemember is set when leave/end fires, then the next
        tick reads it and runs rememberConversation. Same shape here.
        """
        self.to_remember = dialogue_id

    def clear_to_remember(self) -> str | None:
        """Pop the queued remember dialogue_id (consumed by handler)."""
        d_id = self.to_remember
        self.to_remember = None
        return d_id

    # --- 社交图查询 (social-graph-capability) ---

    def familiar_with(
        self, other_agent_id: str, threshold: float = 0.1,
    ) -> bool:
        """是否与 other_agent_id 有 strength > threshold 的 tie。

        薄封装；O(1)；MUST NOT 调 LLM。social_graph=None 时返回 False。
        """
        if self.social_graph is None:
            return False
        tie = self.social_graph.get_tie(self.profile.agent_id, other_agent_id)
        if tie is None:
            return False
        return tie.strength > threshold

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
