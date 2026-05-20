"""R2 (2026-05-21): resume SHALL auto-backup existing snapshots.

2026-05-20 baseline scout lost its day 0 23:00 snapshot when manually
resumed for diag — the diag worker overwrote the original. R1's
PID-prefixed filename prevents SAME-PID collision, but an operator
running `--resume` on an output_dir with existing snapshots should
also get an auto-backup safety net.

Tests verify:
- Backup dir created with copy of existing snapshots BEFORE tick loop
- Backup failure (read-only dir) doesn't abort the resume
- env RESILIENCE_SKIP_RESUME_BACKUP=1 disables the backup
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from synthetic_socio_wind_tunnel.agent import AgentProfile, AgentRuntime
from synthetic_socio_wind_tunnel.atlas import Atlas
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.cartography.builder import RegionBuilder
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.orchestrator import (
    MultiDayRunner,
    Orchestrator,
)
from synthetic_socio_wind_tunnel.run_resilience.state_snapshot import (
    SimulationCheckpoint,
    snapshot_path,
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


def _make_orch_with_resume(start_date: date, snapshot_path_: Path) -> MultiDayRunner:
    atlas = _small_atlas()
    ledger = Ledger()
    ledger.current_time = datetime.combine(start_date, datetime.min.time())
    profile = AgentProfile(
        agent_id="alpha", name="alpha", age=30, occupation="x",
        household="single", home_location="a",
    )
    agent = AgentRuntime(profile=profile, current_location="a")
    ledger.set_entity(EntityState(
        entity_id=agent.profile.agent_id,
        location_id="a",
        position=Coord(x=0.0, y=0.0),
    ))
    orch = Orchestrator(atlas, ledger, [agent])
    snap = SimulationCheckpoint.read(snapshot_path_)
    return MultiDayRunner(
        orchestrator=orch, seed=42, mode="dev",
        output_dir=snapshot_path_.parent,
        restore_from=snap, provider_name="stub",
    )


def _write_minimal_snapshot(p: Path, seed: int = 42) -> Path:
    """Write a minimal valid snapshot file."""
    payload = {
        "schema_version": "3",
        "seed": seed,
        "day_index": 0,
        "tick_index": 12,
        "simulated_time": "2026-04-22T01:00:00",
        "created_at": "2026-05-21T00:00:00",
        "provider": "stub",
        "ledger_state": {"entities": {}, "items": {}, "current_time": "2026-04-22T01:00:00"},
        "agent_runtime_states": {},
        "memory_store_state": {},
        "attention_service_state": {},
        "tick_metrics_recorder_state": {},
        "dialogue_service_state": {},
        "rng_state": {},
        "pending_ops_meta": {},
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_backup_dir_created_before_first_snapshot_write(tmp_path: Path, monkeypatch):
    """Existing snapshot SHALL be copied to backup dir BEFORE any new
    snapshot is written during resume."""
    monkeypatch.delenv("RESILIENCE_SKIP_RESUME_BACKUP", raising=False)
    # Pre-existing snapshot
    pre_snap = snapshot_path(tmp_path, seed=42, tick_index_global=12, spawn_id=999)
    _write_minimal_snapshot(pre_snap, seed=42)

    # Trigger resume — uses the existing snapshot
    runner = _make_orch_with_resume(date(2026, 4, 22), pre_snap)
    # Run for very few ticks to exit quickly without burning LLM
    runner.run_multi_day(start_date=date(2026, 4, 22), num_days=1)

    # Backup dir must exist now
    backup_dirs = list(tmp_path.glob(".snapshot_backup_*"))
    assert len(backup_dirs) >= 1, (
        f"Expected at least 1 backup dir, found: {[d.name for d in tmp_path.iterdir()]}"
    )
    # And contain a copy of the pre-existing snapshot
    backed_up = list(backup_dirs[0].glob(pre_snap.name))
    assert len(backed_up) == 1


def test_env_skip_resume_backup_disables(tmp_path: Path, monkeypatch):
    """env=1 SHALL bypass the backup step entirely."""
    monkeypatch.setenv("RESILIENCE_SKIP_RESUME_BACKUP", "1")
    pre_snap = snapshot_path(tmp_path, seed=42, tick_index_global=12, spawn_id=999)
    _write_minimal_snapshot(pre_snap)

    runner = _make_orch_with_resume(date(2026, 4, 22), pre_snap)
    runner.run_multi_day(start_date=date(2026, 4, 22), num_days=1)

    backup_dirs = list(tmp_path.glob(".snapshot_backup_*"))
    assert len(backup_dirs) == 0, "env=1 SHOULD prevent backup creation"


def test_backup_failure_doesnt_block_resume(tmp_path: Path, monkeypatch, caplog):
    """If backup helper raises, resume SHALL still proceed (warning logged)."""
    import logging
    monkeypatch.delenv("RESILIENCE_SKIP_RESUME_BACKUP", raising=False)
    pre_snap = snapshot_path(tmp_path, seed=42, tick_index_global=12, spawn_id=999)
    _write_minimal_snapshot(pre_snap)

    # Force backup failure by patching shutil.copy2 to raise
    import shutil as _shutil
    orig_copy2 = _shutil.copy2
    def _fail_copy2(*args, **kw):
        raise OSError("simulated disk full")
    with patch.object(_shutil, "copy2", _fail_copy2):
        runner = _make_orch_with_resume(date(2026, 4, 22), pre_snap)
        with caplog.at_level(logging.WARNING):
            result = runner.run_multi_day(start_date=date(2026, 4, 22), num_days=1)

    # Resume completed despite backup failure
    assert result.total_ticks > 0
    # Warning was logged
    assert any("backup" in r.message.lower() for r in caplog.records), (
        f"Expected backup warning in log; got: {[r.message for r in caplog.records]}"
    )
