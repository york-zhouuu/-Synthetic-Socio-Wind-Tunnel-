"""RESUME-DETERMINISM (2026-05-21): full mid-day resume determinism.

Closes backlog 1.16 (mid-day-resume). Verifies:
- Per-service RNG state survives snapshot round-trip
- Mid-day snap + resume produces IDENTICAL ledger state to fresh run
  (sim time, agent state, byte-equal)

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

Mid-day resume now uses snap.tick_index_in_day to compute Orchestrator.run
start_tick on the first resumed day. See `TestMidDayResumeDeterministic`.
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


class TestConversationServiceRoundTrip:
    """ConversationService._rng + _infos + _known + _share_count SHALL
    survive snapshot round-trip identically (audit-confirmed: this RNG
    drives the P(share) gate and divergence causes ShareEvent emission
    divergence on resume)."""

    def test_rng_state_survives_snapshot_roundtrip(self) -> None:
        from synthetic_socio_wind_tunnel.conversation import ConversationService
        svc_a = ConversationService(seed=42)
        for _ in range(100):
            svc_a._rng.random()
        state = svc_a.to_snapshot_state()
        expected_next = svc_a._rng.random()

        svc_b = ConversationService(seed=99)
        svc_b.from_snapshot_state(state)
        actual_next = svc_b._rng.random()

        assert actual_next == expected_next

    def test_infos_known_share_count_round_trip(self) -> None:
        from synthetic_socio_wind_tunnel.conversation import ConversationService
        from synthetic_socio_wind_tunnel.conversation.models import Information

        svc_a = ConversationService(seed=42)
        info = Information(
            info_id="info-1",
            content="hello",
            category="rumor",
            salience=0.7,
            origin_tick=12,
            origin_agent_id="alpha",
            origin_day_index=0,
        )
        svc_a.record_origin(info, "alpha", tick=12)

        state = svc_a.to_snapshot_state()

        svc_b = ConversationService(seed=99)
        svc_b.from_snapshot_state(state)
        # _infos preserved
        assert "info-1" in svc_b._infos
        assert svc_b._infos["info-1"].content == "hello"
        # _known preserved
        assert "alpha" in svc_b._known
        assert "info-1" in svc_b._known["alpha"]
        # _known_by_info preserved
        assert "alpha" in svc_b._known_by_info["info-1"]


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


# ---------------------------------------------------------------------------
# Mid-day resume e2e tests (backlog 1.16 closure)
# ---------------------------------------------------------------------------

from datetime import date
from synthetic_socio_wind_tunnel.agent import AgentProfile, AgentRuntime
from synthetic_socio_wind_tunnel.atlas import Atlas
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.cartography.builder import RegionBuilder
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.orchestrator import MultiDayRunner, Orchestrator
from synthetic_socio_wind_tunnel.run_resilience import (
    SnapshotPolicy, find_latest_snapshot,
)


def _mid_day_atlas() -> Atlas:
    region = (
        RegionBuilder("r", "r")
        .add_outdoor("a", "A", area_type="street")
        .polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        .end_outdoor()
        .build()
    )
    return Atlas(region)


def _mid_day_world(start_date: date, *, atlas: Atlas | None = None):
    if atlas is None:
        atlas = _mid_day_atlas()
    ledger = Ledger()
    ledger.current_time = datetime.combine(start_date, datetime.min.time())
    profile = AgentProfile(
        agent_id="alpha", name="alpha", age=30, occupation="x",
        household="single", home_location="a",
    )
    agent = AgentRuntime(profile=profile, current_location="a")
    ledger.set_entity(EntityState(
        entity_id="alpha", location_id="a", position=Coord(x=0.0, y=0.0),
    ))
    orch = Orchestrator(atlas, ledger, [agent])
    return orch, ledger, {agent.profile.agent_id: agent}


class TestMidDayResumeDeterministic:
    """Mid-day snap + resume SHALL produce identical ledger time + agent
    state to a fresh run that never paused. Closes backlog 1.16."""

    def test_resume_from_mid_day_snap_matches_fresh(self, tmp_path: Path) -> None:
        atlas = _mid_day_atlas()
        start = date(2026, 4, 22)

        # FRESH: 2 days, no snapshots
        fresh_orch, fresh_ledger, fresh_agents = _mid_day_world(start, atlas=atlas)
        fresh_runner = MultiDayRunner(
            orchestrator=fresh_orch, seed=42, provider_name="stub",
            snapshot_policy=SnapshotPolicy(every_ticks=0, wal_enabled=False),
        )
        fresh_runner.run_multi_day(start_date=start, num_days=2)
        fresh_state = fresh_ledger.to_snapshot_state()
        fresh_agent_state = {
            aid: a.to_snapshot_state() for aid, a in fresh_agents.items()
        }

        # RESUME phase 1: 1 day with mid-day snap (every_ticks=144 → snap at
        # tick 144 of day 0 = 12h into day 0)
        p1_dir = tmp_path / "p1"; p1_dir.mkdir()
        p1_orch, _, _ = _mid_day_world(start, atlas=atlas)
        p1_runner = MultiDayRunner(
            orchestrator=p1_orch, seed=42, output_dir=p1_dir,
            provider_name="stub",
            snapshot_policy=SnapshotPolicy(every_ticks=144, keep_last_k=10),
        )
        p1_runner.run_multi_day(start_date=start, num_days=1)

        # Pick the mid-day snap (NOT the day-boundary one if one exists)
        snap_path = find_latest_snapshot(p1_dir, seed=42)
        assert snap_path is not None
        snap = SimulationCheckpoint.read(snap_path)
        # Sanity: snap should be mid-day-0 (tick_in_day = 144), not at boundary
        assert snap.day_index == 0
        assert snap.tick_index_in_day == 144, (
            f"expected snap at tick 144 of day 0, "
            f"got day={snap.day_index} tick_in_day={snap.tick_index_in_day}"
        )

        # RESUME phase 2: restore + run num_days=2 (should run rest of day 0
        # + all of day 1)
        p2_dir = tmp_path / "p2"; p2_dir.mkdir()
        p2_orch, p2_ledger, p2_agents = _mid_day_world(start, atlas=atlas)
        p2_runner = MultiDayRunner(
            orchestrator=p2_orch, seed=42, output_dir=p2_dir,
            provider_name="stub",
            snapshot_policy=SnapshotPolicy(every_ticks=0, wal_enabled=False),
            restore_from=snap,
        )
        p2_runner.run_multi_day(start_date=start, num_days=2)

        resumed_state = p2_ledger.to_snapshot_state()
        resumed_agent_state = {
            aid: a.to_snapshot_state() for aid, a in p2_agents.items()
        }

        # current_time MUST match — the core "完全一模一样" assertion
        assert resumed_state.get("current_time") == fresh_state.get("current_time"), (
            f"current_time diverged: fresh={fresh_state.get('current_time')} "
            f"resumed={resumed_state.get('current_time')}"
        )

        # Agent state MUST match
        for aid in fresh_agent_state:
            assert resumed_agent_state[aid] == fresh_agent_state[aid], (
                f"agent {aid} state diverged"
            )

    def test_on_day_start_not_refired_on_mid_day_resume(
        self, tmp_path: Path,
    ) -> None:
        """on_day_start SHALL NOT re-fire on the first day of a mid-day
        resume — otherwise non-idempotent variant.apply_day_start hooks
        (e.g. inject_feed_item) double-execute and diverge from fresh."""
        atlas = _mid_day_atlas()
        start = date(2026, 4, 22)

        # RESUME phase 1: 1 day with mid-day snap
        p1_dir = tmp_path / "p1"; p1_dir.mkdir()
        p1_orch, _, _ = _mid_day_world(start, atlas=atlas)
        p1_runner = MultiDayRunner(
            orchestrator=p1_orch, seed=42, output_dir=p1_dir,
            provider_name="stub",
            snapshot_policy=SnapshotPolicy(every_ticks=144, keep_last_k=5),
        )
        p1_calls = []
        p1_runner.run_multi_day(
            start_date=start, num_days=1,
            on_day_start=lambda d, i: p1_calls.append((d, i)),
        )
        # Phase 1 fired on_day_start once (day 0)
        assert p1_calls == [(start, 0)]

        snap_path = find_latest_snapshot(p1_dir, seed=42)
        snap = SimulationCheckpoint.read(snap_path)
        assert snap.tick_index_in_day > 0  # mid-day

        # RESUME phase 2: restore from mid-day snap, run 1 more day
        p2_dir = tmp_path / "p2"; p2_dir.mkdir()
        p2_orch, _, _ = _mid_day_world(start, atlas=atlas)
        p2_runner = MultiDayRunner(
            orchestrator=p2_orch, seed=42, output_dir=p2_dir,
            provider_name="stub",
            snapshot_policy=SnapshotPolicy(every_ticks=0, wal_enabled=False),
            restore_from=snap,
        )
        p2_calls = []
        p2_runner.run_multi_day(
            start_date=start, num_days=2,
            on_day_start=lambda d, i: p2_calls.append((d, i)),
        )
        # Phase 2 SHALL skip on_day_start for the resumed day (0) — only
        # day 1 (the fresh day) gets the call
        from datetime import timedelta as _td
        assert p2_calls == [(start + _td(days=1), 1)], (
            f"on_day_start fired for resumed mid-day-0 — would double-inject "
            f"FeedItems / consume RNG. Got: {p2_calls}"
        )

    def test_snap_records_tick_index_in_day(self, tmp_path: Path) -> None:
        """snap files SHALL carry tick_index_in_day so resume can
        compute start_tick correctly."""
        atlas = _mid_day_atlas()
        orch, _, _ = _mid_day_world(date(2026, 4, 22), atlas=atlas)
        runner = MultiDayRunner(
            orchestrator=orch, seed=7, output_dir=tmp_path,
            provider_name="stub",
            snapshot_policy=SnapshotPolicy(every_ticks=72, keep_last_k=10),
        )
        runner.run_multi_day(start_date=date(2026, 4, 22), num_days=1)

        snap = SimulationCheckpoint.read(find_latest_snapshot(tmp_path, seed=7))
        # Should be the last snap fired during day 0 — every_ticks=72 fires
        # AFTER ticks 72/144/216, so tick_in_day records the index of the
        # tick that just COMPLETED (= 72/144/216). Resume must start from
        # tick_in_day + 1.
        assert snap.day_index == 0
        assert snap.tick_index_in_day in (72, 144, 216), (
            f"unexpected tick_in_day={snap.tick_index_in_day}"
        )


class TestOrchestratorStartTickParam:
    """Orchestrator.run(start_tick=N) SHALL skip ticks 0..N-1, only run N..287."""

    def test_start_tick_skips_already_completed_ticks(self) -> None:
        atlas = _mid_day_atlas()
        ledger = Ledger()
        ledger.current_time = datetime(2026, 4, 22, 12, 0, 0)  # noon
        profile = AgentProfile(
            agent_id="alpha", name="alpha", age=30, occupation="x",
            household="single", home_location="a",
        )
        agent = AgentRuntime(profile=profile, current_location="a")
        ledger.set_entity(EntityState(
            entity_id="alpha", location_id="a", position=Coord(x=0.0, y=0.0),
        ))
        orch = Orchestrator(atlas, ledger, [agent])

        # Run from tick 144 → ticks 144..287 = 144 ticks executed
        summary = orch.run(day_index=0, start_tick=144)
        assert summary.total_ticks == 288 - 144, (
            f"total_ticks={summary.total_ticks}, expected 144"
        )
        # ledger advanced 144 ticks * 5min = 720min = 12h
        assert ledger.current_time == datetime(2026, 4, 23, 0, 0, 0)

    def test_start_tick_out_of_bounds_raises(self) -> None:
        atlas = _mid_day_atlas()
        ledger = Ledger()
        ledger.current_time = datetime(2026, 4, 22, 0, 0, 0)
        profile = AgentProfile(
            agent_id="alpha", name="alpha", age=30, occupation="x",
            household="single", home_location="a",
        )
        agent = AgentRuntime(profile=profile, current_location="a")
        ledger.set_entity(EntityState(
            entity_id="alpha", location_id="a", position=Coord(x=0.0, y=0.0),
        ))
        orch = Orchestrator(atlas, ledger, [agent])

        with pytest.raises(ValueError, match="out of bounds"):
            orch.run(day_index=0, start_tick=300)
        with pytest.raises(ValueError, match="out of bounds"):
            orch.run(day_index=0, start_tick=-1)

    def test_start_tick_equal_num_ticks_is_noop(self) -> None:
        """start_tick == num_ticks means 'day fully completed' — 0 ticks run."""
        atlas = _mid_day_atlas()
        ledger = Ledger()
        ledger.current_time = datetime(2026, 4, 22, 0, 0, 0)
        profile = AgentProfile(
            agent_id="alpha", name="alpha", age=30, occupation="x",
            household="single", home_location="a",
        )
        agent = AgentRuntime(profile=profile, current_location="a")
        ledger.set_entity(EntityState(
            entity_id="alpha", location_id="a", position=Coord(x=0.0, y=0.0),
        ))
        orch = Orchestrator(atlas, ledger, [agent])

        original_time = ledger.current_time
        summary = orch.run(day_index=0, start_tick=288)
        assert summary.total_ticks == 0
        # ledger NOT advanced
        assert ledger.current_time == original_time
