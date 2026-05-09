"""Tests for DialogueService.bridge_to_memory_and_propagation.

Verifies the three-way fan-out on dialogue end:
- memory side: 2 encounter MemoryEvents (one per participant), importance 0.7
- propagation side: Information(category="dialogue", salience=0.6) at initiator
- social_graph side: record_encounter increments tie strength

Idempotency + skip-when-pure-reject + partial wiring (some services None).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from synthetic_socio_wind_tunnel.conversation.dialogue_service import (
    DialogueService,
    InvalidDialogueStateError,
)
from synthetic_socio_wind_tunnel.conversation.service import ConversationService
from synthetic_socio_wind_tunnel.memory.service import MemoryService
from synthetic_socio_wind_tunnel.social_graph import SocialGraphService


_T0 = datetime(2026, 5, 9, 10)


def _ended_dialogue(
    svc: DialogueService,
    *,
    initiator: str = "emma",
    invitee: str = "linda",
    location: str = "cafe",
    tick: int = 10,
    sim_time: datetime = _T0,
    n_messages: int = 2,
    end_reason: str = "leave",
) -> str:
    """Helper: create a dialogue, advance to participating, append N messages,
    end it. Returns dialogue_id."""
    d = svc.schedule_invite(
        initiator, invitee, location, tick=tick, simulated_time=sim_time,
    )
    svc.accept_invite(d.dialogue_id, invitee)
    svc.advance_to_participating(d.dialogue_id, tick=tick + 1)
    sim = sim_time + timedelta(minutes=5)
    for i in range(n_messages):
        speaker = initiator if i % 2 == 0 else invitee
        svc.append_message(
            d.dialogue_id, speaker, f"msg {i}",
            tick=tick + 2 + i,
            simulated_time=sim + timedelta(minutes=i),
        )
    svc.end(
        d.dialogue_id, end_reason,
        tick=tick + 2 + n_messages,
        simulated_time=sim + timedelta(minutes=n_messages),
    )
    return d.dialogue_id


# ---------------------------------------------------------------------------
# Happy path: full 3-way fan-out
# ---------------------------------------------------------------------------


class TestBridgeHappyPath:

    def test_writes_two_encounter_memories(self):
        dsvc = DialogueService(seed=1)
        msvc = MemoryService()
        csvc = ConversationService(seed=1)
        gsvc = SocialGraphService()
        d_id = _ended_dialogue(dsvc)

        result = dsvc.bridge_to_memory_and_propagation(
            d_id,
            memory_service=msvc,
            conversation_service=csvc,
            social_graph=gsvc,
            simulated_time=_T0 + timedelta(minutes=20),
            day_index=0,
            summary="Emma and Linda chatted about the market.",
        )

        assert result["skipped"] is False
        emma_events = msvc.all_for("emma")
        linda_events = msvc.all_for("linda")
        assert len(emma_events) == 1
        assert len(linda_events) == 1
        assert emma_events[0].kind == "encounter"
        assert linda_events[0].kind == "encounter"
        # importance default = 0.7 (higher than generic encounter 0.5)
        assert emma_events[0].importance == 0.7
        assert linda_events[0].importance == 0.7
        # actor_id points to the other participant
        assert emma_events[0].actor_id == "linda"
        assert linda_events[0].actor_id == "emma"
        # both have the dialogue tag
        assert "dialogue" in emma_events[0].tags
        # summary embedded in content
        assert "market" in emma_events[0].content
        # event_ids are deterministic per-dialogue
        assert emma_events[0].event_id == f"ev_dlg_{d_id}_emma_encounter"
        assert linda_events[0].event_id == f"ev_dlg_{d_id}_linda_encounter"

    def test_registers_dialogue_information(self):
        dsvc = DialogueService(seed=1)
        msvc = MemoryService()
        csvc = ConversationService(seed=1)
        d_id = _ended_dialogue(dsvc)

        result = dsvc.bridge_to_memory_and_propagation(
            d_id,
            memory_service=msvc,
            conversation_service=csvc,
            social_graph=None,
            simulated_time=_T0 + timedelta(minutes=20),
            day_index=0,
            summary="They discussed the weekend plans.",
        )

        assert result["info_id"] == f"info_dlg_{d_id}"
        assert csvc.info_count() == 1
        # initiator is the origin; hops_at_learn=0
        infos = csvc.all_infos()
        assert len(infos) == 1
        info = infos[0]
        assert info.category == "dialogue"
        assert info.salience == 0.6
        assert info.origin_agent_id == "emma"
        # initiator knows it; invitee does NOT (will learn via propagation later)
        assert info.info_id in csvc.info_known_by("emma")
        assert info.info_id not in csvc.info_known_by("linda")
        # propagation hops at origin = 0
        prop = csvc.get_propagation(info.info_id)
        assert prop is not None
        assert prop.reach == 1
        assert prop.hops_at["emma"] == 0

    def test_records_social_graph_encounter(self):
        dsvc = DialogueService(seed=1)
        msvc = MemoryService()
        gsvc = SocialGraphService()
        d_id = _ended_dialogue(dsvc)

        result = dsvc.bridge_to_memory_and_propagation(
            d_id,
            memory_service=msvc,
            conversation_service=None,
            social_graph=gsvc,
            simulated_time=_T0 + timedelta(minutes=20),
            day_index=0,
        )

        tie = gsvc.get_tie("emma", "linda")
        assert tie is not None
        assert tie.encounter_count == 1
        assert result["tie_strength"] == pytest.approx(tie.strength)


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestBridgeIdempotency:

    def test_second_call_skips(self):
        dsvc = DialogueService(seed=1)
        msvc = MemoryService()
        csvc = ConversationService(seed=1)
        gsvc = SocialGraphService()
        d_id = _ended_dialogue(dsvc)

        first = dsvc.bridge_to_memory_and_propagation(
            d_id, memory_service=msvc, conversation_service=csvc,
            social_graph=gsvc,
            simulated_time=_T0 + timedelta(minutes=20),
        )
        second = dsvc.bridge_to_memory_and_propagation(
            d_id, memory_service=msvc, conversation_service=csvc,
            social_graph=gsvc,
            simulated_time=_T0 + timedelta(minutes=25),
        )
        assert first["skipped"] is False
        assert second["skipped"] is True
        assert second["reason"] == "already_bridged"
        # No double writes
        assert len(msvc.all_for("emma")) == 1
        assert len(msvc.all_for("linda")) == 1
        assert csvc.info_count() == 1
        # tie still has count 1 (record_encounter is also tick-idempotent,
        # but more importantly — bridge bailed before calling it)
        tie = gsvc.get_tie("emma", "linda")
        assert tie.encounter_count == 1

    def test_has_bridged_reflects_state(self):
        dsvc = DialogueService(seed=1)
        msvc = MemoryService()
        d_id = _ended_dialogue(dsvc)
        assert dsvc.has_bridged(d_id) is False
        dsvc.bridge_to_memory_and_propagation(
            d_id, memory_service=msvc,
            simulated_time=_T0 + timedelta(minutes=20),
        )
        assert dsvc.has_bridged(d_id) is True


# ---------------------------------------------------------------------------
# Skip / error cases
# ---------------------------------------------------------------------------


class TestBridgeSkip:

    def test_rejects_unended_dialogue(self):
        dsvc = DialogueService(seed=1)
        msvc = MemoryService()
        d = dsvc.schedule_invite(
            "emma", "linda", "cafe", tick=10, simulated_time=_T0,
        )
        with pytest.raises(InvalidDialogueStateError, match="not ended"):
            dsvc.bridge_to_memory_and_propagation(
                d.dialogue_id, memory_service=msvc,
                simulated_time=_T0 + timedelta(minutes=10),
            )

    def test_rejected_no_messages_skips(self):
        dsvc = DialogueService(seed=1)
        msvc = MemoryService()
        csvc = ConversationService(seed=1)
        gsvc = SocialGraphService()
        d = dsvc.schedule_invite(
            "emma", "linda", "cafe", tick=10, simulated_time=_T0,
        )
        dsvc.reject_invite(
            d.dialogue_id, "linda", "busy",
            tick=11, simulated_time=_T0 + timedelta(minutes=5),
        )
        result = dsvc.bridge_to_memory_and_propagation(
            d.dialogue_id, memory_service=msvc,
            conversation_service=csvc, social_graph=gsvc,
            simulated_time=_T0 + timedelta(minutes=6),
        )
        assert result["skipped"] is True
        assert result["reason"] == "rejected_no_messages"
        assert msvc.all_for("emma") == []
        assert msvc.all_for("linda") == []
        assert csvc.info_count() == 0
        assert gsvc.get_tie("emma", "linda") is None
        # Subsequent bridge call must remain skipped (idempotent skip).
        result2 = dsvc.bridge_to_memory_and_propagation(
            d.dialogue_id, memory_service=msvc,
            simulated_time=_T0 + timedelta(minutes=7),
        )
        assert result2["skipped"] is True
        assert result2["reason"] == "already_bridged"


# ---------------------------------------------------------------------------
# Partial wiring (some downstream services None)
# ---------------------------------------------------------------------------


class TestBridgePartial:

    def test_no_conversation_service(self):
        dsvc = DialogueService(seed=1)
        msvc = MemoryService()
        gsvc = SocialGraphService()
        d_id = _ended_dialogue(dsvc)

        result = dsvc.bridge_to_memory_and_propagation(
            d_id, memory_service=msvc,
            conversation_service=None, social_graph=gsvc,
            simulated_time=_T0 + timedelta(minutes=20),
        )
        assert result["info_id"] is None
        assert len(msvc.all_for("emma")) == 1
        assert gsvc.get_tie("emma", "linda") is not None

    def test_no_social_graph(self):
        dsvc = DialogueService(seed=1)
        msvc = MemoryService()
        csvc = ConversationService(seed=1)
        d_id = _ended_dialogue(dsvc)

        result = dsvc.bridge_to_memory_and_propagation(
            d_id, memory_service=msvc,
            conversation_service=csvc, social_graph=None,
            simulated_time=_T0 + timedelta(minutes=20),
        )
        assert result["tie_strength"] is None
        assert result["info_id"] is not None
        assert csvc.info_count() == 1


# ---------------------------------------------------------------------------
# Custom importance / salience overrides
# ---------------------------------------------------------------------------


class TestBridgeOverrides:

    def test_custom_importance_and_salience(self):
        dsvc = DialogueService(seed=1)
        msvc = MemoryService()
        csvc = ConversationService(seed=1)
        d_id = _ended_dialogue(dsvc)

        dsvc.bridge_to_memory_and_propagation(
            d_id, memory_service=msvc,
            conversation_service=csvc, social_graph=None,
            simulated_time=_T0 + timedelta(minutes=20),
            encounter_importance=0.9,
            info_salience=0.85,
        )

        emma_evs = msvc.all_for("emma")
        assert emma_evs[0].importance == 0.9
        infos = csvc.all_infos()
        assert infos[0].salience == 0.85

    def test_summary_fallback_when_none(self):
        dsvc = DialogueService(seed=1)
        msvc = MemoryService()
        csvc = ConversationService(seed=1)
        d_id = _ended_dialogue(dsvc)
        result = dsvc.bridge_to_memory_and_propagation(
            d_id, memory_service=msvc,
            conversation_service=csvc, social_graph=None,
            simulated_time=_T0 + timedelta(minutes=20),
            summary=None,
        )
        info = csvc.all_infos()[0]
        # Fallback content includes dialogue_id and end_reason
        assert d_id in info.content
        assert "leave" in info.content
        # Memory event content does NOT embed summary when summary is None
        emma_evs = msvc.all_for("emma")
        assert "<dialogue" not in emma_evs[0].content
