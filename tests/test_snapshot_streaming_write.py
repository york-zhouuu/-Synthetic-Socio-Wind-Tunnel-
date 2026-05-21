"""Backlog 1.7 C — streaming snapshot serialization.

`SimulationCheckpoint.write_atomic` now uses `json.dump(d, file)` which
streams the encoder to the file handle instead of building the full
body string in memory via `json.dumps(d)` + `file.write(body)`. The
output bytes MUST be identical so existing snapshots remain readable
by older code and corpus / round-trip tests stay green.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from synthetic_socio_wind_tunnel.run_resilience.state_snapshot import (
    SimulationCheckpoint,
)


def _make_checkpoint() -> SimulationCheckpoint:
    return SimulationCheckpoint(
        seed=42,
        tick_index=288,
        day_index=1,
        tick_index_in_day=0,
        simulated_time=datetime(2026, 5, 22, 8, 0),
        ledger_state={"x": 1, "agents": {"a_001": {"location": "home"}}},
        agent_runtime_states={"a_001": {"foo": "bar"}},
        memory_store_state={
            "agent_events": {
                "a_001": [
                    {
                        "event_id": "ev_1",
                        "kind": "encounter",
                        "agent_id": "a_001",
                        "actor_id": "a_002",
                        "day_index": 0,
                        "encounter_count": 5,
                        "tick": 10,
                        "simulated_time": "2026-05-22T08:00:00",
                        "content": "ran into a_002",
                        "embedding": None,
                    },
                ],
            },
            "event_counter": 1,
            "consumed_feed_item_ids": {},
            "replan_count_today": {},
            "replan_no_op_count_today": {},
            "last_day_index": 1,
            "last_reflection_time": {},
            "rng_state": None,
            "noticing_seed": 0,
        },
    )


def test_write_atomic_bytes_identical_to_json_dumps(tmp_path: Path) -> None:
    """Streaming write SHALL produce bytes identical to legacy
    json.dumps output (no encoding-rule drift)."""
    snap = _make_checkpoint()
    target = tmp_path / "test.snapshot.json"
    snap.write_atomic(target)

    written = target.read_text(encoding="utf-8")
    reference = json.dumps(
        snap.model_dump(mode="json"),
        ensure_ascii=False,
        default=str,
    )
    assert written == reference, (
        f"streaming write diverged from json.dumps:\n"
        f"  written[:200]={written[:200]!r}\n"
        f"  reference[:200]={reference[:200]!r}"
    )


def test_write_then_read_round_trip(tmp_path: Path) -> None:
    """Bytes must also be loadable back into a SimulationCheckpoint
    with all fields preserved (no schema-version drift)."""
    snap = _make_checkpoint()
    target = tmp_path / "rt.snapshot.json"
    snap.write_atomic(target)

    loaded = SimulationCheckpoint.read(target)
    assert loaded.seed == snap.seed
    assert loaded.tick_index == snap.tick_index
    assert loaded.day_index == snap.day_index
    assert loaded.memory_store_state == snap.memory_store_state


def test_write_handles_large_event_list_without_doubling_memory(
    tmp_path: Path,
) -> None:
    """Sanity proxy for the streaming peak claim: 50K-event payload
    writes successfully (would OOM on 8GB CI under doubled-copy mode
    only if events are huge; this is a smoke that the path doesn't
    blow up structurally)."""
    snap = _make_checkpoint()
    fat_events = [
        {
            "event_id": f"ev_{i}",
            "kind": "encounter",
            "agent_id": "a_001",
            "actor_id": "a_002",
            "day_index": 0,
            "encounter_count": 1,
            "tick": i,
            "simulated_time": "2026-05-22T08:00:00",
            "content": "x" * 256,
            "embedding": None,
        }
        for i in range(50_000)
    ]
    snap.memory_store_state["agent_events"]["a_001"] = fat_events
    target = tmp_path / "fat.snapshot.json"
    snap.write_atomic(target)
    assert target.exists() and target.stat().st_size > 50_000 * 100
