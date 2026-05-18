"""Tests for DialogueService (agent-stack-aitown-port Phase C).

Verifies 1:1 fidelity to ai-town's Conversation lifecycle:
- start (initiator walking_over, invitee invited)
- accept_invite → both walking_over
- both at target → participating
- leave / max_messages / cooldown
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from synthetic_socio_wind_tunnel.conversation.dialogue import (
    Dialogue,
    DialogueMessage,
)
from synthetic_socio_wind_tunnel.conversation.dialogue_service import (
    DialogueAlreadyExistsError,
    DialogueCooldownError,
    DialogueService,
    InvalidDialogueStateError,
)


_T0 = datetime(2026, 5, 9, 10)


def _ticks(n: int) -> int:
    return n


# ---------------------------------------------------------------------------
# Dialogue model invariants
# ---------------------------------------------------------------------------


class TestDialogueModel:

    def test_self_dialogue_rejected(self):
        with pytest.raises(ValueError, match="self"):
            Dialogue(
                dialogue_id="d", initiator_id="emma", invitee_id="emma",
                target_location_id="cafe", started_tick=10, last_message_tick=10,
            )

    def test_other_participant(self):
        d = Dialogue(
            dialogue_id="d", initiator_id="emma", invitee_id="linda",
            target_location_id="cafe", started_tick=10, last_message_tick=10,
        )
        assert d.other_participant("emma") == "linda"
        assert d.other_participant("linda") == "emma"
        with pytest.raises(ValueError, match="not in"):
            d.other_participant("john")

    def test_status_derivation(self):
        d = Dialogue(
            dialogue_id="d", initiator_id="emma", invitee_id="linda",
            target_location_id="cafe", started_tick=10, last_message_tick=10,
            member_status={"emma": "walking_over", "linda": "invited"},
        )
        # Mixed walking_over + invited → status walking_over (initiator already moved)
        assert d.status == "walking_over"
        d.member_status["linda"] = "walking_over"
        assert d.status == "walking_over"
        d.member_status["emma"] = "participating"
        d.member_status["linda"] = "participating"
        assert d.status == "participating"
        d.ended_tick = 20
        assert d.status == "ended"

    def test_message_immutable(self):
        m = DialogueMessage(
            message_id="m1", speaker_id="emma", content="hi", tick=10,
        )
        with pytest.raises(Exception):
            m.content = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# schedule_invite
# ---------------------------------------------------------------------------


class TestScheduleInvite:

    def test_creates_with_correct_initial_state(self):
        svc = DialogueService(seed=42)
        d = svc.schedule_invite(
            "emma", "linda", "cafe",
            tick=10, simulated_time=_T0,
        )
        assert d.initiator_id == "emma"
        assert d.invitee_id == "linda"
        # ai-town: initiator starts walking_over, invitee invited
        assert d.member_status["emma"] == "walking_over"
        assert d.member_status["linda"] == "invited"
        assert d.target_location_id == "cafe"
        assert d.ended_tick is None

    def test_self_invite_rejected(self):
        svc = DialogueService(seed=42)
        with pytest.raises(ValueError, match="self"):
            svc.schedule_invite(
                "emma", "emma", "cafe",
                tick=10, simulated_time=_T0,
            )

    def test_initiator_already_busy_rejected(self):
        svc = DialogueService(seed=42)
        svc.schedule_invite("emma", "linda", "cafe",
                            tick=10, simulated_time=_T0)
        with pytest.raises(DialogueAlreadyExistsError, match="emma"):
            svc.schedule_invite("emma", "john", "park",
                                tick=11, simulated_time=_T0 + timedelta(minutes=5))

    def test_invitee_already_busy_rejected(self):
        svc = DialogueService(seed=42)
        svc.schedule_invite("emma", "linda", "cafe",
                            tick=10, simulated_time=_T0)
        with pytest.raises(DialogueAlreadyExistsError, match="linda"):
            svc.schedule_invite("john", "linda", "park",
                                tick=11, simulated_time=_T0 + timedelta(minutes=5))

    def test_active_for(self):
        svc = DialogueService(seed=42)
        d = svc.schedule_invite("emma", "linda", "cafe",
                                tick=10, simulated_time=_T0)
        assert svc.active_for("emma") is d
        assert svc.active_for("linda") is d
        assert svc.active_for("john") is None


# ---------------------------------------------------------------------------
# Cooldown
# ---------------------------------------------------------------------------


class TestCooldown:

    def test_within_cooldown_rejected(self):
        svc = DialogueService(seed=42, cooldown_minutes=60)
        d = svc.schedule_invite("emma", "linda", "cafe",
                                tick=10, simulated_time=_T0)
        svc.end(d.dialogue_id, "leave",
                tick=11, simulated_time=_T0 + timedelta(minutes=5))
        # Try to re-invite 30 min later (within 60 min cooldown)
        with pytest.raises(DialogueCooldownError):
            svc.schedule_invite("emma", "linda", "cafe",
                                tick=20, simulated_time=_T0 + timedelta(minutes=35))

    def test_after_cooldown_ok(self):
        svc = DialogueService(seed=42, cooldown_minutes=60)
        d = svc.schedule_invite("emma", "linda", "cafe",
                                tick=10, simulated_time=_T0)
        svc.end(d.dialogue_id, "leave",
                tick=11, simulated_time=_T0 + timedelta(minutes=5))
        # 90 min later (past cooldown)
        d2 = svc.schedule_invite("emma", "linda", "cafe",
                                 tick=20, simulated_time=_T0 + timedelta(minutes=95))
        assert d2 is not None

    def test_force_overrides_cooldown(self):
        svc = DialogueService(seed=42, cooldown_minutes=120)
        d = svc.schedule_invite("emma", "linda", "cafe",
                                tick=10, simulated_time=_T0)
        svc.end(d.dialogue_id, "leave",
                tick=11, simulated_time=_T0 + timedelta(minutes=5))
        d2 = svc.schedule_invite("emma", "linda", "cafe",
                                 tick=20, simulated_time=_T0 + timedelta(minutes=10),
                                 force=True)
        assert d2 is not None


# ---------------------------------------------------------------------------
# accept / reject invite
# ---------------------------------------------------------------------------


class TestAcceptReject:

    def test_accept_invite_walks_over(self):
        svc = DialogueService(seed=42)
        d = svc.schedule_invite("emma", "linda", "cafe",
                                tick=10, simulated_time=_T0)
        svc.accept_invite(d.dialogue_id, "linda")
        assert d.member_status["linda"] == "walking_over"
        assert d.member_status["emma"] == "walking_over"
        assert d.status == "walking_over"

    def test_accept_in_wrong_status_raises(self):
        svc = DialogueService(seed=42)
        d = svc.schedule_invite("emma", "linda", "cafe",
                                tick=10, simulated_time=_T0)
        # initiator is walking_over, not invited
        with pytest.raises(InvalidDialogueStateError):
            svc.accept_invite(d.dialogue_id, "emma")

    def test_reject_invite_ends(self):
        svc = DialogueService(seed=42)
        d = svc.schedule_invite("emma", "linda", "cafe",
                                tick=10, simulated_time=_T0)
        svc.reject_invite(d.dialogue_id, "linda", "busy",
                          tick=11, simulated_time=_T0 + timedelta(minutes=5))
        assert d.status == "ended"
        assert d.end_reason == "rejected:busy"
        # Both agents freed
        assert svc.active_for("emma") is None
        assert svc.active_for("linda") is None


# ---------------------------------------------------------------------------
# advance_to_participating
# ---------------------------------------------------------------------------


class TestAdvanceParticipating:

    def test_advance_from_walking_over(self):
        svc = DialogueService(seed=42)
        d = svc.schedule_invite("emma", "linda", "cafe",
                                tick=10, simulated_time=_T0)
        svc.accept_invite(d.dialogue_id, "linda")
        svc.advance_to_participating(d.dialogue_id, tick=15)
        assert d.status == "participating"
        assert d.member_status["emma"] == "participating"
        assert d.member_status["linda"] == "participating"

    def test_advance_idempotent(self):
        svc = DialogueService(seed=42)
        d = svc.schedule_invite("emma", "linda", "cafe",
                                tick=10, simulated_time=_T0)
        svc.accept_invite(d.dialogue_id, "linda")
        svc.advance_to_participating(d.dialogue_id, tick=15)
        # Second call no-op (no exception)
        svc.advance_to_participating(d.dialogue_id, tick=20)
        assert d.status == "participating"

    def test_advance_from_invited_rejected(self):
        svc = DialogueService(seed=42)
        d = svc.schedule_invite("emma", "linda", "cafe",
                                tick=10, simulated_time=_T0)
        # linda still invited; status is walking_over (mixed)
        # Actually status is walking_over because emma is, even if linda invited.
        # Test: try to advance when linda hasn't accepted yet
        with pytest.raises(InvalidDialogueStateError):
            # Reset linda back to invited to test the wrong-status path
            d.member_status["linda"] = "invited"
            d.member_status["emma"] = "invited"
            svc.advance_to_participating(d.dialogue_id, tick=15)


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


class TestMessages:

    def _make_participating(self, svc: DialogueService) -> Dialogue:
        d = svc.schedule_invite("emma", "linda", "cafe",
                                tick=10, simulated_time=_T0)
        svc.accept_invite(d.dialogue_id, "linda")
        svc.advance_to_participating(d.dialogue_id, tick=12)
        return d

    def test_append_message_records(self):
        svc = DialogueService(seed=42)
        d = self._make_participating(svc)
        d2, msg = svc.append_message(
            d.dialogue_id, "emma", "Hi linda!",
            tick=13, simulated_time=_T0 + timedelta(minutes=15),
        )
        assert d2 is d
        assert msg.speaker_id == "emma"
        assert msg.content == "Hi linda!"
        assert d.message_count() == 1

    def test_speak_in_invited_rejected(self):
        svc = DialogueService(seed=42)
        d = svc.schedule_invite("emma", "linda", "cafe",
                                tick=10, simulated_time=_T0)
        # Status is walking_over, not participating
        with pytest.raises(InvalidDialogueStateError):
            svc.append_message(d.dialogue_id, "emma", "hi",
                               tick=11, simulated_time=_T0 + timedelta(minutes=5))

    def test_non_participant_speaker_rejected(self):
        svc = DialogueService(seed=42)
        d = self._make_participating(svc)
        with pytest.raises(ValueError, match="not a participant"):
            svc.append_message(d.dialogue_id, "john", "hi",
                               tick=13, simulated_time=_T0 + timedelta(minutes=15))

    def test_max_messages_auto_end(self):
        svc = DialogueService(seed=42, max_messages=3)
        d = self._make_participating(svc)
        for i in range(3):
            svc.append_message(
                d.dialogue_id, "emma" if i % 2 == 0 else "linda",
                f"msg {i}",
                tick=15 + i, simulated_time=_T0 + timedelta(minutes=15 + i),
            )
        assert d.status == "ended"
        assert d.end_reason == "max_messages"


# ---------------------------------------------------------------------------
# Leave + force-end
# ---------------------------------------------------------------------------


class TestLeaveAndEnd:

    def test_leave_ends(self):
        svc = DialogueService(seed=42)
        d = svc.schedule_invite("emma", "linda", "cafe",
                                tick=10, simulated_time=_T0)
        svc.accept_invite(d.dialogue_id, "linda")
        svc.advance_to_participating(d.dialogue_id, tick=12)
        svc.leave(d.dialogue_id, "emma",
                  tick=20, simulated_time=_T0 + timedelta(minutes=50))
        assert d.status == "ended"
        assert d.end_reason == "leave"
        assert svc.active_for("emma") is None
        assert svc.active_for("linda") is None

    def test_end_idempotent(self):
        svc = DialogueService(seed=42)
        d = svc.schedule_invite("emma", "linda", "cafe",
                                tick=10, simulated_time=_T0)
        svc.end(d.dialogue_id, "explicit",
                tick=11, simulated_time=_T0 + timedelta(minutes=5))
        # Second end → no-op (no error)
        svc.end(d.dialogue_id, "another",
                tick=12, simulated_time=_T0 + timedelta(minutes=10))
        assert d.end_reason == "explicit"  # first reason wins


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class TestMetrics:

    def test_counts(self):
        svc = DialogueService(seed=42, cooldown_minutes=0, max_messages=2)
        # d1: leave
        d1 = svc.schedule_invite("a", "b", "x", tick=10, simulated_time=_T0)
        svc.accept_invite(d1.dialogue_id, "b")
        svc.advance_to_participating(d1.dialogue_id, tick=11)
        svc.leave(d1.dialogue_id, "a", tick=12,
                  simulated_time=_T0 + timedelta(minutes=10))
        # d2: max_messages (between c, d)
        d2 = svc.schedule_invite("c", "d", "y", tick=20,
                                 simulated_time=_T0 + timedelta(minutes=15))
        svc.accept_invite(d2.dialogue_id, "d")
        svc.advance_to_participating(d2.dialogue_id, tick=21)
        for i in range(2):
            svc.append_message(
                d2.dialogue_id, "c" if i % 2 == 0 else "d", "x",
                tick=22 + i, simulated_time=_T0 + timedelta(minutes=20 + i),
            )

        assert svc.total_count() == 2
        assert svc.ended_count() == 2
        assert svc.active_count() == 0
        # d1=0 messages (leave), d2=2 messages → avg=1.0
        assert svc.avg_message_count() == 1.0
        reasons = svc.counts_by_end_reason()
        assert reasons.get("leave") == 1
        assert reasons.get("max_messages") == 1


# ---------------------------------------------------------------------------
# Capability 1.12 (2026-05-19) — snapshot persistence
# ---------------------------------------------------------------------------


class TestSnapshotRoundtrip:
    """Snapshot SHALL preserve dialogue + DialogueMessage content."""

    def test_empty_state_roundtrip(self):
        svc1 = DialogueService(seed=42)
        state = svc1.to_snapshot_state()
        svc2 = DialogueService(seed=99)
        svc2.from_snapshot_state(state)
        assert svc2.total_count() == 0

    def test_active_dialogue_survives_roundtrip(self):
        svc1 = DialogueService(seed=42)
        d = svc1.schedule_invite("a", "b", "cafe", tick=10, simulated_time=_T0)
        svc1.accept_invite(d.dialogue_id, "b")
        svc1.advance_to_participating(d.dialogue_id, tick=11)
        svc1.append_message(
            d.dialogue_id, "a", "Hello!",
            tick=12, simulated_time=_T0 + timedelta(minutes=5),
        )
        svc1.append_message(
            d.dialogue_id, "b", "Hi there!",
            tick=13, simulated_time=_T0 + timedelta(minutes=10),
        )
        state = svc1.to_snapshot_state()

        svc2 = DialogueService(seed=99)
        svc2.from_snapshot_state(state)
        assert svc2.total_count() == 1
        assert svc2.active_count() == 1
        d_restored = svc2.get(d.dialogue_id)
        assert d_restored is not None
        assert d_restored.initiator_id == "a"
        assert d_restored.invitee_id == "b"
        assert d_restored.target_location_id == "cafe"
        assert len(d_restored.messages) == 2
        assert d_restored.messages[0].content == "Hello!"
        assert d_restored.messages[1].speaker_id == "b"
        assert svc2.active_for("a") is not None
        assert svc2.active_for("b") is not None

    def test_ended_dialogue_with_cooldown_survives(self):
        svc1 = DialogueService(seed=42)
        d = svc1.schedule_invite("a", "b", "cafe", tick=10, simulated_time=_T0)
        svc1.accept_invite(d.dialogue_id, "b")
        svc1.advance_to_participating(d.dialogue_id, tick=11)
        svc1.leave(d.dialogue_id, "a", tick=20,
                   simulated_time=_T0 + timedelta(minutes=50))
        state = svc1.to_snapshot_state()

        svc2 = DialogueService(seed=99)
        svc2.from_snapshot_state(state)
        assert svc2.ended_count() == 1
        # cooldown SHALL still block re-invite after restore
        with pytest.raises(DialogueCooldownError):
            svc2.schedule_invite(
                "a", "b", "cafe",
                tick=21,
                simulated_time=_T0 + timedelta(minutes=51),
            )

    def test_json_roundtrip_via_serialization(self):
        """state dict SHALL survive json.dumps + json.loads
        (verifies no non-JSON-serializable objects leak through)."""
        import json
        svc1 = DialogueService(seed=42)
        d = svc1.schedule_invite("a", "b", "park", tick=5, simulated_time=_T0)
        svc1.accept_invite(d.dialogue_id, "b")
        svc1.advance_to_participating(d.dialogue_id, tick=6)
        svc1.append_message(
            d.dialogue_id, "a", "hi",
            tick=7, simulated_time=_T0 + timedelta(minutes=10),
        )
        state = svc1.to_snapshot_state()

        blob = json.dumps(state)
        state2 = json.loads(blob)
        svc2 = DialogueService(seed=99)
        svc2.from_snapshot_state(state2)
        assert svc2.total_count() == 1
        assert svc2.get(d.dialogue_id).messages[0].content == "hi"

    def test_rng_state_preserved(self):
        """The RNG state SHALL be restored — so post-resume dialogue
        stochasticity matches what would have happened in-place."""
        import json
        svc1 = DialogueService(seed=42)
        for _ in range(5):
            svc1._rng.random()
        state = svc1.to_snapshot_state()
        # Also verify json round-trip preserves rng (tuple → list → tuple).
        state = json.loads(json.dumps(state))
        svc2 = DialogueService(seed=99)
        svc2.from_snapshot_state(state)
        assert svc1._rng.random() == svc2._rng.random()
