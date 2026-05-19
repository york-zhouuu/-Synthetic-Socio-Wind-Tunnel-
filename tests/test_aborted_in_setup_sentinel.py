"""Tests for harden-worker-resilience: SIGUSR1 setup-phase 哨兵.

When SIGUSR1 fires before any day completes, MultiDayRunner must
NOT write a misleading partial. Instead, write
`seed_N.aborted_in_setup.json` so external audit / resume_publishable
can distinguish "aborted in setup" from "INTERRUPTED with progress".
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from synthetic_socio_wind_tunnel.orchestrator.multi_day import MultiDayRunner


@pytest.fixture
def runner_with_output_dir(tmp_path: Path) -> MultiDayRunner:
    """Construct a minimal MultiDayRunner with output_dir set.

    The runner is created bare; we only exercise _write_aborted_in_setup_sentinel
    + the metadata path, not the full run_multi_day loop.
    """
    runner = MultiDayRunner.__new__(MultiDayRunner)
    runner._seed = 42
    runner._output_dir = tmp_path
    runner._wal_writer = None
    runner._graceful_stop_requested = True  # we are testing setup-phase abort
    return runner


def test_sentinel_written_on_setup_phase_abort(
    runner_with_output_dir: MultiDayRunner, tmp_path: Path,
) -> None:
    runner_with_output_dir._write_aborted_in_setup_sentinel()
    sentinel = tmp_path / "seed_42.aborted_in_setup.json"
    assert sentinel.exists()
    payload = json.loads(sentinel.read_text())
    assert payload["seed"] == 42
    assert payload["reason"] == "SIGUSR1 received during setup phase"
    assert payload["completed_days"] == 0
    assert payload["wal_writes"] == 0
    # ISO timestamp parseable
    assert datetime.fromisoformat(payload["aborted_at"].rstrip("Z"))


def test_no_partial_files_in_setup_phase_abort(
    runner_with_output_dir: MultiDayRunner, tmp_path: Path,
) -> None:
    """Sentinel writing must NOT create any `seed_N_day*.partial.json`."""
    runner_with_output_dir._write_aborted_in_setup_sentinel()
    partials = list(tmp_path.glob("seed_*_day*.partial.json"))
    assert partials == []


def test_sentinel_skipped_when_output_dir_none(tmp_path: Path) -> None:
    """No output_dir => silent no-op (dev mode without persistence)."""
    runner = MutableMock()
    runner._seed = 99
    runner._output_dir = None
    runner._wal_writer = None
    MultiDayRunner._write_aborted_in_setup_sentinel(runner)
    # Nothing to assert other than no crash + no file
    assert list(tmp_path.glob("*")) == []


class MutableMock:
    """Simple mutable namespace — MagicMock would auto-create attrs."""


def test_aborted_in_setup_metadata_set_by_runner(tmp_path: Path) -> None:
    """End-to-end (lightweight): when MultiDayRunner.run_multi_day exits
    with _graceful_stop_requested=True and per_day=[], result.metadata
    SHALL contain aborted_in_setup=True."""
    # We mock the inner orchestrator + collectors so the loop never
    # completes a day. Then trigger graceful_stop before the first
    # day_index iteration.
    runner = MultiDayRunner.__new__(MultiDayRunner)
    runner._seed = 7
    runner._output_dir = tmp_path
    runner._mode = "dev"
    runner._resume_from = 0
    runner._graceful_stop_requested = False
    runner._planner = None
    runner._llm_client = None
    runner._memory_service = None
    runner._attention_service = None
    runner._tick_metrics_recorder = None
    runner._dialogue_service = None
    runner._provider_name = "stub"
    runner._snapshot_policy = MagicMock()
    runner._snapshot_policy.wal_enabled = False
    runner._snapshot_policy.every_ticks = 0
    runner._snapshot_policy.keep_last_k = 1
    runner._snapshot_policy.wal_fsync_every_ticks = 0
    runner._wal_writer = None
    # restore_into path
    runner._restore_from = None

    # Fake orchestrator with no agents and a tick loop we'll never enter
    fake_orch = MagicMock()
    fake_orch._agents = []
    fake_orch._ticks_per_day = 1
    fake_orch._hooks = {"on_tick_end": []}

    def _register(hook):
        fake_orch._hooks["on_tick_end"].append(hook)

    fake_orch.register_on_tick_end = _register

    def _abort_immediately(*args, **kwargs):
        # Pre-day hook fires graceful_stop, then the for-loop catches it
        runner._graceful_stop_requested = True
        # Run never produces a DaySummary — simulate raise of _GracefulStop
        from synthetic_socio_wind_tunnel.orchestrator.multi_day import (
            _GracefulStop,
        )
        raise _GracefulStop()

    fake_orch.run = _abort_immediately
    runner._orchestrator = fake_orch

    from datetime import date

    result = runner.run_multi_day(start_date=date(2026, 4, 22), num_days=2)
    assert result.metadata["graceful_stop"] is True
    assert result.metadata["aborted_in_setup"] is True
    assert result.per_day_summaries == ()
    sentinel = tmp_path / "seed_7.aborted_in_setup.json"
    assert sentinel.exists()
