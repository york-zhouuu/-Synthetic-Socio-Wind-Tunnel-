"""Tests for capture_rng / restore_rng + WAL writer/reader."""

from __future__ import annotations

import json
import random
from datetime import datetime
from pathlib import Path

import pytest

from synthetic_socio_wind_tunnel.run_resilience.state_snapshot import (
    WALWriter,
    capture_rng,
    read_last_wal_line,
    restore_rng,
)


class TestCaptureRestoreRNG:

    def test_capture_then_restore_reproduces_sequence(self) -> None:
        rng_a = random.Random(42)
        # Burn some entropy
        for _ in range(100):
            rng_a.random()
        # Capture
        state = capture_rng({"a": rng_a})

        # Continue rng_a to get the expected next value
        expected_next = rng_a.random()

        # Construct a fresh rng_b, restore from state, verify next == expected_next
        rng_b = random.Random()
        restore_rng(state, {"a": rng_b})
        actual_next = rng_b.random()
        assert actual_next == expected_next

    def test_capture_multiple_named(self) -> None:
        rngs = {"orch": random.Random(1), "collapse": random.Random(2)}
        state = capture_rng(rngs)
        assert set(state.keys()) == {"orch", "collapse"}
        # Each is a JSON-safe list
        json.dumps(state)  # would raise if non-serializable

    def test_state_is_json_safe(self) -> None:
        """getstate() returns nested tuples; capture must convert to lists."""
        state = capture_rng({"x": random.Random(99)})
        # Round-trip through JSON
        s = json.dumps(state)
        state2 = json.loads(s)
        # Restore from the JSON-roundtripped state must still work
        rng_clone = random.Random()
        restore_rng(state2, {"x": rng_clone})
        # Should match
        rng_ref = random.Random(99)
        assert rng_clone.random() == rng_ref.random()

    def test_missing_key_warns_but_does_not_raise(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        state = capture_rng({"orch": random.Random(1)})
        # state has "orch" but caller passes both "orch" and "collapse"
        rngs = {"orch": random.Random(), "collapse": random.Random()}
        with caplog.at_level("WARNING"):
            restore_rng(state, rngs)
        assert any("collapse" in rec.message for rec in caplog.records)


class TestWAL:

    def test_append_writes_line(self, tmp_path: Path) -> None:
        w = WALWriter(output_dir=tmp_path, seed=42, fsync_every_ticks=1)
        w.append(
            tick_index=0, day_index=0,
            simulated_time=datetime(2026, 4, 22, 8, 0),
            commits_succeeded=5, commits_failed=0, encounter_count=2,
        )
        w.close()
        wal_file = tmp_path / "seed_42.wal.jsonl"
        assert wal_file.exists()
        lines = wal_file.read_text().strip().split("\n")
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["tick_index"] == 0
        assert rec["commits_succeeded"] == 5

    def test_append_many_lines(self, tmp_path: Path) -> None:
        with WALWriter(output_dir=tmp_path, seed=1, fsync_every_ticks=10) as w:
            for t in range(50):
                w.append(
                    tick_index=t, day_index=0,
                    simulated_time=datetime(2026, 4, 22, 8, 0),
                    commits_succeeded=1, commits_failed=0, encounter_count=0,
                )
        lines = (tmp_path / "seed_1.wal.jsonl").read_text().strip().split("\n")
        assert len(lines) == 50
        last = json.loads(lines[-1])
        assert last["tick_index"] == 49

    def test_read_last_wal_line(self, tmp_path: Path) -> None:
        with WALWriter(output_dir=tmp_path, seed=7) as w:
            for t in range(3):
                w.append(
                    tick_index=t, day_index=0,
                    simulated_time=datetime(2026, 4, 22, 8, t),
                    commits_succeeded=t, commits_failed=0, encounter_count=t,
                )
        wal_file = tmp_path / "seed_7.wal.jsonl"
        last = read_last_wal_line(wal_file)
        assert last is not None
        assert last["tick_index"] == 2
        assert last["commits_succeeded"] == 2

    def test_read_last_wal_line_empty_file(self, tmp_path: Path) -> None:
        wal_file = tmp_path / "seed_x.wal.jsonl"
        wal_file.write_text("")
        assert read_last_wal_line(wal_file) is None

    def test_read_last_wal_line_missing_file(self, tmp_path: Path) -> None:
        assert read_last_wal_line(tmp_path / "nope.wal.jsonl") is None

    def test_snapshot_path_in_wal_entry(self, tmp_path: Path) -> None:
        with WALWriter(output_dir=tmp_path, seed=1) as w:
            w.append(
                tick_index=24, day_index=0,
                simulated_time=datetime(2026, 4, 22, 10, 0),
                commits_succeeded=10, commits_failed=0, encounter_count=3,
                snapshot_path=tmp_path / "seed_1_tick24.snapshot.json",
            )
        rec = read_last_wal_line(tmp_path / "seed_1.wal.jsonl")
        assert rec is not None
        assert "tick24" in rec["snapshot_path"]

    def test_no_snapshot_path_is_null(self, tmp_path: Path) -> None:
        with WALWriter(output_dir=tmp_path, seed=1) as w:
            w.append(
                tick_index=1, day_index=0,
                simulated_time=datetime(2026, 4, 22, 8, 0),
                commits_succeeded=0, commits_failed=0, encounter_count=0,
            )
        rec = read_last_wal_line(tmp_path / "seed_1.wal.jsonl")
        assert rec is not None
        assert rec["snapshot_path"] is None
