"""Tests for SimulationCheckpoint.restore_into end-to-end orchestration.

Builds a non-trivial state across all 4 subsystems, snapshots it,
restores into fresh instances, verifies each subsystem's to_snapshot_state()
matches.
"""

from __future__ import annotations

import json
import random
from datetime import datetime
from pathlib import Path

import pytest

from synthetic_socio_wind_tunnel.agent import AgentProfile, AgentRuntime
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.attention.service import AttentionService
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.memory import MemoryService
from synthetic_socio_wind_tunnel.run_resilience import (
    SimulationCheckpoint,
    capture_rng,
)


def _make_world(seed: int = 42):
    """Build (ledger, agents, memory, attention) with some non-trivial state."""
    ledger = Ledger()
    ledger.current_time = datetime(2026, 4, 22, 10, 30)
    ledger.set_entity(EntityState(
        entity_id="alice", location_id="cafe_main",
        position=Coord(x=10.0, y=20.0),
    ))
    ledger.set_entity(EntityState(
        entity_id="bob", location_id="park_a",
        position=Coord(x=5.0, y=5.0),
    ))

    profile_a = AgentProfile(
        agent_id="alice", name="Alice", age=30, occupation="dev",
        household="single", home_location="home_a",
    )
    agent_a = AgentRuntime(profile=profile_a, current_location="cafe_main")
    agent_a._movement_queue = ["cafe_main", "park_a"]
    agent_a._moving = True

    profile_b = AgentProfile(
        agent_id="bob", name="Bob", age=25, occupation="student",
        household="single", home_location="home_b",
    )
    agent_b = AgentRuntime(profile=profile_b, current_location="park_a")

    memory = MemoryService(seed=seed)
    # Inject events
    from synthetic_socio_wind_tunnel.memory.models import MemoryEvent
    for i in range(3):
        memory._store_for("alice").append(MemoryEvent(
            event_id=f"alice_e{i}", agent_id="alice", tick=i,
            simulated_time=datetime(2026, 4, 22, 8, i),
            kind="encounter", content=f"event {i}",
            location_id="cafe_main", day_index=0,
        ))

    attention = AttentionService(ledger, seed=seed)
    attention.set_phone_attention_baseline("alice", 0.4)
    attention.set_phone_attention_baseline("bob", 0.2)

    return ledger, {"alice": agent_a, "bob": agent_b}, memory, attention


def _make_empty_world():
    """Build fresh (empty) versions of all subsystems."""
    ledger = Ledger()
    profile_a = AgentProfile(
        agent_id="alice", name="Alice", age=30, occupation="dev",
        household="single", home_location="home_a",
    )
    profile_b = AgentProfile(
        agent_id="bob", name="Bob", age=25, occupation="student",
        household="single", home_location="home_b",
    )
    agents = {
        "alice": AgentRuntime(profile=profile_a, current_location=""),
        "bob": AgentRuntime(profile=profile_b, current_location=""),
    }
    memory = MemoryService(seed=99)
    attention = AttentionService(ledger, seed=99)
    return ledger, agents, memory, attention


def _build_snapshot(ledger, agents, memory, attention, *, seed=42, tick=100, day=0):
    return SimulationCheckpoint(
        seed=seed, tick_index=tick, day_index=day,
        simulated_time=ledger.current_time,
        ledger_state=ledger.to_snapshot_state(),
        agent_runtime_states={aid: a.to_snapshot_state() for aid, a in agents.items()},
        memory_store_state=memory.to_snapshot_state(),
        attention_service_state=attention.to_snapshot_state(),
        rng_state={},
        pending_ops_meta={},
        provider="stub",
    )


class TestRestoreInto:

    def test_round_trip_full(self, tmp_path: Path) -> None:
        # Build source world
        ledger, agents, memory, attention = _make_world()
        snap = _build_snapshot(ledger, agents, memory, attention)

        # Build empty target world
        target_ledger, target_agents, target_memory, target_attention = _make_empty_world()

        # Restore
        snap.restore_into(
            ledger=target_ledger,
            agents=target_agents,
            memory_service=target_memory,
            attention_service=target_attention,
        )

        # Each subsystem's snapshot must equal the source
        assert target_ledger.to_snapshot_state() == ledger.to_snapshot_state()
        for aid, target_agent in target_agents.items():
            assert target_agent.to_snapshot_state() == agents[aid].to_snapshot_state()
        assert target_memory.to_snapshot_state() == memory.to_snapshot_state()
        assert target_attention.to_snapshot_state() == attention.to_snapshot_state()

    def test_round_trip_through_disk(self, tmp_path: Path) -> None:
        """End-to-end: build → snapshot → write → read → restore → verify."""
        ledger, agents, memory, attention = _make_world()
        snap = _build_snapshot(ledger, agents, memory, attention)

        path = tmp_path / "snap.json"
        snap.write_atomic(path)
        snap2 = SimulationCheckpoint.read(path)

        target_ledger, target_agents, target_memory, target_attention = _make_empty_world()
        snap2.restore_into(
            ledger=target_ledger,
            agents=target_agents,
            memory_service=target_memory,
            attention_service=target_attention,
        )

        assert target_ledger.to_snapshot_state() == ledger.to_snapshot_state()
        assert target_memory.to_snapshot_state() == memory.to_snapshot_state()

    def test_missing_agent_raises(self) -> None:
        ledger, agents, memory, attention = _make_world()
        snap = _build_snapshot(ledger, agents, memory, attention)

        # Build target world WITHOUT bob
        target_ledger, target_agents, target_memory, target_attention = _make_empty_world()
        del target_agents["bob"]

        with pytest.raises(ValueError) as exc:
            snap.restore_into(
                ledger=target_ledger,
                agents=target_agents,
                memory_service=target_memory,
                attention_service=target_attention,
            )
        assert "bob" in str(exc.value)

    def test_optional_services_skipped_when_none(self) -> None:
        """memory/attention=None should not raise; ledger/agents still restored."""
        ledger, agents, memory, attention = _make_world()
        snap = _build_snapshot(ledger, agents, memory, attention)

        target_ledger, target_agents, _, _ = _make_empty_world()
        snap.restore_into(
            ledger=target_ledger,
            agents=target_agents,
            memory_service=None,
            attention_service=None,
        )
        # ledger / agents restored
        assert target_ledger.to_snapshot_state() == ledger.to_snapshot_state()

    def test_rng_restore_via_named_rngs(self) -> None:
        """RNG state captured + restored to caller-provided named map."""
        orch_rng = random.Random(42)
        for _ in range(20):
            orch_rng.random()  # burn entropy

        ledger, agents, memory, attention = _make_world()
        snap = SimulationCheckpoint(
            seed=42, tick_index=100, day_index=0,
            simulated_time=ledger.current_time,
            ledger_state={}, agent_runtime_states={},
            memory_store_state={}, attention_service_state={},
            rng_state=capture_rng({"orch": orch_rng}),
            pending_ops_meta={}, provider="stub",
        )

        # Now orch_rng.random() == X; the snapshot captured state BEFORE this call
        # Wait — capture_rng was called AFTER 20 burns; so snapshot has state AFTER 20 burns
        # The "expected next" is the 21st random() call
        expected_next = orch_rng.random()

        # Fresh rng to restore into
        fresh_rng = random.Random(99)  # different seed
        snap.restore_into(named_rngs={"orch": fresh_rng})

        actual_next = fresh_rng.random()
        assert actual_next == expected_next
