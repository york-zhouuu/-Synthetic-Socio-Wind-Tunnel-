"""Property-based tests for DialogueService.evict_old_dialogues.

Demo of `testing-proactive` approach (see docs/testing-philosophy.md
Section 11): instead of writing 1 hand-picked example, let Hypothesis
generate hundreds of random dialogue collections + cutoff values and
auto-shrink to the minimal failing case.

Each `@given` block declares an **invariant** that SHALL hold regardless
of input. If Hypothesis finds any input violating it, the test reports
the smallest input that triggers the bug.

This is complementary to `tests/test_dialogue_service_eviction.py`'s
hand-written cases — the hand-written cases pin down specific scenarios
from spec, the property tests catch edge cases the author didn't think
of.
"""

from __future__ import annotations

from datetime import datetime

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from synthetic_socio_wind_tunnel.conversation.dialogue import (
    Dialogue, DialogueMessage,
)
from synthetic_socio_wind_tunnel.conversation.dialogue_service import (
    DialogueService,
)


def _inject_dialogue(
    svc: DialogueService, dialogue_id: str, started: int,
    ended: int | None, n_messages: int = 0,
) -> None:
    """Inject a synthetic dialogue. ended=None → in-progress."""
    d = Dialogue(
        dialogue_id=dialogue_id,
        initiator_id=f"a_{dialogue_id}",
        invitee_id=f"b_{dialogue_id}",
        target_location_id="loc",
        started_tick=started,
        last_message_tick=started + (n_messages or 0),
        started_at=datetime(2026, 4, 22),
        member_status={f"a_{dialogue_id}": "ended", f"b_{dialogue_id}": "ended"},
        messages=[
            DialogueMessage(
                message_id=f"m_{dialogue_id}_{i}",
                speaker_id=f"a_{dialogue_id}",
                content=f"text {i}",
                tick=started + i,
            )
            for i in range(n_messages)
        ],
        ended_tick=ended,
        end_reason="natural_end" if ended is not None else None,
    )
    svc._dialogues[dialogue_id] = d


# Hypothesis strategies
ended_dialogue = st.builds(
    lambda did, started, duration, n_msg: (did, started, started + duration, n_msg),
    did=st.text(alphabet="abcdefghij", min_size=2, max_size=6).filter(
        lambda s: s.strip() != ""
    ),
    started=st.integers(min_value=0, max_value=10_000),
    duration=st.integers(min_value=1, max_value=1_000),
    n_msg=st.integers(min_value=0, max_value=8),
)

in_progress_dialogue = st.builds(
    lambda did, started, n_msg: (did, started, None, n_msg),
    did=st.text(alphabet="abcdefghij", min_size=2, max_size=6).filter(
        lambda s: s.strip() != ""
    ),
    started=st.integers(min_value=0, max_value=10_000),
    n_msg=st.integers(min_value=0, max_value=8),
)

mixed_dialogues = st.lists(
    st.one_of(ended_dialogue, in_progress_dialogue),
    min_size=0, max_size=50,
    unique_by=lambda t: t[0],
)


# ====================================================================
# Properties (these are the unchanging contracts)
# ====================================================================

@given(dialogues=mixed_dialogues, cutoff=st.integers(min_value=-100, max_value=20_000))
@settings(max_examples=200, deadline=None)
def test_property_evict_never_touches_in_progress(dialogues, cutoff):
    """INVARIANT: evict_old_dialogues SHALL NEVER move an in-progress
    dialogue (ended_tick is None) to summaries, regardless of cutoff."""
    svc = DialogueService(seed=42)
    in_progress_ids = set()
    for did, started, ended, n_msg in dialogues:
        _inject_dialogue(svc, did, started, ended, n_msg)
        if ended is None:
            in_progress_ids.add(did)

    svc.evict_old_dialogues(before_tick=cutoff)

    for did in in_progress_ids:
        assert did in svc._dialogues, (
            f"in-progress {did!r} was wrongly evicted (cutoff={cutoff})"
        )
        assert did not in svc._dialogue_summaries


@given(dialogues=mixed_dialogues, cutoff=st.integers(min_value=-100, max_value=20_000))
@settings(max_examples=200, deadline=None)
def test_property_evict_only_takes_dialogues_below_cutoff(dialogues, cutoff):
    """INVARIANT: evict moves a dialogue to summary IFF
    (ended_tick is not None AND ended_tick < cutoff)."""
    svc = DialogueService(seed=42)
    for did, started, ended, n_msg in dialogues:
        _inject_dialogue(svc, did, started, ended, n_msg)

    snapshot_before = {did: svc._dialogues[did].ended_tick for did in svc._dialogues}
    svc.evict_old_dialogues(before_tick=cutoff)

    for did, ended_tick in snapshot_before.items():
        was_evicted = did in svc._dialogue_summaries
        should_evict = (
            ended_tick is not None and ended_tick < cutoff and cutoff > 0
        )
        assert was_evicted == should_evict, (
            f"{did!r} (ended_tick={ended_tick}, cutoff={cutoff}) "
            f"was_evicted={was_evicted} should_evict={should_evict}"
        )


@given(dialogues=mixed_dialogues, cutoff=st.integers(min_value=-100, max_value=20_000))
@settings(max_examples=200, deadline=None)
def test_property_evict_is_idempotent(dialogues, cutoff):
    """INVARIANT: calling evict twice with same cutoff has same effect
    as calling once (second call returns 0)."""
    svc = DialogueService(seed=42)
    for did, started, ended, n_msg in dialogues:
        _inject_dialogue(svc, did, started, ended, n_msg)

    first = svc.evict_old_dialogues(before_tick=cutoff)
    state_after_first = (
        set(svc._dialogues.keys()),
        set(svc._dialogue_summaries.keys()),
    )

    second = svc.evict_old_dialogues(before_tick=cutoff)
    state_after_second = (
        set(svc._dialogues.keys()),
        set(svc._dialogue_summaries.keys()),
    )

    assert second == 0, (
        f"Second evict with same cutoff returned {second}; "
        f"should be 0 (idempotent)"
    )
    assert state_after_first == state_after_second


@given(
    dialogues=mixed_dialogues,
    cutoffs=st.lists(
        st.integers(min_value=0, max_value=20_000),
        min_size=2, max_size=5,
    ),
)
@settings(max_examples=200, deadline=None)
def test_property_evict_monotone_in_cutoff(dialogues, cutoffs):
    """INVARIANT: as cutoff increases, the set of evicted dialogues
    grows monotonically — once evicted, never un-evicted."""
    svc = DialogueService(seed=42)
    for did, started, ended, n_msg in dialogues:
        _inject_dialogue(svc, did, started, ended, n_msg)

    cutoffs_sorted = sorted(cutoffs)
    seen_evicted: set[str] = set()
    for c in cutoffs_sorted:
        svc.evict_old_dialogues(before_tick=c)
        currently_evicted = set(svc._dialogue_summaries.keys())
        # all previously-seen-evicted must still be in summaries
        assert seen_evicted.issubset(currently_evicted), (
            f"after evict at cutoff={c}, lost: "
            f"{seen_evicted - currently_evicted}"
        )
        seen_evicted = currently_evicted


@given(dialogues=mixed_dialogues, cutoff=st.integers(min_value=0, max_value=20_000))
@settings(max_examples=200, deadline=None)
def test_property_retrieve_summary_total_conservation(dialogues, cutoff):
    """INVARIANT: for every input dialogue id, retrieve_summary returns
    a non-None DialogueSummary (whether live or evicted) — no dialogue
    becomes 'invisible' after evict."""
    svc = DialogueService(seed=42)
    input_ids = []
    for did, started, ended, n_msg in dialogues:
        _inject_dialogue(svc, did, started, ended, n_msg)
        input_ids.append(did)

    svc.evict_old_dialogues(before_tick=cutoff)

    for did in input_ids:
        s = svc.retrieve_summary(did)
        assert s is not None, (
            f"retrieve_summary({did!r}) returned None — "
            f"dialogue lost after evict (cutoff={cutoff})"
        )
        assert s.dialogue_id == did
