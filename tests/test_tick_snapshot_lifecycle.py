"""Tests for MultiDayRunner per-tick WAL + per-N-tick snapshot lifecycle.

Covers:
- WAL line counts == total ticks (1d × 288 = 288 lines)
- snapshot files rolled at every_ticks=24 boundaries, keeping last K
- wal_enabled=False produces no WAL file
- every_ticks=0 produces no snapshot files
- Final snapshot on graceful_stop_requested
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from synthetic_socio_wind_tunnel.agent import (
    AgentProfile, AgentRuntime,
)
from synthetic_socio_wind_tunnel.atlas import Atlas
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.cartography.builder import RegionBuilder
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.orchestrator import MultiDayRunner, Orchestrator
from synthetic_socio_wind_tunnel.run_resilience import (
    SimulationCheckpoint, SnapshotPolicy,
)


def _small_atlas() -> Atlas:
    region = (
        RegionBuilder("r", "r")
        .add_outdoor("a", "A", area_type="street")
        .polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        .end_outdoor()
        .add_outdoor("b", "B", area_type="street")
        .polygon([(15, 0), (25, 0), (25, 10), (15, 10)])
        .end_outdoor()
        .connect("a", "b", path_type="road", distance=5.0)
        .build()
    )
    return Atlas(region)


def _agent(agent_id: str) -> AgentRuntime:
    profile = AgentProfile(
        agent_id=agent_id, name=agent_id, age=30, occupation="x",
        household="single", home_location="a",
    )
    return AgentRuntime(profile=profile, current_location="a")


def _make_orch(start_date: date):
    atlas = _small_atlas()
    ledger = Ledger()
    ledger.current_time = datetime.combine(start_date, datetime.min.time())
    agent = _agent("alpha")
    ledger.set_entity(EntityState(
        entity_id=agent.profile.agent_id,
        location_id=agent.current_location,
        position=Coord(x=0.0, y=0.0),
    ))
    orch = Orchestrator(atlas, ledger, [agent])
    return orch, ledger, agent


class TestWALLifecycle:

    def test_wal_lines_match_total_ticks_1day(self, tmp_path: Path) -> None:
        orch, _, _ = _make_orch(date(2026, 4, 22))
        runner = MultiDayRunner(
            orchestrator=orch, seed=42, output_dir=tmp_path,
            provider_name="stub",
            snapshot_policy=SnapshotPolicy(every_ticks=0, wal_enabled=True),
        )
        runner.run_multi_day(start_date=date(2026, 4, 22), num_days=1)
        wal_path = tmp_path / "seed_42.wal.jsonl"
        assert wal_path.exists()
        lines = wal_path.read_text().strip().split("\n")
        assert len(lines) == 288  # 1 day × 288 ticks

    def test_wal_lines_for_3_days(self, tmp_path: Path) -> None:
        orch, _, _ = _make_orch(date(2026, 4, 22))
        runner = MultiDayRunner(
            orchestrator=orch, seed=7, output_dir=tmp_path,
            provider_name="stub",
            snapshot_policy=SnapshotPolicy(every_ticks=0, wal_enabled=True),
        )
        runner.run_multi_day(start_date=date(2026, 4, 22), num_days=3)
        wal_path = tmp_path / "seed_7.wal.jsonl"
        lines = wal_path.read_text().strip().split("\n")
        assert len(lines) == 288 * 3
        last = json.loads(lines[-1])
        # Last tick_index_global = 3 * 288 - 1 = 863
        assert last["tick_index"] == 863
        assert last["day_index"] == 2

    def test_wal_disabled_no_file(self, tmp_path: Path) -> None:
        orch, _, _ = _make_orch(date(2026, 4, 22))
        runner = MultiDayRunner(
            orchestrator=orch, seed=42, output_dir=tmp_path,
            provider_name="stub",
            snapshot_policy=SnapshotPolicy(every_ticks=0, wal_enabled=False),
        )
        runner.run_multi_day(start_date=date(2026, 4, 22), num_days=1)
        assert not (tmp_path / "seed_42.wal.jsonl").exists()

    def test_no_output_dir_no_wal(self, tmp_path: Path) -> None:
        orch, _, _ = _make_orch(date(2026, 4, 22))
        runner = MultiDayRunner(
            orchestrator=orch, seed=42,
            snapshot_policy=SnapshotPolicy(wal_enabled=True),
        )
        runner.run_multi_day(start_date=date(2026, 4, 22), num_days=1)
        # No files in tmp_path because output_dir was not provided
        assert list(tmp_path.glob("seed_*.wal.jsonl")) == []


class TestSnapshotLifecycle:

    def test_snapshots_at_24_tick_boundaries(self, tmp_path: Path) -> None:
        orch, _, _ = _make_orch(date(2026, 4, 22))
        runner = MultiDayRunner(
            orchestrator=orch, seed=42, output_dir=tmp_path,
            provider_name="stub",
            snapshot_policy=SnapshotPolicy(every_ticks=24, keep_last_k=20),
        )
        runner.run_multi_day(start_date=date(2026, 4, 22), num_days=1)
        # 1 day = 288 ticks (tick_index 0..287); global tick max = 287
        # Snapshots at tick_global % 24 == 0 && > 0 → 24, 48, ..., 264 (11 entries)
        snaps = sorted(tmp_path.glob("seed_42_tick*.snapshot.json"))
        ticks = sorted(int(p.name.split("tick")[1].split(".")[0]) for p in snaps)
        assert ticks == [24 * (i + 1) for i in range(11)]  # 24..264

    def test_keep_last_k_rolls_old_snapshots(self, tmp_path: Path) -> None:
        orch, _, _ = _make_orch(date(2026, 4, 22))
        runner = MultiDayRunner(
            orchestrator=orch, seed=42, output_dir=tmp_path,
            provider_name="stub",
            snapshot_policy=SnapshotPolicy(every_ticks=24, keep_last_k=2),
        )
        runner.run_multi_day(start_date=date(2026, 4, 22), num_days=1)
        # Only last 2 snapshots remain (240 and 264 are the last 2 written;
        # 288 is not reachable since tick_index max = 287)
        snaps = sorted(tmp_path.glob("seed_42_tick*.snapshot.json"))
        ticks = sorted(int(p.name.split("tick")[1].split(".")[0]) for p in snaps)
        assert ticks == [240, 264]

    def test_every_ticks_zero_no_snapshots(self, tmp_path: Path) -> None:
        orch, _, _ = _make_orch(date(2026, 4, 22))
        runner = MultiDayRunner(
            orchestrator=orch, seed=42, output_dir=tmp_path,
            provider_name="stub",
            snapshot_policy=SnapshotPolicy(every_ticks=0, wal_enabled=True),
        )
        runner.run_multi_day(start_date=date(2026, 4, 22), num_days=1)
        assert list(tmp_path.glob("seed_42_tick*.snapshot.json")) == []

    def test_snapshot_content_valid(self, tmp_path: Path) -> None:
        orch, _, _ = _make_orch(date(2026, 4, 22))
        runner = MultiDayRunner(
            orchestrator=orch, seed=42, output_dir=tmp_path,
            provider_name="stub",
            snapshot_policy=SnapshotPolicy(every_ticks=24, keep_last_k=20),
        )
        runner.run_multi_day(start_date=date(2026, 4, 22), num_days=1)
        # Read one snapshot back
        snap = SimulationCheckpoint.read(
            tmp_path / "seed_42_tick24.snapshot.json"
        )
        assert snap.seed == 42
        assert snap.tick_index == 24
        assert snap.provider == "stub"


class TestGracefulStopFinalSnapshot:

    def test_final_snapshot_written_on_graceful_stop(self, tmp_path: Path) -> None:
        orch, _, _ = _make_orch(date(2026, 4, 22))
        runner = MultiDayRunner(
            orchestrator=orch, seed=99, output_dir=tmp_path,
            provider_name="stub",
            snapshot_policy=SnapshotPolicy(every_ticks=100, keep_last_k=2),
        )

        # Trip graceful stop on day 1 tick 5
        def trip(tick_result):
            if tick_result.day_index == 1 and tick_result.tick_index >= 5:
                runner._graceful_stop_requested = True
        orch.register_on_tick_end(trip)

        runner.run_multi_day(start_date=date(2026, 4, 22), num_days=14)
        # Final snapshot exists
        final = tmp_path / "seed_99_tick_final.snapshot.json"
        assert final.exists()
        snap = SimulationCheckpoint.read(final)
        assert snap.seed == 99
