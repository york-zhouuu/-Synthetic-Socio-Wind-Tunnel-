"""Tests for AgentProfile.identity_text / plan_text + AgentRuntime ai-town
state fields and mutators (agent-stack-aitown-port Phase D tasks 14-15).
"""

from __future__ import annotations

import pytest

from synthetic_socio_wind_tunnel.agent import AgentProfile, AgentRuntime
from synthetic_socio_wind_tunnel.agent.operations.models import PendingOp


def _profile(**overrides) -> AgentProfile:
    base = dict(
        agent_id="emma", name="Emma", age=30, occupation="librarian",
        household="single", home_location="apt_emma",
    )
    base.update(overrides)
    return AgentProfile(**base)


def _op(op_id: str = "op1", agent_id: str = "emma",
        kind: str = "do_something") -> PendingOp:
    return PendingOp(
        op_id=op_id, agent_id=agent_id, kind=kind,  # type: ignore[arg-type]
        created_tick=10, timeout_tick=34, args={},
    )


# ---------------------------------------------------------------------------
# AgentProfile.identity_text / plan_text (task 15.1)
# ---------------------------------------------------------------------------


class TestProfileIdentity:

    def test_defaults_none_for_scripted(self):
        p = _profile()
        assert p.identity_text is None
        assert p.plan_text is None
        # is_protagonist also defaults to False
        assert p.is_protagonist is False

    def test_can_set_identity_and_plan(self):
        p = _profile(
            identity_text="A 30-year-old librarian who loves quiet routines.",
            plan_text="Catch up with neighbours about the weekend market.",
            is_protagonist=True,
        )
        assert "librarian" in p.identity_text
        assert "neighbours" in p.plan_text

    def test_frozen_at_construction(self):
        """AgentProfile is frozen — identity should not be mutable post-init."""
        p = _profile(identity_text="initial")
        with pytest.raises((TypeError, ValueError, AttributeError)):
            # pydantic frozen → ValidationError; dataclass frozen → AttributeError
            p.identity_text = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AgentRuntime ai-town state field defaults (task 14.1)
# ---------------------------------------------------------------------------


class TestRuntimeStateFields:

    def test_defaults(self):
        r = AgentRuntime(profile=_profile())
        assert r.pending_operation is None
        assert r.current_dialogue_id is None
        assert r.to_remember is None
        assert r.last_dialogue_ended_tick is None
        assert r.last_op_kind is None
        assert r.use_aitown_decision_tree is False  # backwards-compat default

    def test_flag_can_be_enabled(self):
        r = AgentRuntime(profile=_profile(), use_aitown_decision_tree=True)
        assert r.use_aitown_decision_tree is True


# ---------------------------------------------------------------------------
# AgentRuntime mutators (task 14.3)
# ---------------------------------------------------------------------------


class TestPendingOpMutators:

    def test_set_and_clear(self):
        r = AgentRuntime(profile=_profile())
        op = _op()
        r.set_pending_op(op)
        assert r.pending_operation is op
        assert r.last_op_kind == "do_something"  # bookkeeping
        cleared = r.clear_pending_op()
        assert cleared is op
        assert r.pending_operation is None
        # last_op_kind persists across clear (intentional — metrics use it)
        assert r.last_op_kind == "do_something"

    def test_set_rejects_overwrite_without_force(self):
        r = AgentRuntime(profile=_profile())
        r.set_pending_op(_op("op1"))
        with pytest.raises(RuntimeError, match="already has pending op"):
            r.set_pending_op(_op("op2"))

    def test_set_force_overwrites(self):
        r = AgentRuntime(profile=_profile())
        r.set_pending_op(_op("op1"))
        r.set_pending_op(_op("op2", kind="reflect"), force=True)
        assert r.pending_operation.op_id == "op2"
        assert r.last_op_kind == "reflect"

    def test_clear_when_none(self):
        r = AgentRuntime(profile=_profile())
        assert r.clear_pending_op() is None  # idempotent


class TestDialogueIdMutators:

    def test_set_and_clear(self):
        r = AgentRuntime(profile=_profile())
        r.set_dialogue_id("d1")
        assert r.current_dialogue_id == "d1"
        cleared = r.clear_dialogue_id()
        assert cleared == "d1"
        assert r.current_dialogue_id is None

    def test_clear_with_ended_tick_stamps_last(self):
        r = AgentRuntime(profile=_profile())
        r.set_dialogue_id("d1")
        r.clear_dialogue_id(ended_tick=42)
        assert r.last_dialogue_ended_tick == 42

    def test_set_rejects_overlap(self):
        r = AgentRuntime(profile=_profile())
        r.set_dialogue_id("d1")
        with pytest.raises(RuntimeError, match="already in dialogue"):
            r.set_dialogue_id("d2")

    def test_set_same_id_idempotent(self):
        r = AgentRuntime(profile=_profile())
        r.set_dialogue_id("d1")
        # Same id is allowed (idempotent — accept_invite + advance call sites
        # may end up calling set twice for the same dialogue without harm).
        r.set_dialogue_id("d1")
        assert r.current_dialogue_id == "d1"


class TestToRememberMutators:

    def test_mark_and_clear(self):
        r = AgentRuntime(profile=_profile())
        r.mark_to_remember("d1")
        assert r.to_remember == "d1"
        d_id = r.clear_to_remember()
        assert d_id == "d1"
        assert r.to_remember is None

    def test_mark_overwrites(self):
        # ai-town's toRemember can be overwritten; we mirror that.
        r = AgentRuntime(profile=_profile())
        r.mark_to_remember("d1")
        r.mark_to_remember("d2")
        assert r.to_remember == "d2"

    def test_clear_when_none(self):
        r = AgentRuntime(profile=_profile())
        assert r.clear_to_remember() is None
