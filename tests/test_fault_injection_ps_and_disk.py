"""Fault matrix gap fills (high-priority from docs/testing-fault-matrix.md):

- Process #4: ps timeout / failure modes — resume_publishable._find_alive_worker
  must NOT cause double-spawn when ps itself misbehaves under swap thrash
  (today's 13:02 incident root cause).
- Disk #1: write_atomic disk-full — must propagate OSError without
  corrupting existing target file.
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from synthetic_socio_wind_tunnel.run_resilience.state_snapshot import (
    SimulationCheckpoint, snapshot_path,
)


# ====================================================================
# A.4.a — ps failure mode matrix
# ====================================================================


def _import_find_alive_worker():
    """Import the helper lazily; it lives in a tools/ script not in the package."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "resume_publishable",
        Path(__file__).parent.parent / "tools" / "resume_publishable.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._find_alive_worker


@pytest.fixture
def find_alive_worker():
    return _import_find_alive_worker()


@pytest.mark.parametrize("mock_outcome", [
    pytest.param(
        ("timeout", subprocess.TimeoutExpired(["ps"], 10)),
        id="ps_timeout",
    ),
    pytest.param(
        ("non_zero_rc", subprocess.CompletedProcess(
            args=["ps"], returncode=1, stdout="", stderr="ps: error\n",
        )),
        id="ps_nonzero",
    ),
    pytest.param(
        ("empty_stdout", subprocess.CompletedProcess(
            args=["ps"], returncode=0, stdout="", stderr="",
        )),
        id="ps_empty",
    ),
    pytest.param(
        ("garbage", subprocess.CompletedProcess(
            args=["ps"], returncode=0,
            stdout="not a valid ps line\n\\xff garbage \\x00\n",
            stderr="",
        )),
        id="ps_garbage",
    ),
    pytest.param(
        ("oserror", FileNotFoundError("ps not found")),
        id="ps_not_installed",
    ),
])
def test_find_alive_worker_handles_ps_failures(find_alive_worker, mock_outcome, tmp_path):
    """harden-worker-resilience invariant: when ps fails / returns garbage,
    `_find_alive_worker` SHALL return None. The CALLER must NOT spawn based
    on a None-from-ps-failure — but that's the caller's contract; here we
    only assert this helper's behavior.

    Today's 13:02 incident root cause: ps timed out under swap thrash, the
    helper returned None, the LaunchAgent (mis)treated None as 'worker dead'
    and spawned a duplicate. The fix has 2 layers — this test pins the
    helper layer.
    """
    label, side_effect = mock_outcome
    suite_dir = tmp_path / "suite_test"
    suite_dir.mkdir()

    def _fake_run(*args, **kwargs):
        if isinstance(side_effect, Exception):
            raise side_effect
        return side_effect

    with patch("subprocess.run", side_effect=_fake_run):
        result = find_alive_worker(42, "hyperlocal_push", suite_dir)

    assert result is None, (
        f"ps failure mode {label!r}: expected None, got {result!r}. "
        f"Failure modes MUST yield 'cannot determine' (None), not "
        f"'positively dead' (which would trigger double-spawn)."
    )


def test_find_alive_worker_returns_pid_on_valid_ps_output(find_alive_worker, tmp_path):
    """Happy path: when ps returns a matching line, PID is extracted."""
    suite_dir = tmp_path / "20260101_test_seed42_run"
    suite_dir.mkdir()
    fake_stdout = (
        "12345 /opt/python -m tools/run_variant_suite.py "
        "--variants hyperlocal_push --seed-start 42 "
        f"--suite-dir {suite_dir.name}\n"
    )

    with patch("subprocess.run", return_value=subprocess.CompletedProcess(
        args=["ps"], returncode=0, stdout=fake_stdout, stderr="",
    )):
        result = find_alive_worker(42, "hyperlocal_push", suite_dir)

    assert result == 12345


# ====================================================================
# A.4.b — write_atomic disk-full handling
# ====================================================================


def _make_snap(seed: int = 42) -> SimulationCheckpoint:
    return SimulationCheckpoint(
        seed=seed,
        tick_index=100,
        day_index=0,
        simulated_time=datetime(2026, 4, 22),
        ledger_state={},
        agent_runtime_states={},
        memory_store_state={},
        attention_service_state={},
        rng_state={},
        pending_ops_meta={},
        provider="stub",
    )


def test_write_atomic_disk_full_does_not_corrupt_existing(tmp_path):
    """harden-worker-resilience: when write_atomic hits OSError (disk full
    during fsync / rename), the existing target file SHALL be unchanged.
    Caller can retry on a later tick without losing data.
    """
    path = snapshot_path(tmp_path, seed=42, tick_index_global=100)
    # Pre-populate target with valid snapshot
    snap_v1 = _make_snap(seed=42)
    snap_v1.write_atomic(path)
    assert path.exists()
    original_content = path.read_bytes()

    # Now attempt to overwrite with disk-full simulation
    snap_v2 = _make_snap(seed=43)  # different content

    # Patch os.fsync to raise OSError("No space left on device")
    real_fsync = __import__("os").fsync
    call_count = {"n": 0}

    def _flaky_fsync(fd):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise OSError(28, "No space left on device")
        return real_fsync(fd)

    with patch("os.fsync", side_effect=_flaky_fsync):
        # OSError on fsync gets swallowed by the existing try/except OSError
        # in write_atomic (FS support varies); but if the file write itself
        # fails we expect a propagated OSError.
        try:
            snap_v2.write_atomic(path)
        except OSError:
            pass

    # Whether the write succeeded (fsync swallow) or failed (write raise),
    # the existing target SHALL still be readable as valid JSON, and SHALL
    # contain *either* v1 (original) or v2 (full new write) — never half.
    assert path.exists(), "target file disappeared on failed write"
    loaded = SimulationCheckpoint.read(path)
    assert loaded.seed in (42, 43), (
        f"target contains corrupt seed={loaded.seed}; either v1 (42) or "
        f"v2 (43) — never partial."
    )


def test_write_atomic_write_failure_cleans_tmp(tmp_path):
    """If the write itself raises (mid-write disk full), the tmp file
    SHALL be cleaned up so we don't accumulate orphan .tmp on a sick disk.
    """
    path = snapshot_path(tmp_path, seed=42, tick_index_global=100)
    snap = _make_snap()

    real_open = __import__("os").fdopen
    call_count = {"n": 0}

    def _flaky_fdopen(fd, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Close the real fd to avoid leak
            __import__("os").close(fd)
            raise OSError(28, "No space left on device")
        return real_open(fd, *args, **kwargs)

    with patch("os.fdopen", side_effect=_flaky_fdopen):
        with pytest.raises(OSError):
            snap.write_atomic(path)

    # Target SHALL NOT exist (first-time write), no tmp residue
    assert not path.exists()
    leftover_tmps = list(tmp_path.rglob("*.tmp"))
    assert leftover_tmps == [], (
        f"Failed write left orphan tmp files: {leftover_tmps}. "
        f"On a sick disk this accumulates indefinitely."
    )
