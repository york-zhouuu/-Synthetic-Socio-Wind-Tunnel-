"""2026-05-20 monitoring wiring-gap regression: memstat dialogue counter.

Scout run for publishable v2 at sim 19:00 of day 0 showed
`dialogue.live=0` for all 4 variants — investigation found snapshot
actually contained 589 dialogues + 32 active. Root cause: instrumentation
read `_active_dialogues` / `_evicted_count` attribute names that don't
exist on DialogueService (real fields: `_dialogues`, `_dialogue_summaries`,
`_active_by_agent`). `getattr(default=...)` silently returned 0.

Same shape as 2026-05-20 ru_maxrss / phase-event wiring gap bugs — spec
existed but implementation diverged. These tests guard against silent
counter regressions.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from synthetic_socio_wind_tunnel.conversation.dialogue import Dialogue
from synthetic_socio_wind_tunnel.conversation.dialogue_service import (
    DialogueService,
    DialogueSummary,
)
from synthetic_socio_wind_tunnel.observability.instrumentation import (
    RuntimeInstrumentation,
)


def _live_dialogue(did: str) -> Dialogue:
    """In-progress dialogue (ended_tick None)."""
    return Dialogue(
        dialogue_id=did, initiator_id="a", invitee_id="b",
        target_location_id="loc1",
        started_tick=0, last_message_tick=0,
        started_at=datetime(2026, 5, 20),
        member_status={"a": "participating", "b": "participating"},
    )


def _ended_dialogue(did: str) -> Dialogue:
    """Dialogue with ended_tick set."""
    d = _live_dialogue(did)
    object.__setattr__(d, "ended_tick", 5)
    object.__setattr__(d, "end_reason", "completed")
    return d


def _read_latest_sample(output_dir: Path, seed: int) -> dict:
    p = output_dir / f"seed_{seed}.memstat.jsonl"
    lines = p.read_text(encoding="utf-8").strip().split("\n")
    return json.loads(lines[-1])


def test_dialogue_counter_reads_real_field_names(tmp_path):
    """memstat sample SHALL count live/ended dialogues correctly,
    not silently default to 0 via wrong attribute name."""
    ds = DialogueService(seed=42)
    # 3 live + 7 ended-but-unevicted
    for i in range(3):
        d = _live_dialogue(f"live_{i}")
        ds._dialogues[d.dialogue_id] = d
    for i in range(7):
        d = _ended_dialogue(f"ended_{i}")
        ds._dialogues[d.dialogue_id] = d

    inst = RuntimeInstrumentation(
        output_dir=tmp_path, seed=42, sample_every_n_ticks=1,
    )
    inst.sample_metrics(
        tick_global=10, tick_in_day=10, day_index=0,
        dialogue_service=ds,
    )
    sample = _read_latest_sample(tmp_path, 42)
    ds_stats = sample["dialogue_service"]
    assert ds_stats["live"] == 3, f"live wrong: {ds_stats}"
    assert ds_stats["ended_unevicted"] == 7, (
        f"ended_unevicted wrong: {ds_stats}"
    )
    assert ds_stats["evicted_total"] == 0, (
        f"evicted_total wrong: {ds_stats}"
    )


def test_dialogue_counter_with_evicted_summaries(tmp_path):
    """When dialogues are evicted to _dialogue_summaries, evicted_total
    SHALL reflect that — not silently stay 0."""
    ds = DialogueService(seed=42)
    # 2 live
    for i in range(2):
        d = _live_dialogue(f"live_{i}")
        ds._dialogues[d.dialogue_id] = d
    # 5 evicted summaries directly
    for i in range(5):
        ds._dialogue_summaries[f"evicted_{i}"] = DialogueSummary(
            dialogue_id=f"evicted_{i}",
            initiator_id="a", invitee_id="b",
            target_location_id="loc1",
            started_tick=0, ended_tick=5,
            message_count=2,
            end_reason="completed",
        )

    inst = RuntimeInstrumentation(
        output_dir=tmp_path, seed=42, sample_every_n_ticks=1,
    )
    inst.sample_metrics(
        tick_global=10, tick_in_day=10, day_index=0,
        dialogue_service=ds,
    )
    sample = _read_latest_sample(tmp_path, 42)
    ds_stats = sample["dialogue_service"]
    assert ds_stats["live"] == 2
    assert ds_stats["ended_unevicted"] == 0
    assert ds_stats["evicted_total"] == 5, (
        f"evicted summaries not surfaced: {ds_stats}"
    )


def test_dialogue_counter_no_service(tmp_path):
    """When dialogue_service is None, counters SHALL be 0 (not crash)."""
    inst = RuntimeInstrumentation(
        output_dir=tmp_path, seed=42, sample_every_n_ticks=1,
    )
    inst.sample_metrics(
        tick_global=10, tick_in_day=10, day_index=0,
        dialogue_service=None,
    )
    sample = _read_latest_sample(tmp_path, 42)
    ds_stats = sample["dialogue_service"]
    assert ds_stats["live"] == 0
    assert ds_stats["ended_unevicted"] == 0
    assert ds_stats["evicted_total"] == 0
