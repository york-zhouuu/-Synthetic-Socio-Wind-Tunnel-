"""Tests for harden-worker-resilience: DialogueService rolling cleanup.

Long publishable runs accumulate tens of thousands of Dialogue objects
in _dialogues; each carries a `messages: list[DialogueMessage]` that
never gets released. evict_old_dialogues demotes those finished
beyond a grace window to compact DialogueSummary records.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from synthetic_socio_wind_tunnel.conversation.dialogue_service import (
    DialogueService,
    DialogueSummary,
)


def _make_service() -> DialogueService:
    return DialogueService(seed=42)


def _make_dialogue(
    svc: DialogueService, initiator: str, invitee: str,
    started_tick: int, ended_tick: int | None,
    location: str = "loc_x",
) -> str:
    """Inject a synthetic ended dialogue directly into the service
    (bypassing the schedule_invite state machine to keep test focused
    on eviction semantics)."""
    from synthetic_socio_wind_tunnel.conversation.dialogue import (
        Dialogue, DialogueMessage,
    )
    did = f"d_{initiator}_{invitee}_{started_tick}"
    # 2026-05-20 fix-dialogue-eviction-tick-semantic: tests pass
    # synthetic `started_tick` as a global tick value (e.g.
    # `5 * ticks_per_day + 10` = 1450). The Dialogue object now needs
    # `started_day_index` for eviction; derive it from started_tick.
    derived_day_index = started_tick // 288
    d = Dialogue(
        dialogue_id=did,
        initiator_id=initiator,
        invitee_id=invitee,
        target_location_id=location,
        started_tick=started_tick,
        last_message_tick=started_tick + 5,
        started_at=datetime(2026, 4, 22, 8, 0),
        started_day_index=derived_day_index,
        member_status={initiator: "ended", invitee: "ended"},
        messages=[
            DialogueMessage(
                message_id=f"m_{i}", speaker_id=initiator,
                content=f"msg {i}", tick=started_tick + i,
            )
            for i in range(3)
        ],
        ended_tick=ended_tick,
        end_reason="natural_end" if ended_tick is not None else None,
    )
    svc._dialogues[did] = d
    return did


def test_evict_demotes_ended_dialogues_before_cutoff() -> None:
    """harden-worker-resilience scenario: 4 dialogues starting + ending
    on days 1/2/3/4; evict at day 5 cutoff (2-day grace) should demote
    those started before day 3, keep day 3+ in full form.

    2026-05-20: signature changed to compare started_day_index (not
    ended_tick). Test setup updated so dialogues start and end on the
    same day (matches reality — dialogues are minutes, not days)."""
    svc = _make_service()
    ticks_per_day = 288
    # Start each dialogue on the same day it "ends" so started_day_index
    # reflects intent. _make_dialogue derives started_day_index from
    # started_tick // 288.
    d1 = _make_dialogue(svc, "a", "b", 1 * ticks_per_day, 1 * ticks_per_day + 10)
    d2 = _make_dialogue(svc, "c", "d", 2 * ticks_per_day, 2 * ticks_per_day + 10)
    d3 = _make_dialogue(svc, "e", "f", 3 * ticks_per_day, 3 * ticks_per_day + 10)
    d4 = _make_dialogue(svc, "g", "h", 4 * ticks_per_day, 4 * ticks_per_day + 10)

    # cutoff = day 3 (= max(0, 5-2)) → days 0/1/2 evicted, 3/4 kept
    evicted = svc.evict_old_dialogues(before_day_index=3)
    assert evicted == 2
    assert d1 not in svc._dialogues
    assert d2 not in svc._dialogues
    assert d3 in svc._dialogues
    assert d4 in svc._dialogues
    assert d1 in svc._dialogue_summaries
    assert d2 in svc._dialogue_summaries
    # retrieve_summary returns non-None for all 4 (live or evicted)
    for did in (d1, d2, d3, d4):
        s = svc.retrieve_summary(did)
        assert s is not None
        assert isinstance(s, DialogueSummary)


def test_evict_does_not_touch_in_progress() -> None:
    """In-progress dialogues (ended_tick is None) must never be evicted."""
    svc = _make_service()
    d_active = _make_dialogue(svc, "a", "b", started_tick=0, ended_tick=None)
    # Cutoff way after the dialogue started — would evict if eligible
    evicted = svc.evict_old_dialogues(before_day_index=99)
    assert evicted == 0
    assert d_active in svc._dialogues
    assert svc._dialogue_summaries == {}


def test_evict_zero_cutoff_is_noop() -> None:
    svc = _make_service()
    d1 = _make_dialogue(svc, "a", "b", 0, 100)
    evicted = svc.evict_old_dialogues(before_day_index=0)
    assert evicted == 0
    assert d1 in svc._dialogues


def test_evict_idempotent_second_call() -> None:
    svc = _make_service()
    d1 = _make_dialogue(svc, "a", "b", 0, 100)
    first = svc.evict_old_dialogues(before_day_index=2)
    second = svc.evict_old_dialogues(before_day_index=2)
    assert first == 1
    assert second == 0
    assert d1 in svc._dialogue_summaries


def test_retrieve_summary_for_live_dialogue() -> None:
    svc = _make_service()
    d = _make_dialogue(svc, "a", "b", 0, 100)
    s = svc.retrieve_summary(d)
    assert s is not None
    assert s.dialogue_id == d
    assert s.initiator_id == "a"
    assert s.invitee_id == "b"
    assert s.message_count == 3
    assert s.ended_tick == 100


def test_retrieve_summary_unknown_returns_none() -> None:
    svc = _make_service()
    assert svc.retrieve_summary("nonexistent") is None


def test_snapshot_round_trip_preserves_summaries() -> None:
    """Snapshot must serialize+restore _dialogue_summaries so a worker
    restart after rolling eviction sees the same summaries (downstream
    metrics can still call retrieve_summary)."""
    svc = _make_service()
    d1 = _make_dialogue(svc, "a", "b", 0, 100)
    _ = _make_dialogue(svc, "c", "d", 0, 500)  # stays live
    svc.evict_old_dialogues(before_day_index=2)
    assert d1 in svc._dialogue_summaries

    state = svc.to_snapshot_state()
    svc2 = _make_service()
    svc2.from_snapshot_state(state)
    assert d1 in svc2._dialogue_summaries
    s = svc2.retrieve_summary(d1)
    assert s is not None
    assert s.message_count == 3


def test_legacy_snapshot_without_summaries_field_loads() -> None:
    """v1 snapshots predate `dialogue_summaries` key — must default
    to empty dict, not raise."""
    svc = _make_service()
    state = svc.to_snapshot_state()
    # Simulate legacy snapshot: remove the new key
    state.pop("dialogue_summaries", None)
    svc2 = _make_service()
    svc2.from_snapshot_state(state)  # should not raise
    assert svc2._dialogue_summaries == {}
