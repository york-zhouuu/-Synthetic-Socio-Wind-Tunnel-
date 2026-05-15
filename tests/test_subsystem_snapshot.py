"""Round-trip tests for 4 subsystems' to_snapshot_state / from_snapshot_state.

For each subsystem:
1. Build a non-trivial in-memory state
2. Call to_snapshot_state() → JSON-safe dict
3. Construct a fresh instance + call from_snapshot_state(state)
4. Verify the new instance's to_snapshot_state() == state (byte-equal)

Also test:
- JSON.dumps the state succeeds (true JSON-safety)
- Mismatched agent_id / non-dict state raises ValueError
"""

from __future__ import annotations

import json
import random
from datetime import datetime
from pathlib import Path

import pytest

from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

class TestLedgerSnapshot:

    def _make_ledger(self) -> Ledger:
        ledger = Ledger()
        ledger.current_time = datetime(2026, 4, 22, 8, 0)
        ledger.set_entity(EntityState(
            entity_id="alice", location_id="cafe_main",
            position=Coord(x=1.0, y=2.0),
        ))
        ledger.set_entity(EntityState(
            entity_id="bob", location_id="park_a",
            position=Coord(x=3.0, y=4.0),
        ))
        return ledger

    def test_round_trip(self) -> None:
        ledger = self._make_ledger()
        state = ledger.to_snapshot_state()
        # JSON-safe
        json.dumps(state)

        new_ledger = Ledger()
        new_ledger.from_snapshot_state(state)
        assert new_ledger.to_snapshot_state() == state

    def test_entity_states_preserved(self) -> None:
        ledger = self._make_ledger()
        state = ledger.to_snapshot_state()
        new_ledger = Ledger()
        new_ledger.from_snapshot_state(state)
        e = new_ledger.get_entity("alice")
        assert e is not None
        assert e.location_id == "cafe_main"
        assert e.position.x == 1.0

    def test_non_dict_state_raises(self) -> None:
        ledger = Ledger()
        with pytest.raises(ValueError):
            ledger.from_snapshot_state("not a dict")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AgentRuntime
# ---------------------------------------------------------------------------

class TestAgentRuntimeSnapshot:

    def _make_agent(self):
        from synthetic_socio_wind_tunnel.agent import AgentProfile, AgentRuntime
        profile = AgentProfile(
            agent_id="alice", name="Alice", age=30, occupation="dev",
            household="single", home_location="home_a",
        )
        agent = AgentRuntime(profile=profile, current_location="cafe_main")
        return agent

    def test_round_trip_minimal(self) -> None:
        agent = self._make_agent()
        state = agent.to_snapshot_state()
        json.dumps(state)  # JSON-safe

        from synthetic_socio_wind_tunnel.agent import AgentRuntime, AgentProfile
        profile2 = AgentProfile(
            agent_id="alice", name="Alice", age=30, occupation="dev",
            household="single", home_location="home_a",
        )
        agent2 = AgentRuntime(profile=profile2, current_location="")
        agent2.from_snapshot_state(state)
        # Round-trip equivalence (modulo per-call RNG state if any)
        assert agent2.to_snapshot_state() == state

    def test_movement_state_preserved(self) -> None:
        agent = self._make_agent()
        agent._movement_queue = ["loc_1", "loc_2", "loc_3"]
        agent._moving = True
        state = agent.to_snapshot_state()

        from synthetic_socio_wind_tunnel.agent import AgentRuntime, AgentProfile
        profile2 = AgentProfile(
            agent_id="alice", name="Alice", age=30, occupation="dev",
            household="single", home_location="home_a",
        )
        agent2 = AgentRuntime(profile=profile2, current_location="")
        agent2.from_snapshot_state(state)
        assert agent2._movement_queue == ["loc_1", "loc_2", "loc_3"]
        assert agent2._moving is True

    def test_agent_id_mismatch_raises(self) -> None:
        agent = self._make_agent()
        state = agent.to_snapshot_state()
        state["agent_id"] = "different_id"
        with pytest.raises(ValueError) as exc:
            agent.from_snapshot_state(state)
        assert "agent_id" in str(exc.value)

    def test_tick_inputs_cleared_after_restore(self) -> None:
        """In-flight LLM ops (in _tick_inputs) must be abandoned, not preserved."""
        agent = self._make_agent()
        # Inject a fake tick_input
        from types import SimpleNamespace
        agent._tick_inputs = [SimpleNamespace(op_id="fake", payload={})]
        state = agent.to_snapshot_state()
        # State should NOT include _tick_inputs
        assert "_tick_inputs" not in state

        from synthetic_socio_wind_tunnel.agent import AgentRuntime, AgentProfile
        profile2 = AgentProfile(
            agent_id="alice", name="Alice", age=30, occupation="dev",
            household="single", home_location="home_a",
        )
        agent2 = AgentRuntime(profile=profile2, current_location="")
        agent2.from_snapshot_state(state)
        assert agent2._tick_inputs == []

    def test_invite_rng_round_trip(self) -> None:
        agent = self._make_agent()
        # Burn entropy
        for _ in range(50):
            agent._invite_rng.random()

        # Capture state AFTER burning; the next random() is the "next" we want to predict
        state = agent.to_snapshot_state()
        expected_next = agent._invite_rng.random()

        from synthetic_socio_wind_tunnel.agent import AgentRuntime, AgentProfile
        profile2 = AgentProfile(
            agent_id="alice", name="Alice", age=30, occupation="dev",
            household="single", home_location="home_a",
        )
        agent2 = AgentRuntime(profile=profile2, current_location="")
        agent2.from_snapshot_state(state)
        actual_next = agent2._invite_rng.random()
        assert actual_next == expected_next


# ---------------------------------------------------------------------------
# MemoryService
# ---------------------------------------------------------------------------

class TestMemoryServiceSnapshot:

    def _make_memory(self):
        from synthetic_socio_wind_tunnel.memory import MemoryService
        return MemoryService(seed=42)

    def test_round_trip_empty(self) -> None:
        m = self._make_memory()
        state = m.to_snapshot_state()
        json.dumps(state)

        m2 = self._make_memory()
        m2.from_snapshot_state(state)
        assert m2.to_snapshot_state() == state

    def test_round_trip_with_events(self) -> None:
        from synthetic_socio_wind_tunnel.memory.models import MemoryEvent
        m = self._make_memory()
        # Inject events into per-agent stores
        for i in range(5):
            ev = MemoryEvent(
                event_id=f"e{i}", agent_id="alice", tick=i,
                simulated_time=datetime(2026, 4, 22, 8, i),
                kind="encounter", content=f"event {i}",
                location_id="cafe_main", day_index=0,
            )
            m._store_for("alice").append(ev)
        state = m.to_snapshot_state()

        m2 = self._make_memory()
        m2.from_snapshot_state(state)
        # 5 events for alice
        store = m2._store_for("alice")
        assert len(store) == 5
        # Round-trip equivalence
        assert m2.to_snapshot_state() == state

    def test_non_dict_state_raises(self) -> None:
        m = self._make_memory()
        with pytest.raises(ValueError):
            m.from_snapshot_state([])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AttentionService
# ---------------------------------------------------------------------------

class TestAttentionServiceSnapshot:

    def _make_attention(self):
        from synthetic_socio_wind_tunnel.attention.service import AttentionService
        ledger = Ledger()
        ledger.current_time = datetime(2026, 4, 22, 8, 0)
        return AttentionService(ledger, seed=42)

    def test_round_trip_empty(self) -> None:
        a = self._make_attention()
        state = a.to_snapshot_state()
        json.dumps(state)

        ledger2 = Ledger()
        from synthetic_socio_wind_tunnel.attention.service import AttentionService
        a2 = AttentionService(ledger2, seed=99)
        a2.from_snapshot_state(state)
        assert a2.to_snapshot_state() == state

    def test_phone_attention_preserved(self) -> None:
        a = self._make_attention()
        a.set_phone_attention_baseline("alice", 0.3)
        a.set_phone_attention_baseline("bob", 0.5)
        state = a.to_snapshot_state()

        ledger2 = Ledger()
        from synthetic_socio_wind_tunnel.attention.service import AttentionService
        a2 = AttentionService(ledger2)
        a2.from_snapshot_state(state)
        # Within numeric epsilon
        assert abs(a2.get_phone_attention("alice") - 0.3) < 1e-6
        assert abs(a2.get_phone_attention("bob") - 0.5) < 1e-6

    def test_non_dict_state_raises(self) -> None:
        a = self._make_attention()
        with pytest.raises(ValueError):
            a.from_snapshot_state("nope")  # type: ignore[arg-type]
