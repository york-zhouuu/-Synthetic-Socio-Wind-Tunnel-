"""RESUME-DETERMINISM (2026-05-21): RNG state preservation across resume.

User goal: "断点续跑要和正常跑完全一模一样" (resume should be identical
to fresh). LLM stochasticity puts a hard ceiling on full byte-equality,
but the *deterministic* portion (RNG-driven decisions, ledger state)
MUST round-trip identically.

These tests verify the contract IN ISOLATION (not via full
MultiDayRunner) so failures point at a specific RNG capture/restore gap.

Per real-artifact-test-mandatory invariant (CLAUDE.md 2026-05-20):
- No mocked RNG state
- Tests write/read actual snapshot artifacts
- Assert post-restore behavior == pre-snapshot behavior

Known scope limitation documented at end of this file: snapshots
fire AFTER tick-end (`_on_tick_end_resume_hook`), so a snap labeled
`tick_global=N` actually represents "N ticks have completed". On
resume, `Orchestrator.run(day_index=D)` always runs from tick 0,
which causes a 1-tick re-execution at the day boundary when snap
fires at tick_global=288 (= day 1 tick 0). This is a snap-timing
issue, not an RNG-state issue, and is tracked separately.
"""

from __future__ import annotations

import random
from datetime import datetime
from pathlib import Path

import pytest

from synthetic_socio_wind_tunnel.attention.service import AttentionService
from synthetic_socio_wind_tunnel.conversation.dialogue_service import (
    DialogueService,
)
from synthetic_socio_wind_tunnel.memory.service import MemoryService
from synthetic_socio_wind_tunnel.run_resilience.state_snapshot import (
    SimulationCheckpoint,
)


class TestAttentionRngRoundTrip:
    """AttentionService._rng SHALL survive snapshot round-trip identically."""

    def test_rng_state_survives_snapshot_roundtrip(self) -> None:
        from synthetic_socio_wind_tunnel.ledger import Ledger
        svc_a = AttentionService(Ledger(), seed=42)
        # Burn 100 draws
        for _ in range(100):
            svc_a._rng.random()
        state = svc_a.to_snapshot_state()

        # Continue svc_a for reference
        expected_next = svc_a._rng.random()

        # Restore into fresh service
        from synthetic_socio_wind_tunnel.ledger import Ledger
        svc_b = AttentionService(Ledger(), seed=99)  # Different seed!
        svc_b.from_snapshot_state(state)
        actual_next = svc_b._rng.random()

        assert actual_next == expected_next, (
            "AttentionService._rng state did NOT round-trip through snapshot"
        )

    def test_rng_state_survives_json_roundtrip(self, tmp_path: Path) -> None:
        """Write to disk, read back, restore — must still produce same seq."""
        import json
        from synthetic_socio_wind_tunnel.ledger import Ledger
        svc_a = AttentionService(Ledger(), seed=42)
        for _ in range(50):
            svc_a._rng.random()
        state = svc_a.to_snapshot_state()

        # Write to JSON file (simulating snapshot path)
        artifact = tmp_path / "attn.json"
        artifact.write_text(json.dumps(state, default=str))
        loaded = json.loads(artifact.read_text())

        expected = svc_a._rng.random()
        from synthetic_socio_wind_tunnel.ledger import Ledger
        svc_b = AttentionService(Ledger(), seed=999)
        svc_b.from_snapshot_state(loaded)
        actual = svc_b._rng.random()
        assert actual == expected


class TestMemoryRngRoundTrip:
    """MemoryService._rng SHALL survive snapshot round-trip identically."""

    def test_rng_state_survives_snapshot_roundtrip(self) -> None:
        svc_a = MemoryService(seed=42)
        for _ in range(100):
            svc_a._rng.random()
        state = svc_a.to_snapshot_state()
        expected_next = svc_a._rng.random()

        svc_b = MemoryService(seed=99)
        svc_b.from_snapshot_state(state)
        actual_next = svc_b._rng.random()

        assert actual_next == expected_next, (
            "MemoryService._rng state did NOT round-trip through snapshot"
        )


class TestDialogueRngRoundTrip:
    """DialogueService._rng SHALL survive snapshot round-trip identically."""

    def test_rng_state_survives_snapshot_roundtrip(self) -> None:
        svc_a = DialogueService(seed=42)
        for _ in range(100):
            svc_a._rng.random()
        state = svc_a.to_snapshot_state()
        expected_next = svc_a._rng.random()

        svc_b = DialogueService(seed=99)
        svc_b.from_snapshot_state(state)
        actual_next = svc_b._rng.random()

        assert actual_next == expected_next, (
            "DialogueService._rng state did NOT round-trip through snapshot"
        )


class TestSnapshotRngFieldRoundtrip:
    """SimulationCheckpoint.rng_state field SHALL accept + restore arbitrary
    named RNGs (the capture_rng / restore_rng path)."""

    def test_external_rng_via_rng_state_field(self, tmp_path: Path) -> None:
        """A non-service RNG (e.g. orchestrator-owned) can be persisted via
        rng_state field on SimulationCheckpoint."""
        from synthetic_socio_wind_tunnel.run_resilience.state_snapshot import (
            capture_rng, restore_rng,
        )

        external_rng = random.Random(2026)
        for _ in range(50):
            external_rng.random()

        captured = capture_rng({"external": external_rng})
        snap = SimulationCheckpoint(
            seed=42, tick_index=12, day_index=0,
            simulated_time=datetime(2026, 4, 22, 1, 0, 0),
            rng_state=captured,
        )
        snap_path = tmp_path / "snap.json"
        snap.write_atomic(snap_path)

        # Read back
        snap2 = SimulationCheckpoint.read(snap_path)

        # Continue external_rng for reference
        expected = external_rng.random()

        # Restore into fresh RNG via the documented capture_rng path
        fresh_rng = random.Random(1)  # Different seed
        restore_rng(snap2.rng_state, {"external": fresh_rng})
        actual = fresh_rng.random()
        assert actual == expected
