"""Tests for SimulationCheckpoint + SnapshotPolicy + snapshot file helpers."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from synthetic_socio_wind_tunnel.run_resilience import IncompatibleCheckpointError
from synthetic_socio_wind_tunnel.run_resilience.state_snapshot import (
    SimulationCheckpoint,
    SnapshotPolicy,
    find_latest_snapshot,
    prune_snapshots,
    snapshot_path,
)


def _make(seed: int = 42, tick_index: int = 100, day_index: int = 0) -> SimulationCheckpoint:
    return SimulationCheckpoint(
        seed=seed,
        tick_index=tick_index,
        day_index=day_index,
        simulated_time=datetime(2026, 4, 22, 8, 20),
        ledger_state={},
        agent_runtime_states={},
        memory_store_state={},
        attention_service_state={},
        rng_state={},
        pending_ops_meta={},
        provider="stub",
    )


class TestSimulationCheckpointFields:

    def test_default_schema_version_is_current(self) -> None:
        # Bumped to "3" on 2026-05-19 (capability 1.12 — adds
        # dialogue_service_state). v2 added tick_metrics_recorder_state.
        # v1 snapshots are rejected.
        snap = _make()
        assert snap.schema_version == "3"

    def test_required_fields_set(self) -> None:
        snap = _make(seed=42, tick_index=100, day_index=0)
        assert snap.seed == 42
        assert snap.tick_index == 100
        assert snap.day_index == 0
        assert snap.simulated_time == datetime(2026, 4, 22, 8, 20)

    def test_model_dump_is_json_safe(self) -> None:
        snap = _make()
        # mode="json" must produce a fully JSON-serializable dict
        s = json.dumps(snap.model_dump(mode="json"), ensure_ascii=False)
        assert "schema_version" in s
        assert "seed" in s

    def test_frozen(self) -> None:
        snap = _make()
        with pytest.raises(Exception):
            snap.tick_index = 200  # type: ignore[misc]


class TestAtomicWrite:

    def test_round_trip(self, tmp_path: Path) -> None:
        snap = _make(seed=42, tick_index=100, day_index=0)
        path = snapshot_path(tmp_path, seed=42, tick_index_global=100)
        snap.write_atomic(path)
        assert path.exists()
        snap2 = SimulationCheckpoint.read(path)
        assert snap2.model_dump(mode="json") == snap.model_dump(mode="json")

    def test_no_tmp_residue_after_normal_write(self, tmp_path: Path) -> None:
        snap = _make()
        path = snapshot_path(tmp_path, seed=42, tick_index_global=100)
        snap.write_atomic(path)
        assert list(tmp_path.glob("*.tmp")) == []

    def test_cleans_pre_existing_tmp(self, tmp_path: Path) -> None:
        path = snapshot_path(tmp_path, seed=42, tick_index_global=100)
        path.parent.mkdir(exist_ok=True, parents=True)
        stale = path.with_suffix(path.suffix + ".tmp")
        stale.write_text("garbage from previous crashed write")
        assert stale.exists()
        snap = _make()
        snap.write_atomic(path)
        assert not stale.exists()

    def test_read_incompatible_schema_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "seed_42_tick100.snapshot.json"
        path.write_text(json.dumps({
            "schema_version": "99",
            "seed": 42, "tick_index": 100, "day_index": 0,
            "simulated_time": "2026-04-22T08:20:00",
            "ledger_state": {}, "agent_runtime_states": {},
            "memory_store_state": {}, "attention_service_state": {},
            "rng_state": {}, "pending_ops_meta": {},
            "provider": "stub", "created_at": "2026-04-22T08:20:00",
        }))
        with pytest.raises(IncompatibleCheckpointError) as exc_info:
            SimulationCheckpoint.read(path)
        assert exc_info.value.expected == "3"
        assert exc_info.value.found == "99"

    def test_read_v1_snapshot_upgrades_in_place(self, tmp_path: Path) -> None:
        """v1 snapshot (pre-2026-05-19) missing tick_metrics_recorder_state
        + dialogue_service_state SHALL load with empty defaults."""
        path = tmp_path / "seed_42_tick100.snapshot.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "seed": 42, "tick_index": 100, "day_index": 0,
            "simulated_time": "2026-04-22T08:20:00",
            "ledger_state": {}, "agent_runtime_states": {},
            "memory_store_state": {}, "attention_service_state": {},
            "rng_state": {}, "pending_ops_meta": {},
            "provider": "stub", "created_at": "2026-04-22T08:20:00",
        }))
        snap = SimulationCheckpoint.read(path)
        assert snap.schema_version == "3"  # upgraded in memory
        assert snap.tick_metrics_recorder_state == {}
        assert snap.dialogue_service_state == {}
        assert snap.seed == 42

    def test_read_v2_snapshot_upgrades_in_place(self, tmp_path: Path) -> None:
        """v2 snapshot (between 1.11 and 1.12 commits) SHALL load with
        dialogue_service_state defaulting to {}."""
        path = tmp_path / "seed_42_tick100.snapshot.json"
        path.write_text(json.dumps({
            "schema_version": "2",
            "seed": 42, "tick_index": 100, "day_index": 0,
            "simulated_time": "2026-04-22T08:20:00",
            "ledger_state": {}, "agent_runtime_states": {},
            "memory_store_state": {}, "attention_service_state": {},
            "tick_metrics_recorder_state": {"current_day": 5, "buckets": {}},
            "rng_state": {}, "pending_ops_meta": {},
            "provider": "stub", "created_at": "2026-04-22T08:20:00",
        }))
        snap = SimulationCheckpoint.read(path)
        assert snap.schema_version == "3"
        assert snap.dialogue_service_state == {}
        assert snap.tick_metrics_recorder_state == {
            "current_day": 5, "buckets": {},
        }


class TestSnapshotFileHelpers:

    def _make_files(self, dir_: Path, seed: int, ticks: list[int]) -> None:
        for t in ticks:
            (dir_ / f"seed_{seed}_tick{t}.snapshot.json").write_text("{}")

    def test_find_latest_snapshot_picks_max_tick(self, tmp_path: Path) -> None:
        self._make_files(tmp_path, 42, [24, 96, 48, 72])
        latest = find_latest_snapshot(tmp_path, seed=42)
        assert latest is not None
        assert latest.name == "seed_42_tick96.snapshot.json"

    def test_find_latest_snapshot_none_when_empty(self, tmp_path: Path) -> None:
        assert find_latest_snapshot(tmp_path, seed=42) is None

    def test_find_latest_snapshot_seed_isolated(self, tmp_path: Path) -> None:
        self._make_files(tmp_path, 42, [24, 48])
        self._make_files(tmp_path, 99, [200])
        latest = find_latest_snapshot(tmp_path, seed=42)
        assert latest is not None and "seed_42" in latest.name

    def test_prune_keeps_last_k(self, tmp_path: Path) -> None:
        self._make_files(tmp_path, 42, [24, 48, 72, 96])
        deleted = prune_snapshots(tmp_path, seed=42, keep=2)
        # Should delete 24 and 48
        deleted_ticks = sorted(int(p.name.split("tick")[1].split(".")[0]) for p in deleted)
        assert deleted_ticks == [24, 48]
        remaining = sorted(
            int(p.name.split("tick")[1].split(".")[0])
            for p in tmp_path.glob("seed_42_tick*.snapshot.json")
        )
        assert remaining == [72, 96]

    def test_prune_no_op_when_under_k(self, tmp_path: Path) -> None:
        self._make_files(tmp_path, 42, [24, 48])
        deleted = prune_snapshots(tmp_path, seed=42, keep=5)
        assert deleted == []
        assert len(list(tmp_path.glob("seed_42_*"))) == 2

    def test_prune_seed_isolated(self, tmp_path: Path) -> None:
        self._make_files(tmp_path, 42, [24, 48, 72])
        self._make_files(tmp_path, 99, [100, 200])
        prune_snapshots(tmp_path, seed=42, keep=1)
        # Only seed_42 pruned; seed_99 untouched
        s42 = list(tmp_path.glob("seed_42_*"))
        s99 = list(tmp_path.glob("seed_99_*"))
        assert len(s42) == 1
        assert len(s99) == 2


class TestSnapshotPolicy:

    def test_defaults(self) -> None:
        p = SnapshotPolicy()
        assert p.every_ticks == 24
        assert p.keep_last_k == 2
        assert p.wal_enabled is True
        assert p.wal_fsync_every_ticks == 1

    def test_frozen(self) -> None:
        p = SnapshotPolicy()
        with pytest.raises(Exception):
            p.every_ticks = 48  # type: ignore[misc]

    def test_from_env_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RESILIENCE_SNAPSHOT_EVERY_TICKS", "48")
        monkeypatch.setenv("RESILIENCE_SNAPSHOT_KEEP_LAST", "3")
        monkeypatch.setenv("RESILIENCE_WAL_ENABLED", "false")
        monkeypatch.setenv("RESILIENCE_WAL_FSYNC_EVERY_TICKS", "5")
        p = SnapshotPolicy.from_env()
        assert p.every_ticks == 48
        assert p.keep_last_k == 3
        assert p.wal_enabled is False
        assert p.wal_fsync_every_ticks == 5

    def test_from_env_invalid_falls_back(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setenv("RESILIENCE_SNAPSHOT_EVERY_TICKS", "abc")
        with caplog.at_level("WARNING"):
            p = SnapshotPolicy.from_env()
        assert p.every_ticks == 24
        assert any("无法解析" in rec.message for rec in caplog.records)

    def test_from_env_bool_variants(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for raw, expected in [
            ("1", True), ("0", False),
            ("True", True), ("False", False),
            ("yes", True), ("no", False),
            ("on", True), ("off", False),
        ]:
            monkeypatch.setenv("RESILIENCE_WAL_ENABLED", raw)
            p = SnapshotPolicy.from_env()
            assert p.wal_enabled is expected, f"{raw} → {expected}"

    def test_from_env_out_of_range_caught_by_pydantic(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # every_ticks max is 288; 999 should be rejected by Pydantic
        monkeypatch.setenv("RESILIENCE_SNAPSHOT_EVERY_TICKS", "999")
        with pytest.raises(Exception):
            SnapshotPolicy.from_env()
