"""NEW-A (2026-05-21): watchdog respawn passes spawn-time env to subprocess.

Plan B added 4 hot-fix env vars (OPERATION_POOL_MAX_CONCURRENT_OPS,
OPERATION_POOL_HANDLER_TIMEOUT_SEC, RESILIENCE_POOL_READ_TIMEOUT,
RESILIENCE_RETRY_MAX_ATTEMPTS). Operators set them via per-worker
`nohup env <vars> ...` but the watchdog process inherits the SHELL's
env which doesn't have them. So watchdog auto-respawn silently
reverts to pre-Plan-B behavior.

Fix: worker writes spawn_env_<variant>.json at startup; watchdog
respawn reads it and merges into subprocess env.

Tests:
- spawn_env JSON file written at worker startup
- watchdog reads file + applies to respawn env
- missing/corrupt file → graceful fallback
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


_PLAN_B_KEYS = [
    "OPERATION_POOL_HANDLER_TIMEOUT_SEC",
    "OPERATION_POOL_MAX_CONCURRENT_OPS",
    "RESILIENCE_POOL_READ_TIMEOUT",
    "RESILIENCE_RETRY_MAX_ATTEMPTS",
    "RSS_RESTART_MB",
    "MEMORY_EVENT_EVICT_GRACE_DAYS",
    "SNAPSHOT_PRUNE_BEFORE_WRITE",
    "GC_EVERY_N_TICKS",
    "RSS_CHECK_EVERY_N_TICKS",
    "RESILIENCE_SNAPSHOT_EVERY_TICKS",
    "RESILIENCE_WAL_ENABLED",
]


def test_write_spawn_env_file_atomic(tmp_path: Path, monkeypatch):
    """run_variant_suite SHALL write spawn_env_<variant>.json
    capturing each Plan B env var currently set in os.environ."""
    from tools.run_variant_suite import _write_spawn_env_file  # to be added

    monkeypatch.setenv("OPERATION_POOL_MAX_CONCURRENT_OPS", "150")
    monkeypatch.setenv("RSS_RESTART_MB", "6000")
    monkeypatch.delenv("OPERATION_POOL_HANDLER_TIMEOUT_SEC", raising=False)

    out_file = _write_spawn_env_file(
        suite_dir=tmp_path, variant="baseline",
    )
    assert out_file.exists()
    payload = json.loads(out_file.read_text())
    assert payload["OPERATION_POOL_MAX_CONCURRENT_OPS"] == "150"
    assert payload["RSS_RESTART_MB"] == "6000"
    # Unset key omitted
    assert "OPERATION_POOL_HANDLER_TIMEOUT_SEC" not in payload


def test_watchdog_reads_spawn_env_and_merges(tmp_path: Path, monkeypatch):
    """watchdog._spawn_replacement SHALL include spawn_env values
    in the subprocess env."""
    from tools.watchdog_wal_deadlock import _spawn_replacement

    # Pre-populate spawn_env file with custom values
    spawn_env_file = tmp_path / "spawn_env_baseline.json"
    spawn_env_file.write_text(json.dumps({
        "OPERATION_POOL_MAX_CONCURRENT_OPS": "150",
        "RSS_RESTART_MB": "6000",
    }))

    # Ensure these are NOT in watchdog's own env
    monkeypatch.delenv("OPERATION_POOL_MAX_CONCURRENT_OPS", raising=False)
    monkeypatch.delenv("RSS_RESTART_MB", raising=False)

    captured_env: dict = {}
    def _fake_popen(*args, **kwargs):
        captured_env.update(kwargs.get("env", {}))
        proc = MagicMock()
        proc.poll.return_value = None
        proc.pid = 99999
        return proc

    with patch("tools.watchdog_wal_deadlock.subprocess.Popen", _fake_popen), \
         patch("tools.watchdog_wal_deadlock.time.sleep"):
        pid = _spawn_replacement(
            suite_dir=tmp_path, variant="baseline", seed=44,
        )
    # We sleep ~3s after spawn — but mocked Popen returns immediately
    assert pid == 99999
    assert captured_env.get("OPERATION_POOL_MAX_CONCURRENT_OPS") == "150"
    assert captured_env.get("RSS_RESTART_MB") == "6000"


def test_watchdog_missing_spawn_env_warns_and_proceeds(tmp_path: Path, caplog):
    """No spawn_env file → WARN + fallback to os.environ.copy()."""
    from tools.watchdog_wal_deadlock import _spawn_replacement

    captured_env: dict = {}
    def _fake_popen(*args, **kwargs):
        captured_env.update(kwargs.get("env", {}))
        proc = MagicMock()
        proc.poll.return_value = None
        proc.pid = 88888
        return proc

    with patch("tools.watchdog_wal_deadlock.subprocess.Popen", _fake_popen), \
         patch("tools.watchdog_wal_deadlock.time.sleep"), \
         caplog.at_level(logging.WARNING):
        pid = _spawn_replacement(
            suite_dir=tmp_path, variant="baseline", seed=44,
        )
    assert pid == 88888
    # Warning SHOULD mention spawn_env
    assert any(
        "spawn_env" in r.message.lower() for r in caplog.records
    ), f"Expected warning about missing spawn_env: {[r.message for r in caplog.records]}"


def test_watchdog_corrupt_spawn_env_warns_and_proceeds(tmp_path: Path, caplog):
    """Corrupt spawn_env JSON → WARN + fallback to os.environ.copy()."""
    from tools.watchdog_wal_deadlock import _spawn_replacement

    (tmp_path / "spawn_env_baseline.json").write_text("not json {{{")

    def _fake_popen(*args, **kwargs):
        proc = MagicMock()
        proc.poll.return_value = None
        proc.pid = 77777
        return proc

    with patch("tools.watchdog_wal_deadlock.subprocess.Popen", _fake_popen), \
         patch("tools.watchdog_wal_deadlock.time.sleep"), \
         caplog.at_level(logging.WARNING):
        pid = _spawn_replacement(
            suite_dir=tmp_path, variant="baseline", seed=44,
        )
    assert pid == 77777
    assert any(
        "spawn_env" in r.message.lower() and "corrupt" in r.message.lower()
        or ("spawn_env" in r.message.lower() and "parse" in r.message.lower())
        for r in caplog.records
    )
