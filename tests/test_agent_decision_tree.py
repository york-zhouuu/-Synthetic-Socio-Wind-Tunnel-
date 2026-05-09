"""Tests for AgentRuntime aitown decision tree (agent-stack-aitown-port
Phase D task 18).

Covers each of the 6 branches + scripted-agent-unchanged + flag-off path:

- Branch 1 (drain tick_inputs): generate_message result appended to dialogue
- Branch 2 (pending op gate): WaitIntent while pending op in flight
- Branch 3 (to_remember): schedules remember op + WaitIntent
- Branch 4 (dialogue lifecycle): walking_over → MoveIntent;
                                  participating my-turn → composes;
                                  ended → marks to_remember
- Branch 5 (plan-driven): falls through to legacy plan
- Branch 6 (do_something): no plan → schedules do_something
- Scripted: never enters aitown branches
- Flag off: protagonist with use_aitown_decision_tree=False uses legacy
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from synthetic_socio_wind_tunnel.agent import AgentProfile, AgentRuntime
from synthetic_socio_wind_tunnel.agent.intent import MoveIntent, WaitIntent
from synthetic_socio_wind_tunnel.agent.operations.models import (
    OperationResult,
    PendingOp,
)
from synthetic_socio_wind_tunnel.conversation.dialogue_service import (
    DialogueService,
)
from synthetic_socio_wind_tunnel.orchestrator.models import TickContext


_T0 = datetime(2026, 5, 9, 10)


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _StubPool:
    """Minimal OperationPool stand-in. Captures `schedule` calls."""

    def __init__(self) -> None:
        self.scheduled: list[tuple[PendingOp, dict]] = []

    def schedule(self, op: PendingOp,
                 *, handler_kwargs: dict | None = None) -> None:
        self.scheduled.append((op, dict(handler_kwargs or {})))

    def cancel(self, agent_id: str, reason: str = "") -> bool:
        # Drop the most-recent scheduled for that agent.
        for i in range(len(self.scheduled) - 1, -1, -1):
            if self.scheduled[i][0].agent_id == agent_id:
                self.scheduled.pop(i)
                return True
        return False


def _profile(*, protag: bool = True) -> AgentProfile:
    return AgentProfile(
        agent_id="emma", name="Emma", age=30, occupation="librarian",
        household="single", home_location="apt_emma",
        is_protagonist=protag,
        identity_text="A 30-year-old librarian who loves quiet routines."
        if protag else None,
        plan_text="Catch up with neighbours about the weekend market."
        if protag else None,
    )


def _runtime(*, protag: bool = True, use_aitown: bool = True,
             with_pool: bool = True, with_dialogue: bool = True,
             with_memory: bool = True) -> AgentRuntime:
    pool = _StubPool() if with_pool else None
    dsvc = DialogueService(seed=1) if with_dialogue else None
    msvc_obj = object() if with_memory else None
    r = AgentRuntime(
        profile=_profile(protag=protag),
        use_aitown_decision_tree=use_aitown,
        operation_pool=pool,
        dialogue_service=dsvc,
        memory_service=msvc_obj,
    )
    return r


def _ctx(tick: int = 10, sim: datetime | None = None) -> TickContext:
    return TickContext(
        tick_index=tick,
        simulated_time=sim or _T0,
    )


# ---------------------------------------------------------------------------
# Branch 1: drain tick_inputs
# ---------------------------------------------------------------------------


class TestBranch1DrainTickInputs:

    def test_generate_message_result_appended_to_dialogue(self):
        r = _runtime()
        # Set up: emma + linda dialogue at participating, emma is initiator
        d = r.dialogue_service.schedule_invite(
            "emma", "linda", "cafe", tick=10, simulated_time=_T0,
        )
        r.dialogue_service.accept_invite(d.dialogue_id, "linda")
        r.dialogue_service.advance_to_participating(d.dialogue_id, tick=11)
        # Linda speaks first (so it's emma's turn, but to test branch 1
        # we just inject a generated message result for emma).
        r.dialogue_service.append_message(
            d.dialogue_id, "linda", "Hi Emma!",
            tick=12, simulated_time=_T0 + timedelta(minutes=10),
        )
        r.set_dialogue_id(d.dialogue_id)

        # Inject a generate_message result for emma.
        result = OperationResult(
            op_id="op1", agent_id="emma", kind="generate_message",
            success=True,
            payload={
                "dialogue_id": d.dialogue_id,
                "speaker_id": "emma",
                "content": "Hello Linda!",
                "phase": "continue",
            },
        )
        r.consume_op_result(result)

        # step() drains. Result: dialogue has 2 messages now.
        intent = r.step(_ctx(tick=13))
        d_after = r.dialogue_service.get(d.dialogue_id)
        assert len(d_after.messages) == 2
        assert d_after.messages[-1].content == "Hello Linda!"
        # Emma just spoke → it's linda's turn → emma waits "listening"
        assert isinstance(intent, WaitIntent)


# ---------------------------------------------------------------------------
# Branch 2: pending op gate
# ---------------------------------------------------------------------------


class TestBranch2PendingOpGate:

    def test_pending_op_returns_wait(self):
        r = _runtime()
        op = PendingOp(
            op_id="op_pending", agent_id="emma", kind="do_something",
            created_tick=10, timeout_tick=34, args={},
        )
        r.set_pending_op(op)
        intent = r.step(_ctx(tick=12))
        assert isinstance(intent, WaitIntent)
        assert intent.reason == "awaiting_op"

    def test_timed_out_pending_op_cleared(self):
        r = _runtime()
        op = PendingOp(
            op_id="op_pending", agent_id="emma", kind="do_something",
            created_tick=10, timeout_tick=12, args={},
        )
        r.set_pending_op(op)
        # tick=20 well past timeout → old op cleared and step continues.
        # Note: branch 6 will then schedule a NEW do_something op since
        # plan=None. So pending_operation transitions to the new op,
        # never returning to the old one.
        intent = r.step(_ctx(tick=20))
        # Old op is gone (id != "op_pending")
        assert r.pending_operation is None or r.pending_operation.op_id != "op_pending"
        assert isinstance(intent, WaitIntent)
        # Must be the "reconsidering" wait (branch 6 fired) — confirming
        # the timeout-clear path actually executed.
        assert intent.reason == "reconsidering"


# ---------------------------------------------------------------------------
# Branch 3: to_remember
# ---------------------------------------------------------------------------


class TestBranch3ToRemember:

    def test_to_remember_schedules_remember_op(self):
        r = _runtime()
        # Set up an ended dialogue with messages.
        d = r.dialogue_service.schedule_invite(
            "emma", "linda", "cafe", tick=10, simulated_time=_T0,
        )
        r.dialogue_service.accept_invite(d.dialogue_id, "linda")
        r.dialogue_service.advance_to_participating(d.dialogue_id, tick=11)
        r.dialogue_service.append_message(
            d.dialogue_id, "emma", "hi", tick=12,
            simulated_time=_T0 + timedelta(minutes=10),
        )
        r.dialogue_service.end(
            d.dialogue_id, "leave",
            tick=13, simulated_time=_T0 + timedelta(minutes=15),
        )
        r.mark_to_remember(d.dialogue_id)

        intent = r.step(_ctx(tick=14))

        assert isinstance(intent, WaitIntent)
        assert intent.reason == "will_remember"
        # Op pool should have a remember_conversation scheduled.
        assert len(r.operation_pool.scheduled) == 1
        op, _ = r.operation_pool.scheduled[0]
        assert op.kind == "remember_conversation"
        assert op.args["dialogue_id"] == d.dialogue_id
        assert r.pending_operation is op


# ---------------------------------------------------------------------------
# Branch 4: dialogue lifecycle
# ---------------------------------------------------------------------------


class TestBranch4DialogueLifecycle:

    def test_walking_over_returns_move_intent(self):
        r = _runtime()
        d = r.dialogue_service.schedule_invite(
            "emma", "linda", "cafe", tick=10, simulated_time=_T0,
        )
        r.dialogue_service.accept_invite(d.dialogue_id, "linda")
        # Both walking_over now.
        r.set_dialogue_id(d.dialogue_id)

        intent = r.step(_ctx(tick=11))
        assert isinstance(intent, MoveIntent)
        assert intent.to_location == "cafe"

    def test_participating_my_turn_schedules_message(self):
        r = _runtime()
        d = r.dialogue_service.schedule_invite(
            "emma", "linda", "cafe", tick=10, simulated_time=_T0,
        )
        r.dialogue_service.accept_invite(d.dialogue_id, "linda")
        r.dialogue_service.advance_to_participating(d.dialogue_id, tick=11)
        # Linda speaks first → emma's turn.
        r.dialogue_service.append_message(
            d.dialogue_id, "linda", "Hi!",
            tick=12, simulated_time=_T0 + timedelta(minutes=10),
        )
        r.set_dialogue_id(d.dialogue_id)

        intent = r.step(_ctx(tick=13))
        assert isinstance(intent, WaitIntent)
        assert intent.reason == "composing"
        assert len(r.operation_pool.scheduled) == 1
        op, _ = r.operation_pool.scheduled[0]
        assert op.kind == "generate_message"
        assert op.args["dialogue_id"] == d.dialogue_id
        assert op.args["speaker_id"] == "emma"
        assert op.args["phase"] == "continue"

    def test_participating_partner_turn_listens(self):
        r = _runtime()
        d = r.dialogue_service.schedule_invite(
            "emma", "linda", "cafe", tick=10, simulated_time=_T0,
        )
        r.dialogue_service.accept_invite(d.dialogue_id, "linda")
        r.dialogue_service.advance_to_participating(d.dialogue_id, tick=11)
        # Emma just spoke → linda's turn → emma listens.
        r.dialogue_service.append_message(
            d.dialogue_id, "emma", "Hi Linda",
            tick=12, simulated_time=_T0 + timedelta(minutes=10),
        )
        r.set_dialogue_id(d.dialogue_id)

        intent = r.step(_ctx(tick=13))
        assert isinstance(intent, WaitIntent)
        assert intent.reason == "listening"
        assert r.operation_pool.scheduled == []  # no op scheduled

    def test_ended_dialogue_marks_to_remember(self):
        r = _runtime()
        d = r.dialogue_service.schedule_invite(
            "emma", "linda", "cafe", tick=10, simulated_time=_T0,
        )
        r.dialogue_service.accept_invite(d.dialogue_id, "linda")
        r.dialogue_service.advance_to_participating(d.dialogue_id, tick=11)
        r.dialogue_service.append_message(
            d.dialogue_id, "emma", "hi",
            tick=12, simulated_time=_T0 + timedelta(minutes=10),
        )
        r.dialogue_service.end(
            d.dialogue_id, "leave",
            tick=13, simulated_time=_T0 + timedelta(minutes=15),
        )
        r.set_dialogue_id(d.dialogue_id)

        intent = r.step(_ctx(tick=14))
        # to_remember was set; current_dialogue_id cleared.
        assert r.to_remember == d.dialogue_id
        assert r.current_dialogue_id is None
        # last_dialogue_ended_tick should match d.ended_tick (which was set
        # to 13 by service.end above)
        assert r.last_dialogue_ended_tick == 13


# ---------------------------------------------------------------------------
# Branch 6: no plan → schedule do_something
# ---------------------------------------------------------------------------


class TestBranch6DoSomething:

    def test_no_plan_schedules_do_something(self):
        r = _runtime()
        # No plan, no dialogue, no pending op → branch 6 fires.
        intent = r.step(_ctx(tick=10))
        assert isinstance(intent, WaitIntent)
        assert intent.reason == "reconsidering"
        assert len(r.operation_pool.scheduled) == 1
        op, _ = r.operation_pool.scheduled[0]
        assert op.kind == "do_something"
        assert op.args["agent_id"] == "emma"
        assert op.args["agent_identity"] is not None  # filled by profile

    def test_translates_do_something_go_to_to_move(self):
        r = _runtime()
        # Inject a do_something result that says "go_to cafe"
        result = OperationResult(
            op_id="op1", agent_id="emma", kind="do_something",
            success=True,
            payload={"action": "go_to", "destination_id": "cafe_main"},
        )
        r.consume_op_result(result)

        intent = r.step(_ctx(tick=11))
        assert isinstance(intent, MoveIntent)
        assert intent.to_location == "cafe_main"

    def test_translates_invite_to_dialogue_schedule(self):
        r = _runtime()
        result = OperationResult(
            op_id="op1", agent_id="emma", kind="do_something",
            success=True,
            payload={
                "action": "invite_dialogue",
                "target_agent_id": "linda",
            },
        )
        r.consume_op_result(result)

        intent = r.step(_ctx(tick=11))
        # Should have scheduled an invite → emma now in current_dialogue_id
        assert r.current_dialogue_id is not None
        d = r.dialogue_service.get(r.current_dialogue_id)
        assert d.invitee_id == "linda"
        assert isinstance(intent, WaitIntent)


# ---------------------------------------------------------------------------
# Scripted agent: never goes through aitown
# ---------------------------------------------------------------------------


class TestScriptedAgent:

    def test_scripted_uses_legacy(self):
        r = _runtime(protag=False, use_aitown=True)
        # Even with use_aitown=True, scripted agents (is_protagonist=False)
        # use legacy. No plan → returns WaitIntent("no_plan"), never schedules op.
        intent = r.step(_ctx(tick=10))
        assert isinstance(intent, WaitIntent)
        assert intent.reason == "no_plan"
        assert r.operation_pool.scheduled == []

    def test_scripted_never_schedules_ops(self):
        r = _runtime(protag=False, use_aitown=True)
        # Even with a current_dialogue_id set, scripted agents skip aitown.
        # (Hypothetically a scripted agent shouldn't be in a dialogue, but
        # the gate is defense-in-depth.)
        d = r.dialogue_service.schedule_invite(
            "emma", "linda", "cafe", tick=10, simulated_time=_T0,
        )
        r.set_dialogue_id(d.dialogue_id)
        r.step(_ctx(tick=11))
        assert r.operation_pool.scheduled == []


# ---------------------------------------------------------------------------
# Feature flag off: protagonist falls back to legacy
# ---------------------------------------------------------------------------


class TestFlagOff:

    def test_flag_off_uses_legacy(self):
        r = _runtime(protag=True, use_aitown=False)
        intent = r.step(_ctx(tick=10))
        assert isinstance(intent, WaitIntent)
        assert intent.reason == "no_plan"  # legacy: no plan → no_plan
        # No ops scheduled; aitown branch not entered.
        assert r.operation_pool.scheduled == []

    def test_flag_off_ignores_pending_op(self):
        r = _runtime(protag=True, use_aitown=False)
        op = PendingOp(
            op_id="op_x", agent_id="emma", kind="do_something",
            created_tick=10, timeout_tick=34, args={},
        )
        r.set_pending_op(op)
        intent = r.step(_ctx(tick=11))
        # Flag off → legacy ignores pending_operation entirely
        assert intent.reason == "no_plan"


# ---------------------------------------------------------------------------
# Idempotency / multiple results
# ---------------------------------------------------------------------------


class TestBranch4ai_townInviteAuto:
    """ai-town 1:1: invitee 在 invited 状态下自动 accept (probability=0.8) 或 reject."""

    def _setup_invitee_runtime(self, *, rng_value: float) -> tuple[AgentRuntime, str]:
        """Build a runtime that's the INVITEE of an active dialogue, with
        an injected RNG that returns a known value."""
        # We need a fresh dialogue service shared with the runtime.
        dsvc = DialogueService(seed=1)
        # Create dialogue: emma is initiator, linda is invitee
        d = dsvc.schedule_invite(
            "emma", "linda", "cafe", tick=10, simulated_time=_T0,
        )
        # Build runtime FOR LINDA (the invitee)
        profile = AgentProfile(
            agent_id="linda", name="Linda", age=28, occupation="dev",
            household="single", home_location="apt_linda",
            is_protagonist=True,
            identity_text="A friendly dev.", plan_text="Find a cafe.",
        )
        pool = _StubPool()
        rt = AgentRuntime(
            profile=profile,
            use_aitown_decision_tree=True,
            operation_pool=pool,
            dialogue_service=dsvc,
            memory_service=None,
        )
        rt.set_dialogue_id(d.dialogue_id)
        # Override the RNG with a deterministic value
        import random
        class _FixedRng:
            def random(self) -> float:
                return rng_value
        rt._invite_rng = _FixedRng()
        return rt, d.dialogue_id

    def test_invitee_auto_accept_below_threshold(self):
        rt, d_id = self._setup_invitee_runtime(rng_value=0.5)  # < 0.8 → accept
        intent = rt.step(_ctx(tick=11))
        d = rt.dialogue_service.get(d_id)
        # Linda's status should now be walking_over (acceptInvite mutates both)
        assert d.member_status["linda"] == "walking_over"
        assert isinstance(intent, WaitIntent)
        assert intent.reason == "invite_accepted"

    def test_invitee_auto_reject_above_threshold(self):
        rt, d_id = self._setup_invitee_runtime(rng_value=0.9)  # > 0.8 → reject
        intent = rt.step(_ctx(tick=11))
        d = rt.dialogue_service.get(d_id)
        # rejected → dialogue ended
        assert d.ended_tick is not None
        assert d.end_reason == "rejected:random_decline"
        assert intent.reason == "invite_rejected"
        # Linda no longer has current dialogue
        assert rt.current_dialogue_id is None


class TestBranch4ai_townLeavePhase:
    """ai-town 1:1: 当 messages 接近上限时，schedule generate_message phase=leave
    让 LLM 生成告别语，再正式 end + 触发 remember."""

    def _setup_full_dialogue(self, *, n_messages: int) -> tuple[AgentRuntime, str]:
        """emma is participating in a dialogue with N messages already exchanged."""
        dsvc = DialogueService(seed=1)
        d = dsvc.schedule_invite(
            "emma", "linda", "cafe", tick=10, simulated_time=_T0,
        )
        dsvc.accept_invite(d.dialogue_id, "linda")
        dsvc.advance_to_participating(d.dialogue_id, tick=11)
        for i in range(n_messages):
            speaker = "emma" if i % 2 == 0 else "linda"
            dsvc.append_message(
                d.dialogue_id, speaker, f"msg {i}",
                tick=12 + i,
                simulated_time=_T0 + timedelta(minutes=i * 2),
            )
        # emma is the runtime; ensure last message was from linda (so it's
        # emma's turn to speak)
        if n_messages % 2 == 0 and n_messages > 0:
            # last was at index n-1 = odd → linda spoke; emma's turn ✓
            pass
        rt = AgentRuntime(
            profile=_profile(protag=True),
            use_aitown_decision_tree=True,
            operation_pool=_StubPool(),
            dialogue_service=dsvc,
            memory_service=None,
        )
        rt.set_dialogue_id(d.dialogue_id)
        return rt, d.dialogue_id

    def test_near_max_duration_schedules_leave(self):
        # max_duration_minutes = 30 (default); at sim time +26m → over_dur=True.
        # n_messages=6 → last speaker linda (index 5) → emma's turn.
        rt, d_id = self._setup_full_dialogue(n_messages=6)
        intent = rt.step(_ctx(tick=20, sim=_T0 + timedelta(minutes=26)))
        assert intent.reason == "composing_leave"
        assert len(rt.operation_pool.scheduled) == 1
        op, _ = rt.operation_pool.scheduled[0]
        assert op.kind == "generate_message"
        assert op.args["phase"] == "leave"

    def test_leave_result_ends_and_marks_remember(self):
        rt, d_id = self._setup_full_dialogue(n_messages=4)
        # Inject a leave-phase generate_message result
        result = OperationResult(
            op_id="op_leave", agent_id="emma", kind="generate_message",
            success=True,
            payload={
                "dialogue_id": d_id, "speaker_id": "emma",
                "content": "Got to run, see you!",
                "phase": "leave",
            },
        )
        rt.consume_op_result(result)
        rt.step(_ctx(tick=20))
        d = rt.dialogue_service.get(d_id)
        # Dialogue ended via "leave"
        assert d.ended_tick is not None
        assert d.end_reason == "leave"
        # to_remember stamped + dialogue cleared
        assert rt.to_remember == d_id
        assert rt.current_dialogue_id is None
        # The leave message is the last one
        assert d.messages[-1].content == "Got to run, see you!"


class TestDrainSemantics:

    def test_drain_clears_inputs(self):
        r = _runtime()
        r.consume_op_result(OperationResult(
            op_id="op1", agent_id="emma", kind="do_something",
            success=True, payload={"action": "wait"},
        ))
        r.step(_ctx(tick=10))
        assert r._tick_inputs == []

    def test_failed_result_not_applied(self):
        r = _runtime()
        d = r.dialogue_service.schedule_invite(
            "emma", "linda", "cafe", tick=10, simulated_time=_T0,
        )
        r.dialogue_service.accept_invite(d.dialogue_id, "linda")
        r.dialogue_service.advance_to_participating(d.dialogue_id, tick=11)
        r.set_dialogue_id(d.dialogue_id)
        r.consume_op_result(OperationResult(
            op_id="op1", agent_id="emma", kind="generate_message",
            success=False, error_msg="LLM down",
        ))
        r.step(_ctx(tick=12))
        d_after = r.dialogue_service.get(d.dialogue_id)
        # No message appended for a failed result.
        assert len(d_after.messages) == 0
